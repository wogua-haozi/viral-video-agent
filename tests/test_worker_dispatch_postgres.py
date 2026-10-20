"""Opt-in dispatch checks against dedicated PostgreSQL and Redis test services.

PILOT_TEST_POSTGRES_URL and PILOT_TEST_REDIS_URL must both explicitly select test
services. PostgreSQL uses the existing random-schema sandbox; Redis uses a unique
queue and removes only this test's known keys, never FLUSHDB/FLUSHALL.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from arq import create_pool
from arq.connections import RedisSettings
from arq.constants import (
    health_check_key_suffix, in_progress_key_prefix, job_key_prefix,
    result_key_prefix, retry_key_prefix,
)
from arq.jobs import JobStatus
from arq.worker import Worker

from src import dispatch, worker
from src.api import job_routes
from src.db.models import AnalysisJob
from src.queue import JobQueue
from tests.test_creator_pilot_postgres import PILOT, migrate, postgres_db
from tests.test_worker_claim_recovery import Queue, disconnected, pending_job, read_state


@pytest_asyncio.fixture
async def postgres_factory(postgres_db, monkeypatch):
    await migrate(postgres_db, PILOT)
    monkeypatch.setattr(dispatch, "async_session_factory", postgres_db.factory)
    monkeypatch.setattr(worker, "async_session_factory", postgres_db.factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", False)
    monkeypatch.setattr(worker, "ENABLE_CANDIDATE_CONFIRMATION", False)
    monkeypatch.setattr(worker, "WORKER_HEARTBEAT_SECONDS", 60)
    return postgres_db.factory


@pytest_asyncio.fixture
async def redis_queue():
    url = os.getenv("PILOT_TEST_REDIS_URL")
    if not url:
        pytest.skip("PILOT_TEST_REDIS_URL is not explicitly configured")
    name = "pilot_test_dispatch_" + uuid.uuid4().hex
    pool = await create_pool(RedisSettings.from_dsn(url), default_queue_name=name)
    owned_ids = set()
    queue = JobQueue(pool)
    try:
        yield SimpleNamespace(queue=queue, pool=pool, name=name, ids=owned_ids)
    finally:
        keys = [name, name + health_check_key_suffix]
        for job_id in owned_ids:
            keys.extend(prefix + job_id for prefix in (
                job_key_prefix, in_progress_key_prefix, result_key_prefix, retry_key_prefix,
            ))
        await pool.delete(*keys)
        await pool.aclose()


@pytest.mark.asyncio
async def test_postgres_parallel_unclaimed_recovery_fences_once(postgres_factory):
    job_id = await pending_job(postgres_factory)
    now = datetime.now(timezone.utc)
    queue = Queue(JobStatus.complete)
    results = await asyncio.gather(*(
        dispatch.recover_unclaimed_jobs(queue, now) for _ in range(4)
    ))
    assert sum(results) == 1
    job, usage = await read_state(postgres_factory, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("pending", 1, 1)
    assert (usage.input_tokens, usage.asr_seconds) == (11, 3)


@pytest.mark.asyncio
async def test_actual_arq_claim_failure_recovers_past_retained_result(postgres_factory, redis_queue, monkeypatch):
    job_id = await pending_job(postgres_factory)
    ids = [f"analysis:{job_id}:v{version}" for version in (0, 1)]
    redis_queue.ids.update(ids)
    queue = redis_queue.queue
    assert await queue.status(ids[0]) == JobStatus.not_found
    await queue.enqueue(str(job_id), 0)
    assert await queue.status(ids[0]) == JobStatus.queued
    original_claim = worker._claim_job_once
    failures = []
    executions = []

    async def fail_initial_claim(job_id, version, token, arq_job_id=None):
        if version == 0:
            failures.append(token)
            raise disconnected()
        return await original_claim(job_id, version, token, arq_job_id)

    async def local_execution(_ctx, job, _synthesis, _execution):
        assert await queue.status(f"analysis:{job.id}:v{job.execution_version}") == JobStatus.in_progress
        executions.append(job.execution_version)
        async with postgres_factory() as db:
            current = await db.get(AnalysisJob, job.id)
            current.status = "completed"
            await db.commit()

    monkeypatch.setattr(worker, "_claim_job_once", fail_initial_claim)
    monkeypatch.setattr(worker, "_execute_job", local_execution)

    async def run_one():
        runner = Worker(
            [worker.run_analysis_job], redis_pool=redis_queue.pool, queue_name=redis_queue.name,
            burst=True, max_burst_jobs=1, handle_signals=False, poll_delay=0.01,
            log_results=False,
        )
        await asyncio.wait_for(runner.async_run(), 10)
        return runner

    first = await run_one()
    assert first.jobs_failed == 1 and len(failures) == 3 and len(set(failures)) == 1
    job, _ = await read_state(postgres_factory, job_id)
    assert job.status == "pending"
    assert await queue.status(ids[0]) == JobStatus.complete
    # The retained failed result makes a same-ID enqueue a no-op in real Arq.
    await queue.enqueue(str(job_id), 0)
    assert await queue.status(ids[0]) == JobStatus.complete
    assert await dispatch.reconcile_pending_dispatches(queue=queue) == {"leased": 1, "recovered": 1, "failed": 0}
    assert await queue.status(ids[1]) == JobStatus.queued
    await dispatch.reconcile_pending_dispatches(queue=queue)
    second = await run_one()
    assert second.jobs_complete == 1 and executions == [1]
    job, usage = await read_state(postgres_factory, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("completed", 1, 1)
    assert (usage.input_tokens, usage.asr_seconds) == (11, 3)


@pytest.mark.asyncio
async def test_actual_arq_deferred_delivery_is_preserved(postgres_factory, redis_queue):
    job_id = await pending_job(postgres_factory)
    arq_id = f"analysis:{job_id}:v0"
    redis_queue.ids.add(arq_id)
    await redis_queue.pool.enqueue_job(
        "run_analysis_job", str(job_id), 0, _job_id=arq_id, _defer_by=60,
    )
    assert await redis_queue.queue.status(arq_id) == JobStatus.deferred
    assert await dispatch.reconcile_pending_dispatches(queue=redis_queue.queue) == {"leased": 0, "recovered": 0, "failed": 0}
    job, _ = await read_state(postgres_factory, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("pending", 0, 0)


@pytest.mark.asyncio
async def test_actual_arq_fast_claim_before_api_ack_recovers_after_retry_claim_failure(
    postgres_factory, redis_queue, monkeypatch,
):
    job_id = await pending_job(
        postgres_factory, arq_job_id=None, dispatch_pending_at=datetime.now(timezone.utc),
    )
    # Use the actual delivery ID from Arq, not a manufactured DB acknowledgement.
    initial_id = f"pilot-delivery:{uuid.uuid4()}"
    recovered_id = f"analysis:{job_id}:v1"
    redis_queue.ids.update({initial_id, recovered_id})
    queue = redis_queue.queue
    entered = asyncio.Event()
    api_returned = asyncio.Event()
    executions = []
    failed_claim_tokens = []
    fail_retry_claim = False
    original_claim = worker._claim_job_once

    async def controlled_claim(job_id, version, token, *args, **kwargs):
        if fail_retry_claim and version == 0:
            failed_claim_tokens.append(token)
            raise disconnected()
        return await original_claim(job_id, version, token, *args, **kwargs)

    async def local_execution(ctx, job, _synthesis, _execution):
        executions.append(job.execution_version)
        if job.execution_version == 0:
            assert ctx["job_id"] == initial_id
            entered.set()
            await api_returned.wait()
            raise ConnectionError("local transient execution fixture")
        async with postgres_factory() as db:
            current = await db.get(AnalysisJob, job.id)
            current.status = "completed"
            await db.commit()

    async def run_one():
        runner = Worker(
            [worker.run_analysis_job], redis_pool=redis_queue.pool, queue_name=redis_queue.name,
            burst=True, max_burst_jobs=1, handle_signals=False, poll_delay=0.01,
            log_results=False,
        )
        await asyncio.wait_for(runner.async_run(), 10)
        return runner

    first_worker = None

    class FastWorkerQueue:
        async def enqueue(self, job_id_value, version):
            nonlocal first_worker
            await redis_queue.pool.enqueue_job(
                "run_analysis_job", job_id_value, version, _job_id=initial_id,
            )
            first_worker = asyncio.create_task(run_one())
            # The API cannot fill arq_job_id once this transaction has claimed
            # the job and moved it to running.
            await asyncio.wait_for(entered.wait(), 5)
            return initial_id

    monkeypatch.setattr(worker, "_claim_job_once", controlled_claim)
    monkeypatch.setattr(worker, "_execute_job", local_execution)
    try:
        async with postgres_factory() as db:
            api_result = await job_routes._enqueue_committed_job(db, FastWorkerQueue(), job_id, 0)
            assert api_result.status == "running"
    finally:
        api_returned.set()
        if first_worker:
            first = await first_worker
    assert first.jobs_retried == 1
    after_retry, _ = await read_state(postgres_factory, job_id)
    assert (after_retry.status, after_retry.retry_count) == ("pending", 1)
    assert await queue.status(initial_id) == JobStatus.deferred

    fail_retry_claim = True
    # Advance only this isolated delivery's scheduled score; no production
    # retry timing or shared Redis keys are changed.
    await redis_queue.pool.zadd(redis_queue.name, {initial_id: 1})
    second = await run_one()
    assert second.jobs_failed == 1
    assert len(failed_claim_tokens) == 3 and len(set(failed_claim_tokens)) == 1
    assert await queue.status(initial_id) == JobStatus.complete
    reconcile_at = datetime.now(timezone.utc) + timedelta(
        seconds=dispatch.DISPATCH_RECONCILE_MIN_AGE_SECONDS + 1,
    )
    assert await dispatch.reconcile_pending_dispatches(queue=queue, now=reconcile_at) == {
        "leased": 1, "recovered": 1, "failed": 0,
    }
    assert after_retry.arq_job_id == initial_id
    assert await queue.status(recovered_id) == JobStatus.queued
    third = await run_one()
    assert third.jobs_complete == 1 and executions == [0, 1]
    job, usage = await read_state(postgres_factory, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("completed", 1, 2)
    assert (usage.input_tokens, usage.asr_seconds) == (11, 3)
