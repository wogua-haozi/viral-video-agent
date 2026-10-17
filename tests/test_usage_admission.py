import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api import job_routes
from src.db.models import AnalysisJob, UsageRecord
from src.db.session import Base, get_db
from src.main import app
from src.queue import get_job_queue
from src.repositories import JobRepository, UsageRepository


class RecordingQueue:
    def __init__(self):
        self.calls = []

    async def enqueue(self, job_id, execution_version=0):
        self.calls.append((job_id, execution_version))
        return f"analysis:{job_id}:v{execution_version}"


@pytest_asyncio.fixture
async def admission_client(tmp_path):
    # Independent connections are intentional: a StaticPool can hide races in
    # the last available quota slot and cannot model concurrent transactions.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admission.db'}", connect_args={"timeout": 30})

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_db():
        async with factory() as db:
            yield db

    queue = RecordingQueue()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            registered = await client.post("/auth/register", json={"email": "pilot@example.com", "password": "strong-pass-123"})
            assert registered.status_code == 201
            yield client, factory, queue
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def payload(key="pilot-submission-key", query="分析B站摄影视频的选题角度"):
    return {"query": query, "platforms": ["bilibili"], "analysis_mode": "standard", "idempotency_key": key}


@pytest.mark.asyncio
async def test_pending_submission_reserves_slot_and_idempotent_replay_survives_limit(admission_client, monkeypatch):
    client, factory, queue = admission_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 1)
    first = await client.post("/jobs", json=payload())
    assert first.status_code == 202
    assert first.json()["status"] == "pending"
    assert (await client.get("/usage")).json()["jobs_used"] == 1
    repeated = await client.post("/jobs", json=payload())
    assert repeated.status_code == 202 and repeated.json()["id"] == first.json()["id"]
    blocked = await client.post("/jobs", json=payload("another-submission"))
    assert blocked.status_code == 429
    conflict = await client.post("/jobs", json=payload(query="分析不同的内容领域"))
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "JOB_IDEMPOTENCY_CONFLICT"
    assert len(queue.calls) == 1
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(UsageRecord)) == 1


@pytest.mark.asyncio
async def test_parallel_submissions_cannot_oversubscribe_last_slot(admission_client, monkeypatch):
    client, factory, queue = admission_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 1)
    responses = await asyncio.gather(*[
        client.post("/jobs", json=payload(f"parallel-request-{index}")) for index in range(6)
    ])
    assert sorted(response.status_code for response in responses) == [202, 429, 429, 429, 429, 429]
    assert len(queue.calls) == 1
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnalysisJob)) == 1
        assert await db.scalar(select(func.count()).select_from(UsageRecord)) == 1


@pytest.mark.asyncio
async def test_parallel_replays_create_one_job_and_one_queue_message(admission_client, monkeypatch):
    client, factory, queue = admission_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 1)
    responses = await asyncio.gather(*[client.post("/jobs", json=payload()) for _ in range(4)])
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(queue.calls) == 1
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(UsageRecord)) == 1


@pytest.mark.asyncio
async def test_delete_preserves_consumption_and_does_not_refund_slot(admission_client, monkeypatch):
    client, factory, _ = admission_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 1)
    created = await client.post("/jobs", json=payload())
    job_id = uuid.UUID(created.json()["id"])
    async with factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        await UsageRepository(db).settle_attempt(job, "failed-attempt", {"input_tokens": 100, "output_tokens": 20, "total_cost": 0.03}, 8)
        await db.commit()
    assert (await client.post(f"/jobs/{job_id}/cancel")).status_code == 200
    assert (await client.delete(f"/jobs/{job_id}")).status_code == 204
    async with factory() as db:
        usage = await db.scalar(select(UsageRecord))
        assert usage.job_id is None
        assert usage.input_tokens == 100 and usage.estimated_cost == pytest.approx(0.03)
    summary = (await client.get("/usage")).json()
    assert summary["jobs_used"] == 1 and summary["asr_seconds"] == 8
    assert (await client.post("/jobs", json=payload("after-delete-key"))).status_code == 429


@pytest.mark.asyncio
async def test_retry_preserves_ledger_and_obeys_retry_budget(admission_client, monkeypatch):
    client, factory, _ = admission_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 1)
    created = await client.post("/jobs", json=payload())
    job_id = uuid.UUID(created.json()["id"])
    for attempt in range(job_routes.JOB_MAX_RETRIES):
        async with factory() as db:
            job = await JobRepository(db).get_for_update(job_id)
            job.status = "failed"
            await UsageRepository(db).settle_attempt(job, f"attempt-{attempt}", {"input_tokens": 10, "total_cost": 0.01})
            await db.commit()
        retried = await client.post(f"/jobs/{job_id}/retry")
        assert retried.status_code == 202
        assert retried.json()["execution_version"] == attempt + 1
    async with factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        job.status = "failed"
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(UsageRecord)) == 1
    exhausted = await client.post(f"/jobs/{job_id}/retry")
    assert exhausted.status_code == 409 and exhausted.json()["error_code"] == "JOB_RETRY_LIMIT_REACHED"
    assert (await client.get(f"/jobs/{job_id}")).json()["can_retry"] is False
    assert (await client.get("/usage")).json()["input_tokens"] == 10 * job_routes.JOB_MAX_RETRIES


@pytest.mark.asyncio
async def test_revision_reserves_its_own_slot_once(admission_client, monkeypatch):
    client, _, queue = admission_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 2)
    created = await client.post("/jobs", json=payload())
    job_id = created.json()["id"]
    await client.post(f"/jobs/{job_id}/cancel")
    revised_payload = {"query": "只看相机测评账号的标题结构", "idempotency_key": "pilot-revision-key"}
    first = await client.post(f"/jobs/{job_id}/revisions", json=revised_payload)
    replay = await client.post(f"/jobs/{job_id}/revisions", json=revised_payload)
    assert first.status_code == replay.status_code == 202
    assert first.json()["id"] == replay.json()["id"]
    assert (await client.get("/usage")).json()["jobs_used"] == 2
    denied = await client.post(f"/jobs/{job_id}/revisions", json={**revised_payload, "idempotency_key": "third-revision-key"})
    assert denied.status_code == 429 and len(queue.calls) == 2


@pytest.mark.asyncio
async def test_usage_checkpoints_count_each_attempt_and_interaction_once(admission_client):
    client, factory, _ = admission_client
    created = await client.post("/jobs", json=payload())
    job_id = uuid.UUID(created.json()["id"])
    async with factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        job.interaction_usage = {"input_tokens": 10, "output_tokens": 5, "estimated_cost": 0.01}
        repo = UsageRepository(db)
        for _ in range(2):
            await repo.settle_attempt(job, "one", {"input_tokens": 100, "output_tokens": 50, "total_cost": 0.1}, 20)
        await repo.settle_attempt(job, "one", {"input_tokens": 80, "output_tokens": 30, "total_cost": 0.08}, 10)
        await repo.settle_attempt(job, "two", {"input_tokens": 40, "output_tokens": 10, "total_cost": 0.05}, 10)
        job.interaction_usage = {"input_tokens": 13, "output_tokens": 7, "estimated_cost": 0.013}
        usage = await repo.settle_attempt(job, "two", {"input_tokens": 40, "output_tokens": 10, "total_cost": 0.05}, 10)
        await db.commit()
        assert (usage.input_tokens, usage.output_tokens, usage.asr_seconds) == (153, 67, 30)
        assert usage.estimated_cost == pytest.approx(0.163)


@pytest.mark.asyncio
async def test_cancelled_task_cannot_be_deleted_or_retried_while_worker_stops(admission_client):
    client, factory, _ = admission_client
    created = await client.post("/jobs", json=payload())
    job_id = uuid.UUID(created.json()["id"])
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = "running"
        job.worker_token = str(uuid.uuid4())
        job.worker_lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=90)
        await db.commit()
    cancelled = await client.post(f"/jobs/{job_id}/cancel")
    assert cancelled.json()["status"] == "cancelled" and cancelled.json()["can_retry"] is False
    assert cancelled.json()["is_stopping"] is True
    assert (await client.post(f"/jobs/{job_id}/retry")).json()["error_code"] == "JOB_STOPPING"
    assert (await client.delete(f"/jobs/{job_id}")).json()["error_code"] == "JOB_STOPPING"
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        job.worker_token = None
        job.worker_lease_expires_at = None
        await db.commit()
    stopped = (await client.get(f"/jobs/{job_id}")).json()
    assert stopped["is_stopping"] is False and stopped["can_retry"] is True


@pytest.mark.asyncio
async def test_fast_worker_start_does_not_expire_created_job_response(admission_client):
    client, factory, _ = admission_client

    class FastQueue:
        async def enqueue(self, job_id, execution_version=0):
            async with factory() as db:
                job = await db.get(AnalysisJob, uuid.UUID(job_id))
                job.status = "running"
                await db.commit()
            return f"fast:{job_id}"

    app.dependency_overrides[get_job_queue] = lambda: FastQueue()
    created = await client.post("/jobs", json=payload())
    assert created.status_code == 202
    assert created.json()["status"] == "running"
