import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import dispatch
from src.db.models import (
    AnalysisJob, CandidateDecisionBatch, CandidateSnapshot, CandidateSynthesisRun,
    CollectionSnapshot, JobEvent, UsageRecord, User,
)
from src.db.session import Base


@pytest_asyncio.fixture
async def recovery_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}", connect_args={"timeout": 30})

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(dispatch, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def running_job(factory, **overrides):
    now = datetime.now(timezone.utc)
    async with factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="unused")
        db.add(user)
        await db.flush()
        values = dict(
            user_id=user.id, query="分析B站摄影视频", platforms=["bilibili"],
            analysis_mode="standard", idempotency_key=str(uuid.uuid4()),
            status="running", execution_version=3, retry_count=0,
            started_at=now - timedelta(minutes=20), worker_token=str(uuid.uuid4()),
            worker_lease_expires_at=now - timedelta(seconds=5), arq_job_id="old-queue-id",
        )
        values.update(overrides)
        job = AnalysisJob(**values)
        db.add(job)
        await db.flush()
        db.add(UsageRecord(job_id=job.id, user_id=user.id, input_tokens=35, estimated_cost=0.02))
        await db.commit()
        return job.id


class RecordingQueue:
    def __init__(self):
        self.calls = []

    async def enqueue(self, job_id, version):
        self.calls.append((job_id, version))
        return f"analysis:{job_id}:v{version}"


@pytest.mark.asyncio
async def test_expired_worker_recovered_once_with_new_version_and_same_quota(recovery_db):
    job_id = await running_job(recovery_db)
    now = datetime.now(timezone.utc)
    queue = RecordingQueue()
    first = await dispatch.reconcile_pending_dispatches(queue=queue, now=now)
    second = await dispatch.reconcile_pending_dispatches(queue=queue, now=now)
    assert first == {"leased": 1, "recovered": 1, "failed": 0}
    assert second == {"leased": 0, "recovered": 0, "failed": 0}
    assert queue.calls == [(str(job_id), 4)]
    async with recovery_db() as db:
        job = await db.get(AnalysisJob, job_id)
        assert (job.status, job.retry_count, job.execution_version) == ("pending", 1, 4)
        assert job.worker_token is None and job.worker_lease_expires_at is None
        usage = await db.scalar(select(UsageRecord).where(UsageRecord.job_id == job_id))
        assert usage.input_tokens == 35 and usage.estimated_cost == pytest.approx(0.02)
        assert await db.scalar(select(func.count()).select_from(UsageRecord)) == 1


@pytest.mark.asyncio
async def test_parallel_recovery_fences_the_same_expired_attempt_once(recovery_db):
    job_id = await running_job(recovery_db)
    now = datetime.now(timezone.utc)
    counts = await asyncio.gather(dispatch.recover_expired_jobs(now), dispatch.recover_expired_jobs(now))
    assert sum(counts) == 1
    async with recovery_db() as db:
        job = await db.get(AnalysisJob, job_id)
        assert (job.execution_version, job.retry_count) == (4, 1)
        assert await db.scalar(select(func.count()).select_from(JobEvent).where(JobEvent.event_type == "worker_recovered")) == 1


@pytest.mark.asyncio
async def test_live_and_recent_legacy_workers_are_not_recovered(recovery_db):
    now = datetime.now(timezone.utc)
    live_id = await running_job(recovery_db, worker_lease_expires_at=now + timedelta(seconds=60))
    recent_id = await running_job(recovery_db, worker_token=None, worker_lease_expires_at=None, started_at=now)
    cancelled_id = await running_job(recovery_db, status="cancelled")
    assert await dispatch.recover_expired_jobs(now) == 0
    async with recovery_db() as db:
        assert (await db.get(AnalysisJob, live_id)).status == "running"
        assert (await db.get(AnalysisJob, recent_id)).status == "running"
        assert (await db.get(AnalysisJob, cancelled_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_exhausted_worker_fails_visibly_and_legacy_stale_worker_recovers(recovery_db):
    exhausted_id = await running_job(recovery_db, retry_count=dispatch.JOB_MAX_RETRIES)
    legacy_id = await running_job(recovery_db, worker_token=None, worker_lease_expires_at=None)
    queue = RecordingQueue()
    await dispatch.reconcile_pending_dispatches(queue=queue, now=datetime.now(timezone.utc))
    assert queue.calls == [(str(legacy_id), 4)]
    async with recovery_db() as db:
        exhausted = await db.get(AnalysisJob, exhausted_id)
        assert exhausted.status == "failed" and exhausted.completed_at is not None
        assert exhausted.error_code == "WORKER_FAILED" and exhausted.worker_token is None


@pytest.mark.asyncio
async def test_recovery_reuses_frozen_candidate_decisions(recovery_db):
    job_id = await running_job(recovery_db, execution_version=1)
    async with recovery_db() as db:
        job = await db.get(AnalysisJob, job_id)
        collection = CollectionSnapshot(
            job_id=job_id, source_execution_version=0, schema_version="collection-v1",
            content_hash="frozen-collection-hash", workflow_version="v2", topic_spec={}, plan=[],
            raw_data=[], evidence=[], tool_results=[], search_queries_used=[], collection_usage={},
        )
        db.add(collection)
        await db.flush()
        snapshot = CandidateSnapshot(
            collection_snapshot_id=collection.id, job_id=job_id, source_execution_version=0,
            schema_version="candidate-v1", snapshot_hash="frozen-candidate-hash", topic_summary={},
        )
        db.add(snapshot)
        await db.flush()
        batch = CandidateDecisionBatch(
            request_id=uuid.uuid4(), snapshot_id=snapshot.id, job_id=job_id, submitted_by=job.user_id, payload_hash="frozen-decision-hash",
        )
        db.add(batch)
        await db.flush()
        batch_id = batch.id
        db.add(CandidateSynthesisRun(job_id=job_id, decision_batch_id=batch.id, execution_version=1))
        await db.commit()
    assert await dispatch.recover_expired_jobs(datetime.now(timezone.utc)) == 1
    async with recovery_db() as db:
        runs = list((await db.scalars(select(CandidateSynthesisRun).order_by(CandidateSynthesisRun.execution_version))).all())
        assert [run.execution_version for run in runs] == [1, 2]
        assert all(run.decision_batch_id == batch_id for run in runs)
        assert (await db.scalar(select(CandidateSnapshot))).snapshot_hash == "frozen-candidate-hash"
        assert (await db.scalar(select(CollectionSnapshot))).content_hash == "frozen-collection-hash"
