"""Claim failures and acknowledged-but-unclaimed deliveries use only local fixtures."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from arq import Retry
from arq.jobs import JobStatus
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src import dispatch, worker
from src.db.models import (
    AnalysisJob, CandidateDecisionBatch, CandidateSnapshot, CandidateSynthesisRun,
    CollectionSnapshot, JobEvent, UsageRecord, User,
)
from src.db.session import Base
from src.utils.asr_usage_tracker import asr_usage_tracker


@pytest_asyncio.fixture
async def database(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'claims.db'}", poolclass=NullPool,
        connect_args={"timeout": 30},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(worker, "async_session_factory", factory)
    monkeypatch.setattr(dispatch, "async_session_factory", factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", False)
    monkeypatch.setattr(worker, "ENABLE_CANDIDATE_CONFIRMATION", False)
    monkeypatch.setattr(worker, "WORKER_HEARTBEAT_SECONDS", 60)
    yield factory
    await engine.dispose()


async def pending_job(factory, **overrides):
    async with factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.invalid", hashed_password="local-fixture")
        db.add(user)
        await db.flush()
        job_id = uuid.uuid4()
        values = dict(
            id=job_id, user_id=user.id, query="公开样本研究", platforms=["bilibili"],
            analysis_mode="standard", status="pending", execution_version=0,
            retry_count=0, idempotency_key=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
            arq_job_id=f"analysis:{job_id}:v0",
        )
        values.update(overrides)
        job = AnalysisJob(**values)
        db.add(job)
        await db.flush()
        db.add(UsageRecord(user_id=user.id, job_id=job.id, input_tokens=11, asr_seconds=3))
        await db.commit()
        return job.id


async def read_state(factory, job_id):
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        records = list((await db.scalars(select(UsageRecord).where(UsageRecord.job_id == job_id))).all())
        assert len(records) == 1
        return job, records[0]


def disconnected():
    return OperationalError("local fixture", {}, ConnectionError("local fixture"), connection_invalidated=True)


class Queue:
    def __init__(self, status):
        self.current_status = status
        self.inspected = []
        self.enqueued = []

    async def status(self, job_id):
        self.inspected.append(job_id)
        if isinstance(self.current_status, Exception):
            raise self.current_status
        return self.current_status

    async def enqueue(self, job_id, version):
        self.enqueued.append((job_id, version))
        return f"analysis:{job_id}:v{version}"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_factory", [disconnected, ConnectionRefusedError, TimeoutError])
async def test_claim_retries_transient_connection_failure_with_same_token(database, monkeypatch, error_factory):
    job_id = await pending_job(database)
    original = worker._claim_job_once
    tokens = []

    async def interrupted(job_id, version, token):
        tokens.append(token)
        if len(tokens) < 3:
            raise error_factory()
        return await original(job_id, version, token)

    monkeypatch.setattr(worker, "_claim_job_once", interrupted)
    claimed = await worker._claim_job(job_id, 0)
    assert claimed is not None
    assert len(tokens) == 3 and len(set(tokens)) == 1
    job, usage = await read_state(database, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("running", 0, 0)
    assert (usage.input_tokens, usage.asr_seconds) == (11, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_factory", [disconnected, TimeoutError])
async def test_claim_commit_acknowledgement_loss_reclaims_only_its_own_token(database, monkeypatch, error_factory):
    job_id = await pending_job(database)
    commits = 0

    @asynccontextmanager
    async def lost_ack_factory():
        nonlocal commits
        async with database() as db:
            commit = db.commit

            async def lose_first_ack():
                nonlocal commits
                await commit()
                commits += 1
                if commits == 1:
                    raise error_factory()

            db.commit = lose_first_ack
            yield db

    monkeypatch.setattr(worker, "async_session_factory", lost_ack_factory)
    claimed = await worker._claim_job(job_id, 0)
    assert claimed is not None and commits == 2
    assert await worker._claim_job(job_id, 0) is None
    job, usage = await read_state(database, job_id)
    assert job.worker_token == claimed[2] and job.status == "running"
    assert usage.input_tokens == 11


@pytest.mark.asyncio
async def test_claim_retry_exhaustion_is_bounded_and_later_reconciled(database, monkeypatch):
    job_id = await pending_job(database)
    attempts = 0

    async def unavailable(*_args):
        nonlocal attempts
        attempts += 1
        raise disconnected()

    monkeypatch.setattr(worker, "_claim_job_once", unavailable)
    with pytest.raises(OperationalError):
        await worker.run_analysis_job({}, str(job_id), 0)
    assert attempts == 3
    job, _ = await read_state(database, job_id)
    assert (job.status, job.retry_count, job.worker_token) == ("pending", 0, None)
    queue = Queue(JobStatus.complete)
    assert await dispatch.reconcile_pending_dispatches(queue=queue) == {"leased": 1, "recovered": 1, "failed": 0}
    job, usage = await read_state(database, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("pending", 1, 1)
    assert (usage.input_tokens, usage.asr_seconds) == (11, 3)


@pytest.mark.asyncio
async def test_claim_does_not_retry_programming_error(database, monkeypatch):
    attempts = 0

    async def invalid(*_args):
        nonlocal attempts
        attempts += 1
        raise ProgrammingError("local fixture", {}, ValueError("invalid schema fixture"))

    monkeypatch.setattr(worker, "_claim_job_once", invalid)
    with pytest.raises(ProgrammingError):
        await worker._claim_job(uuid.uuid4(), 0)
    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [JobStatus.queued, JobStatus.deferred, JobStatus.in_progress, "unknown"])
async def test_active_or_unknown_arq_delivery_is_not_replaced(database, status):
    job_id = await pending_job(database)
    queue = Queue(status)
    assert await dispatch.reconcile_pending_dispatches(queue=queue) == {"leased": 0, "recovered": 0, "failed": 0}
    assert queue.enqueued == []
    job, _ = await read_state(database, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("pending", 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [JobStatus.not_found, JobStatus.complete])
async def test_lost_delivery_is_fenced_once_without_reserving_again(database, status):
    job_id = await pending_job(database)
    now = datetime.now(timezone.utc)
    queue = Queue(status)
    assert await dispatch.reconcile_pending_dispatches(queue=queue, now=now) == {"leased": 1, "recovered": 1, "failed": 0}
    queue.current_status = JobStatus.queued
    await dispatch.reconcile_pending_dispatches(queue=queue, now=now)
    assert queue.enqueued == [(str(job_id), 1)]
    assert await worker._claim_job(job_id, 0) is None
    assert await worker._claim_job(job_id, 1) is not None
    job, usage = await read_state(database, job_id)
    assert (job.status, job.execution_version, job.retry_count) == ("running", 1, 1)
    assert (usage.input_tokens, usage.asr_seconds) == (11, 3)


@pytest.mark.asyncio
async def test_queue_outage_is_not_treated_as_missing_delivery(database):
    job_id = await pending_job(database)
    queue = Queue(ConnectionError("local Redis outage fixture"))
    now = datetime.now(timezone.utc)
    await dispatch.reconcile_pending_dispatches(queue=queue, now=now)
    await dispatch.reconcile_pending_dispatches(queue=queue, now=now)
    assert len(queue.inspected) == 1 and queue.enqueued == []
    job, _ = await read_state(database, job_id)
    assert (job.execution_version, job.retry_count) == (0, 0)
    queue.current_status = JobStatus.not_found
    await dispatch.reconcile_pending_dispatches(
        queue=queue, now=now + timedelta(seconds=dispatch.DISPATCH_RECONCILE_MIN_AGE_SECONDS + 1),
    )
    assert queue.enqueued == [(str(job_id), 1)]


@pytest.mark.asyncio
async def test_reconciliation_rotates_past_older_queued_jobs(database, monkeypatch):
    now = datetime.now(timezone.utc)
    older_id = await pending_job(database, created_at=now - timedelta(minutes=30))
    lost_id = await pending_job(database, created_at=now - timedelta(minutes=20))
    monkeypatch.setattr(dispatch, "DISPATCH_RECONCILE_BATCH_SIZE", 1)

    class MixedQueue(Queue):
        async def status(self, arq_job_id):
            self.inspected.append(arq_job_id)
            return JobStatus.queued if str(older_id) in arq_job_id else JobStatus.not_found

    queue = MixedQueue(None)
    assert await dispatch.recover_unclaimed_jobs(queue, now) == 0
    later = now + timedelta(seconds=dispatch.DISPATCH_RECONCILE_MIN_AGE_SECONDS + 1)
    assert await dispatch.recover_unclaimed_jobs(queue, later) == 1
    assert queue.inspected == [f"analysis:{older_id}:v0", f"analysis:{lost_id}:v0"]
    old, _ = await read_state(database, older_id)
    recovered, _ = await read_state(database, lost_id)
    assert (old.execution_version, old.retry_count) == (0, 0)
    assert (recovered.execution_version, recovered.retry_count) == (1, 1)


@pytest.mark.asyncio
async def test_repeated_lost_deliveries_eventually_fail_visibly(database):
    job_id = await pending_job(database)
    queue = Queue(JobStatus.complete)
    now = datetime.now(timezone.utc)
    for _ in range(dispatch.JOB_MAX_RETRIES + 2):
        await dispatch.reconcile_pending_dispatches(queue=queue, now=now)
        now += timedelta(seconds=dispatch.DISPATCH_RECONCILE_MIN_AGE_SECONDS + 1)
    job, usage = await read_state(database, job_id)
    assert job.status == "failed" and job.error_code == "WORKER_FAILED"
    assert job.completed_at is not None
    assert job.retry_count == dispatch.JOB_MAX_RETRIES
    assert len(queue.enqueued) == dispatch.JOB_MAX_RETRIES
    assert (usage.input_tokens, usage.asr_seconds) == (11, 3)


@pytest.mark.asyncio
async def test_parallel_unclaimed_recovery_changes_version_once(database):
    job_id = await pending_job(database)
    queue = Queue(JobStatus.not_found)
    now = datetime.now(timezone.utc)
    counts = await asyncio.gather(
        dispatch.recover_unclaimed_jobs(queue, now), dispatch.recover_unclaimed_jobs(queue, now),
    )
    assert sum(counts) == 1
    job, _ = await read_state(database, job_id)
    assert (job.execution_version, job.retry_count) == (1, 1)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(JobEvent).where(JobEvent.event_type == "dispatch_unclaimed")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_change", ["claim", "cancel", "version"])
async def test_unclaimed_recovery_does_not_override_concurrent_state(database, concurrent_change):
    job_id = await pending_job(database)

    class RacingQueue(Queue):
        async def status(self, _job_id):
            if concurrent_change == "claim":
                assert await worker._claim_job(job_id, 0) is not None
            else:
                async with database() as db:
                    job = await db.get(AnalysisJob, job_id)
                    if concurrent_change == "cancel":
                        job.status = "cancelled"
                    else:
                        job.execution_version += 1
                    await db.commit()
            return JobStatus.not_found

    queue = RacingQueue(JobStatus.not_found)
    assert await dispatch.recover_unclaimed_jobs(queue, datetime.now(timezone.utc)) == 0
    job, _ = await read_state(database, job_id)
    assert job.retry_count == 0
    assert job.status == {"claim": "running", "cancel": "cancelled", "version": "pending"}[concurrent_change]


@pytest.mark.asyncio
async def test_unclaimed_candidate_synthesis_reuses_frozen_decision(database):
    job_id = await pending_job(database)
    async with database() as db:
        job = await db.get(AnalysisJob, job_id)
        collection = CollectionSnapshot(
            job_id=job_id, source_execution_version=0, schema_version="collection-v1",
            content_hash="fixture-collection", workflow_version="v2", topic_spec={}, plan=[],
            raw_data=[], evidence=[], tool_results=[], search_queries_used=[], collection_usage={},
        )
        db.add(collection)
        await db.flush()
        snapshot = CandidateSnapshot(
            collection_snapshot_id=collection.id, job_id=job_id, source_execution_version=0,
            schema_version="candidate-v1", snapshot_hash="fixture-candidates", topic_summary={},
        )
        db.add(snapshot)
        await db.flush()
        batch = CandidateDecisionBatch(
            request_id=uuid.uuid4(), snapshot_id=snapshot.id, job_id=job_id,
            submitted_by=job.user_id, payload_hash="fixture-decision",
        )
        db.add(batch)
        await db.flush()
        batch_id = batch.id
        db.add(CandidateSynthesisRun(job_id=job_id, decision_batch_id=batch.id, execution_version=0))
        await db.commit()
    assert await dispatch.recover_unclaimed_jobs(Queue(JobStatus.complete), datetime.now(timezone.utc)) == 1
    async with database() as db:
        runs = list((await db.scalars(select(CandidateSynthesisRun).order_by(CandidateSynthesisRun.execution_version))).all())
        assert [run.execution_version for run in runs] == [0, 1]
        assert all(run.decision_batch_id == batch_id for run in runs)


@pytest.mark.asyncio
@pytest.mark.parametrize("timed_out", [False, True])
async def test_second_cancel_waits_for_cleanup_before_usage_settlement(database, monkeypatch, timed_out):
    job_id = await pending_job(database)
    entered = asyncio.Event()
    cleanup_entered = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleaned = asyncio.Event()

    async def work(*_args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_entered.set()
            await allow_cleanup.wait()
            asr_usage_tracker.record({"asr_usage_receipt": {"id": "cleanup-fixture", "seconds": 7}})
            cleaned.set()

    original_finish = worker._finish_attempt

    async def finish(*args, **kwargs):
        assert cleaned.is_set()
        return await original_finish(*args, **kwargs)

    monkeypatch.setattr(worker, "_execute_job", work)
    monkeypatch.setattr(worker, "_finish_attempt", finish)
    monkeypatch.setattr(worker, "JOB_TIMEOUT_SECONDS", 0.05 if timed_out else 10)
    task = asyncio.create_task(worker.run_analysis_job({}, str(job_id), 0))
    await asyncio.wait_for(entered.wait(), 2)
    if not timed_out:
        task.cancel()
    await asyncio.wait_for(cleanup_entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not cleaned.is_set() and not task.done()
    allow_cleanup.set()
    with pytest.raises((asyncio.CancelledError, Retry)):
        await task
    assert cleaned.is_set()
    job, usage = await read_state(database, job_id)
    assert job.status == "pending" and job.worker_token is None
    assert usage.asr_seconds == 10
