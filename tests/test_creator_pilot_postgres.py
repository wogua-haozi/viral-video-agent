"""Opt-in PostgreSQL migration, quota and recovery regressions.

Run against an explicitly selected PostgreSQL test database:

    PILOT_TEST_POSTGRES_URL='postgresql+asyncpg://user@host/test_db' \
        python -m pytest -q tests/test_creator_pilot_postgres.py

The role needs CREATE SCHEMA permission. Every test creates a random
``pilot_test_<uuid>`` schema, connects with that schema as its entire search_path,
and drops only that schema in teardown. It never migrates the database's public
schema or uses the application's configured DATABASE_URL. No model, external
data provider or real queue is invoked. Without the explicit URL these tests
are skipped; SQLite is not a substitute for these PostgreSQL lock/FK checks.
"""

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src import dispatch
from src.api import job_routes
from src.db.models import AnalysisJob, JobEvent, UsageRecord, User
from src.db.session import get_db
from src.main import app
from src.queue import get_job_queue
from src.repositories import JobRepository, UsageRepository


POSTGRES_URL = os.getenv("PILOT_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PILOT_TEST_POSTGRES_URL is not explicitly configured")
ROOT = Path(__file__).resolve().parents[1]
PRE_PILOT = "20260725_0004"
PILOT = "20261017_0005"


@dataclass
class PostgresSandbox:
    engine: AsyncEngine
    factory: async_sessionmaker
    schema: str


async def migrate(database: PostgresSandbox, revision: str, *, downgrade: bool = False) -> None:
    def run(connection):
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, revision)

    async with database.engine.begin() as connection:
        assert await connection.scalar(sa.text("SELECT current_schema()")) == database.schema
        await connection.run_sync(run)


@pytest_asyncio.fixture
async def postgres_db():
    if not POSTGRES_URL:
        pytest.skip("PILOT_TEST_POSTGRES_URL is not explicitly configured")
    url = make_url(POSTGRES_URL)
    if url.get_backend_name() != "postgresql":
        pytest.fail("PILOT_TEST_POSTGRES_URL must select a PostgreSQL test database")
    url = url.set(drivername="postgresql+asyncpg")
    schema = "pilot_test_" + uuid.uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = None
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            created = True
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            connect_args={"server_settings": {
                "search_path": schema,
                "application_name": "viral-video-creator-pilot-tests",
                "lock_timeout": "10000",
                "statement_timeout": "30000",
            }},
        )
        yield PostgresSandbox(engine, async_sessionmaker(engine, expire_on_commit=False), schema)
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            # The identifier is generated above, never read from a request/URL.
            assert schema.startswith("pilot_test_") and len(schema) == 43
            async with admin.begin() as connection:
                await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def seed_pre_pilot(database: PostgresSandbox) -> dict:
    """Insert real 0004 rows, without using the newer ORM model to fake history."""
    old_created = datetime(2026, 6, 30, 23, 55, tzinfo=timezone.utc)
    ids = {key: uuid.uuid4() for key in ("user", "measured", "pending", "failed", "usage")}

    def insert(connection):
        metadata = sa.MetaData()
        users = sa.Table("users", metadata, autoload_with=connection)
        jobs = sa.Table("analysis_jobs", metadata, autoload_with=connection)
        usage = sa.Table("usage_records", metadata, autoload_with=connection)
        assert "accounted_attempts" not in usage.c
        assert "worker_token" not in jobs.c
        connection.execute(users.insert().values(
            id=ids["user"], email="legacy-pilot@example.invalid", hashed_password="unused-test-hash",
            created_at=old_created, is_active=True,
        ))
        for key, status, interaction in (
            ("measured", "completed", {"input_tokens": 20, "output_tokens": 10, "estimated_cost": 0.02}),
            ("pending", "pending", {"input_tokens": 15, "output_tokens": 7, "estimated_cost": 0.015}),
            ("failed", "failed", {}),
        ):
            connection.execute(jobs.insert().values(
                id=ids[key], user_id=ids["user"], query="分析B站相机内容", platforms=["bilibili"],
                analysis_mode="standard", status=status, progress=0, retry_count=0,
                idempotency_key="legacy-" + key, created_at=old_created, interaction_usage=interaction,
            ))
        connection.execute(usage.insert().values(
            id=ids["usage"], user_id=ids["user"], job_id=ids["measured"],
            input_tokens=120, output_tokens=60, estimated_cost=0.13, asr_seconds=12,
            # Old accounting settled in the following month. Admission now
            # belongs to the original submission month without changing totals.
            created_at=old_created + timedelta(days=2),
        ))

    async with database.engine.begin() as connection:
        await connection.run_sync(insert)
    return {**ids, "created_at": old_created}


@pytest.mark.asyncio
async def test_postgres_upgrade_preserves_old_usage_backfills_missing_slots_and_downgrades(postgres_db):
    await migrate(postgres_db, PRE_PILOT)
    legacy = await seed_pre_pilot(postgres_db)
    await migrate(postgres_db, PILOT)

    async with postgres_db.factory() as db:
        rows = list((await db.scalars(sa.select(UsageRecord))).all())
        assert len(rows) == 3
        by_job = {row.job_id: row for row in rows}
        measured = by_job[legacy["measured"]]
        assert (measured.input_tokens, measured.output_tokens, measured.asr_seconds) == (120, 60, 12)
        assert measured.estimated_cost == pytest.approx(0.13)
        assert measured.created_at == legacy["created_at"]
        assert measured.accounted_attempts["interaction"] == {
            "input_tokens": 20, "output_tokens": 10, "estimated_cost": 0.02, "asr_seconds": 0,
        }
        pending = by_job[legacy["pending"]]
        assert (pending.input_tokens, pending.output_tokens, pending.asr_seconds) == (15, 7, 0)
        assert pending.estimated_cost == pytest.approx(0.015)
        assert pending.created_at == legacy["created_at"]
        assert by_job[legacy["failed"]].input_tokens == 0

    async with postgres_db.factory() as db:
        job = await JobRepository(db).get_for_update(legacy["measured"])
        repo = UsageRepository(db)
        for _ in range(2):
            measured = await repo.settle_attempt(
                job, "after-upgrade", {"input_tokens": 9, "output_tokens": 3, "total_cost": 0.001}, 2,
            )
        assert (measured.input_tokens, measured.output_tokens, measured.asr_seconds) == (129, 63, 14)
        assert measured.estimated_cost == pytest.approx(0.131)
        pending_job = await JobRepository(db).get_for_update(legacy["pending"])
        pending = await repo.settle_attempt(pending_job, "after-upgrade", {})
        assert (pending.input_tokens, pending.output_tokens) == (15, 7)
        assert pending.estimated_cost == pytest.approx(0.015)
        await db.commit()

    # A repeated upgrade must neither reserve again nor erase checkpoints.
    await migrate(postgres_db, PILOT)
    async with postgres_db.factory() as db:
        assert await db.scalar(sa.select(sa.func.count()).select_from(UsageRecord)) == 3
        usage = await db.get(UsageRecord, legacy["usage"])
        assert usage.input_tokens == 129 and "attempt:after-upgrade" in usage.accounted_attempts

    await migrate(postgres_db, PRE_PILOT, downgrade=True)
    async with postgres_db.engine.connect() as connection:
        def inspect_schema(sync):
            inspector = sa.inspect(sync)
            return (
                {column["name"]: column for column in inspector.get_columns("usage_records")},
                {column["name"] for column in inspector.get_columns("analysis_jobs")},
                inspector.get_foreign_keys("usage_records"),
            )
        columns, job_columns, foreign_keys = await connection.run_sync(inspect_schema)
        assert "accounted_attempts" not in columns
        assert columns["job_id"]["nullable"] is False
        assert "worker_token" not in job_columns and "worker_lease_expires_at" not in job_columns
        job_fk = next(item for item in foreign_keys if item["constrained_columns"] == ["job_id"])
        assert job_fk["options"]["ondelete"] == "CASCADE"
        assert await connection.scalar(sa.text("SELECT input_tokens FROM usage_records WHERE id = :id"), {"id": legacy["usage"]}) == 129
        assert await connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == PRE_PILOT

    await migrate(postgres_db, "base", downgrade=True)
    async with postgres_db.engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT to_regclass('analysis_jobs')")) is None


class RecordingQueue:
    def __init__(self):
        self.calls = []

    async def enqueue(self, job_id, execution_version=0):
        self.calls.append((job_id, execution_version))
        return f"analysis:{job_id}:v{execution_version}"


@pytest_asyncio.fixture
async def postgres_client(postgres_db):
    await migrate(postgres_db, PILOT)

    async def override_db():
        async with postgres_db.factory() as session:
            yield session

    previous_overrides = app.dependency_overrides.copy()
    queue = RecordingQueue()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/auth/register", json={
                "email": "postgres-pilot@example.com", "password": "strong-test-pass-123",
            })
            assert response.status_code == 201, response.text
            yield client, queue
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def submission(key):
    return {
        "query": "分析B站摄影视频的选题角度", "platforms": ["bilibili"],
        "analysis_mode": "standard", "idempotency_key": key,
    }


@pytest.mark.asyncio
async def test_postgres_parallel_admission_cannot_oversubscribe_last_slot(postgres_db, postgres_client, monkeypatch):
    client, queue = postgres_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 2)
    assert (await client.post("/jobs", json=submission("already-reserved"))).status_code == 202

    responses = await asyncio.wait_for(asyncio.gather(*[
        client.post("/jobs", json=submission(f"last-slot-{index}")) for index in range(6)
    ]), timeout=20)

    assert sorted(response.status_code for response in responses) == [202, 429, 429, 429, 429, 429]
    assert len(queue.calls) == 2
    async with postgres_db.factory() as db:
        assert await db.scalar(sa.select(sa.func.count()).select_from(AnalysisJob)) == 2
        assert await db.scalar(sa.select(sa.func.count()).select_from(UsageRecord)) == 2
    assert (await client.get("/usage")).json()["jobs_used"] == 2


@pytest.mark.asyncio
async def test_postgres_parallel_idempotent_replay_reserves_and_enqueues_once(postgres_db, postgres_client, monkeypatch):
    client, queue = postgres_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 1)
    responses = await asyncio.wait_for(asyncio.gather(*[
        client.post("/jobs", json=submission("same-submission")) for _ in range(6)
    ]), timeout=20)

    assert [response.status_code for response in responses] == [202] * 6
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(queue.calls) == 1
    async with postgres_db.factory() as db:
        assert await db.scalar(sa.select(sa.func.count()).select_from(AnalysisJob)) == 1
        assert await db.scalar(sa.select(sa.func.count()).select_from(UsageRecord)) == 1


@pytest.mark.asyncio
async def test_postgres_creation_and_revision_share_the_last_quota_slot(postgres_db, postgres_client, monkeypatch):
    client, queue = postgres_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 2)
    original = await client.post("/jobs", json=submission("revision-source"))
    assert original.status_code == 202
    source_id = original.json()["id"]
    assert (await client.post(f"/jobs/{source_id}/cancel")).status_code == 200

    responses = await asyncio.wait_for(asyncio.gather(
        client.post("/jobs", json=submission("new-job-competes")),
        client.post(f"/jobs/{source_id}/revisions", json={
            "query": "只分析相机评测账号的选题", "idempotency_key": "revision-competes",
        }),
    ), timeout=20)

    assert sorted(response.status_code for response in responses) == [202, 429]
    assert len(queue.calls) == 2
    async with postgres_db.factory() as db:
        assert await db.scalar(sa.select(sa.func.count()).select_from(AnalysisJob)) == 2
        assert await db.scalar(sa.select(sa.func.count()).select_from(UsageRecord)) == 2


@pytest.mark.asyncio
async def test_postgres_delete_retains_ledger_and_downgrade_refuses_to_discard_it(postgres_db, postgres_client, monkeypatch):
    client, _ = postgres_client
    monkeypatch.setattr(job_routes, "USER_MONTHLY_JOB_LIMIT", 1)
    created = await client.post("/jobs", json=submission("delete-keeps-usage"))
    assert created.status_code == 202
    job_id = uuid.UUID(created.json()["id"])
    async with postgres_db.factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        usage = await UsageRepository(db).settle_attempt(
            job, "measured-before-delete", {"input_tokens": 100, "output_tokens": 20, "total_cost": 0.03}, 8,
        )
        usage_id, user_id = usage.id, usage.user_id
        await db.commit()

    assert (await client.post(f"/jobs/{job_id}/cancel")).status_code == 200
    assert (await client.delete(f"/jobs/{job_id}")).status_code == 204
    async with postgres_db.factory() as db:
        assert await db.get(AnalysisJob, job_id) is None
        usage = await db.get(UsageRecord, usage_id)
        assert usage.job_id is None and usage.user_id == user_id
        assert (usage.input_tokens, usage.output_tokens, usage.asr_seconds) == (100, 20, 8)
        assert usage.estimated_cost == pytest.approx(0.03)
        assert "attempt:measured-before-delete" in usage.accounted_attempts
    assert (await client.get("/usage")).json()["jobs_used"] == 1
    assert (await client.post("/jobs", json=submission("after-delete"))).status_code == 429

    with pytest.raises(RuntimeError, match="retained usage for deleted jobs"):
        await migrate(postgres_db, PRE_PILOT, downgrade=True)
    async with postgres_db.factory() as db:
        assert await db.scalar(sa.text("SELECT version_num FROM alembic_version")) == PILOT
        usage = await db.get(UsageRecord, usage_id)
        assert usage.job_id is None and usage.input_tokens == 100
        assert usage.estimated_cost == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_postgres_parallel_recovery_fences_once_and_preserves_quota(postgres_db, monkeypatch):
    await migrate(postgres_db, PILOT)
    monkeypatch.setattr(dispatch, "async_session_factory", postgres_db.factory)
    now = datetime.now(timezone.utc)
    async with postgres_db.factory() as db:
        user = User(email="recovery@example.invalid", hashed_password="unused-test-hash")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id, query="分析B站相机视频", platforms=["bilibili"],
            analysis_mode="standard", idempotency_key="stale-worker",
            status="running", execution_version=3, retry_count=0,
            started_at=now - timedelta(minutes=20), worker_token=str(uuid.uuid4()),
            worker_lease_expires_at=now - timedelta(seconds=5), arq_job_id="old-worker",
        )
        db.add(job)
        await db.flush()
        await UsageRepository(db).reserve(job)
        await UsageRepository(db).settle_attempt(job, "previous-attempt", {"input_tokens": 35, "total_cost": 0.02})
        job_id = job.id
        await db.commit()

    recovered = await asyncio.wait_for(asyncio.gather(*[
        dispatch.recover_expired_jobs(now) for _ in range(4)
    ]), timeout=20)
    assert sum(recovered) == 1
    async with postgres_db.factory() as db:
        job = await db.get(AnalysisJob, job_id)
        assert (job.status, job.execution_version, job.retry_count) == ("pending", 4, 1)
        assert job.worker_token is None and job.worker_lease_expires_at is None
        assert await db.scalar(sa.select(sa.func.count()).select_from(UsageRecord)) == 1
        usage = await db.scalar(sa.select(UsageRecord).where(UsageRecord.job_id == job_id))
        assert usage.input_tokens == 35 and usage.estimated_cost == pytest.approx(0.02)
        assert await db.scalar(sa.select(sa.func.count()).select_from(JobEvent).where(JobEvent.event_type == "worker_recovered")) == 1
