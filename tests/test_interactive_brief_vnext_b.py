import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import AnalysisJob, JobClarification, JobEvent, Report, User
from src.db.session import Base, get_db
from src.dispatch import reconcile_pending_dispatches
from src.main import app
from src.queue import get_job_queue


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    database_path = (tmp_path / "interactive-vnext-b.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


class CapturingQueue:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory
        self.calls: list[tuple[str, int]] = []
        self.ids: list[str] = []
        self.fail = False
        self.on_enqueue = None

    async def enqueue(self, job_id: str, execution_version: int = 0) -> str:
        self.calls.append((job_id, execution_version))
        arq_job_id = f"analysis:{job_id}:v{execution_version}"
        self.ids.append(arq_job_id)
        if self.on_enqueue:
            await self.on_enqueue(uuid.UUID(job_id), execution_version)
        if self.fail:
            raise RuntimeError("queue unavailable")
        return arq_job_id


@pytest_asyncio.fixture
async def api_client(session_factory):
    queue = CapturingQueue(session_factory)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory, queue
    app.dependency_overrides.clear()


async def register(client: AsyncClient, email: str) -> uuid.UUID:
    response = await client.post("/auth/register", json={"email": email, "password": "strong-pass-123"})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def create_job(factory, user_id: uuid.UUID, *, status: str, query: str = "分析相机账号", **values) -> uuid.UUID:
    async with factory() as db:
        job = AnalysisJob(
            user_id=user_id,
            query=query,
            platforms=["bilibili"],
            analysis_mode="standard",
            status=status,
            idempotency_key=str(uuid.uuid4()),
            **values,
        )
        db.add(job)
        await db.commit()
        return job.id


def options():
    return [
        {"id": "strict", "label": "专业账号", "description": "只纳入专业账号"},
        {"id": "generalist", "label": "综合账号", "description": "允许综合账号"},
    ]


@pytest.mark.asyncio
async def test_clarification_history_is_owned_and_separates_current(api_client):
    client, factory, _ = api_client
    owner_id = await register(client, "vnext-b-history@example.com")
    job_id = await create_job(factory, owner_id, status="waiting_user", clarification_round=2)
    async with factory() as db:
        db.add(JobClarification(
            job_id=job_id,
            round=2,
            question="是否纳入综合账号？",
            options=options(),
            allow_custom=True,
            status="pending",
        ))
        db.add(JobClarification(
            job_id=job_id,
            round=1,
            question="只看专业账号吗？",
            options=options(),
            allow_custom=True,
            status="answered",
            selected_option_id="strict",
            custom_answer="排除偶尔发布者",
            answered_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    response = await client.get(f"/jobs/{job_id}/clarification")
    assert response.status_code == 200
    payload = response.json()
    assert payload["current"]["round"] == 2
    assert [item["round"] for item in payload["history"]] == [1]
    assert payload["history"][0]["selected_option_id"] == "strict"
    assert payload["history"][0]["custom_answer"] == "排除偶尔发布者"

    await client.post("/auth/logout")
    await register(client, "vnext-b-history-other@example.com")
    assert (await client.get(f"/jobs/{job_id}/clarification")).status_code == 404


@pytest.mark.asyncio
async def test_revision_creates_audited_job_without_overwriting_answers(api_client):
    client, factory, queue = api_client
    owner_id = await register(client, "vnext-b-revision@example.com")
    source_id = await create_job(factory, owner_id, status="waiting_user", clarification_round=2)
    async with factory() as db:
        answered = JobClarification(
            job_id=source_id,
            round=1,
            question="只看专业账号吗？",
            options=options(),
            allow_custom=True,
            status="answered",
            selected_option_id="strict",
            custom_answer="旧回答",
            answered_at=datetime.now(timezone.utc),
        )
        pending = JobClarification(job_id=source_id, round=2, question="时间范围？", options=options(), allow_custom=True, status="pending")
        db.add_all([answered, pending])
        await db.commit()
        answered_id, pending_id = answered.id, pending.id

    request = {"query": "只分析近一年持续发布相机测评的专业账号", "idempotency_key": "revision-stable-key"}
    first = await client.post(f"/jobs/{source_id}/revisions", json=request)
    duplicate = await client.post(f"/jobs/{source_id}/revisions", json=request)
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["id"] == duplicate.json()["id"]
    revised_id = uuid.UUID(first.json()["id"])
    assert first.json()["revision_of_job_id"] == str(source_id)
    assert first.json()["execution_version"] == 0
    assert first.json()["retry_count"] == 0
    assert queue.calls == [(str(revised_id), 0)]

    source_response = await client.get(f"/jobs/{source_id}")
    assert source_response.status_code == 200
    assert source_response.json()["can_retry"] is False
    assert source_response.json()["can_revise"] is True
    direct_retry = await client.post(f"/jobs/{source_id}/retry")
    assert direct_retry.status_code == 409
    assert direct_retry.json()["error_code"] == "JOB_NOT_RETRYABLE"

    async with factory() as db:
        source = await db.get(AnalysisJob, source_id)
        revised = await db.get(AnalysisJob, revised_id)
        old_answer = await db.get(JobClarification, answered_id)
        old_pending = await db.get(JobClarification, pending_id)
        source_events = list((await db.scalars(select(JobEvent).where(JobEvent.job_id == source_id))).all())
        revised_events = list((await db.scalars(select(JobEvent).where(JobEvent.job_id == revised_id))).all())
        assert source.status == "cancelled"
        assert revised.status == "pending"
        assert revised.query == request["query"]
        assert revised.revision_of_job_id == source_id
        assert old_answer.status == "answered"
        assert old_answer.custom_answer == "旧回答"
        assert old_pending.status == "pending"
        assert any(event.event_type == "scope_revision_created" for event in source_events)
        assert any(event.event_type == "scope_revision_started" for event in revised_events)

    conflict = await client.post(f"/jobs/{source_id}/revisions", json={**request, "query": "另一种范围"})
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "JOB_REVISION_CONFLICT"
    blocked_delete = await client.delete(f"/jobs/{source_id}")
    assert blocked_delete.status_code == 409
    assert blocked_delete.json()["error_code"] == "JOB_HAS_REVISIONS"


@pytest.mark.asyncio
async def test_cancelled_waiting_job_with_pending_clarification_cannot_retry(api_client):
    client, factory, queue = api_client
    owner_id = await register(client, "vnext-b-cancelled-clarification@example.com")
    job_id = await create_job(factory, owner_id, status="waiting_user", clarification_round=1)
    async with factory() as db:
        db.add(JobClarification(
            job_id=job_id,
            round=1,
            question="是否只看专业账号？",
            options=options(),
            allow_custom=True,
            status="pending",
        ))
        await db.commit()

    cancelled = await client.post(f"/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["can_retry"] is False
    assert cancelled.json()["can_revise"] is True

    retry = await client.post(f"/jobs/{job_id}/retry")
    assert retry.status_code == 409
    assert retry.json()["error_code"] == "JOB_NOT_RETRYABLE"
    assert queue.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "can_retry", "can_revise"),
    [
        ("failed", True, True),
        ("cancelled", True, True),
        ("partial", True, True),
        ("completed", False, True),
        ("pending", False, False),
        ("running", False, False),
        ("waiting_user", False, True),
    ],
)
async def test_job_action_capabilities_follow_backend_state_rules(api_client, status, can_retry, can_revise):
    client, factory, _ = api_client
    owner_id = await register(client, f"vnext-b-actions-{status}@example.com")
    job_id = await create_job(factory, owner_id, status=status)

    detail = await client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["can_retry"] is can_retry
    assert detail.json()["can_revise"] is can_revise

    listing = await client.get("/jobs?limit=100")
    listed = next(item for item in listing.json()["items"] if item["id"] == str(job_id))
    assert listed["can_retry"] is can_retry
    assert listed["can_revise"] is can_revise


def test_frontend_retry_actions_use_server_capabilities_and_handle_errors():
    root = Path(__file__).resolve().parents[1]
    job_page = (root / "frontend/src/app/jobs/[id]/page.tsx").read_text(encoding="utf-8")
    history_page = (root / "frontend/src/app/history/page.tsx").read_text(encoding="utf-8")

    assert "job.can_retry &&" in job_page
    assert "job.can_revise &&" in job_page
    assert "setRetryError(readableError(err))" in job_page
    assert "isLoading={retrying || reconcilingRetry}" in job_page
    assert "retryError &&" in job_page and 'role="alert"' in job_page
    assert "job.can_retry &&" in history_page
    assert "setRetryErrors" in history_page
    assert "isLoading={retryingId === job.id}" in history_page
    assert "['failed', 'cancelled'].includes(job.status)" not in job_page
    assert "['failed', 'cancelled'].includes(job.status)" not in history_page


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "running"])
async def test_active_job_cannot_be_revised(api_client, status):
    client, factory, queue = api_client
    owner_id = await register(client, f"vnext-b-{status}@example.com")
    job_id = await create_job(factory, owner_id, status=status)
    response = await client.post(f"/jobs/{job_id}/revisions", json={"query": "修改后的范围", "idempotency_key": f"revision-{status}-key"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "JOB_REVISION_INVALID"
    assert queue.calls == []


@pytest.mark.asyncio
async def test_completed_revision_preserves_report_and_source(api_client):
    client, factory, queue = api_client
    owner_id = await register(client, "vnext-b-completed@example.com")
    source_id = await create_job(
        factory,
        owner_id,
        status="completed",
        progress=100,
        topic_spec={"topic": "旧范围"},
        completed_at=datetime.now(timezone.utc),
    )
    async with factory() as db:
        report = Report(job_id=source_id, user_id=owner_id, title="旧报告", content="# 旧报告", structured_claims=[], status="completed", model_info={})
        db.add(report)
        await db.commit()
        report_id = report.id

    response = await client.post(
        f"/jobs/{source_id}/revisions",
        json={"query": "修订后的研究范围", "idempotency_key": "completed-revision-key"},
    )
    assert response.status_code == 202
    revised_id = uuid.UUID(response.json()["id"])
    assert queue.calls == [(str(revised_id), 0)]
    async with factory() as db:
        source = await db.get(AnalysisJob, source_id)
        report = await db.get(Report, report_id)
        revised = await db.get(AnalysisJob, revised_id)
        assert source.status == "completed"
        assert source.topic_spec == {"topic": "旧范围"}
        assert report.content == "# 旧报告"
        assert revised.revision_of_job_id == source_id


@pytest.mark.asyncio
async def test_revision_is_owned(api_client):
    client, factory, queue = api_client
    owner_id = await register(client, "vnext-b-revision-owner@example.com")
    source_id = await create_job(factory, owner_id, status="cancelled")
    await client.post("/auth/logout")
    await register(client, "vnext-b-revision-other@example.com")
    response = await client.post(
        f"/jobs/{source_id}/revisions",
        json={"query": "他人的修订", "idempotency_key": "foreign-revision-key"},
    )
    assert response.status_code == 404
    assert queue.calls == []


@pytest.mark.asyncio
async def test_reconciliation_recovers_process_exit_after_commit_before_enqueue(api_client, monkeypatch):
    from src import dispatch
    from src.api import job_routes

    client, factory, queue = api_client
    await register(client, "vnext-b-process-exit@example.com")

    class SimulatedProcessExit(BaseException):
        pass

    async def exit_before_enqueue(*_args, **_kwargs):
        raise SimulatedProcessExit

    monkeypatch.setattr(job_routes, "_enqueue_committed_job", exit_before_enqueue)
    with pytest.raises(SimulatedProcessExit):
        await client.post(
            "/jobs",
            json={
                "query": "模拟提交后进程退出",
                "platforms": ["bilibili"],
                "analysis_mode": "standard",
                "idempotency_key": "process-exit-after-commit",
            },
        )

    async with factory() as db:
        job = await db.scalar(select(AnalysisJob).where(AnalysisJob.idempotency_key == "process-exit-after-commit"))
        assert job is not None
        job_id = job.id
        assert job.status == "pending"
        assert job.arq_job_id is None
        assert job.dispatch_pending_at is not None

    monkeypatch.setattr(dispatch, "async_session_factory", factory)
    result = await reconcile_pending_dispatches(queue=queue, now=datetime.now(timezone.utc) + timedelta(minutes=5))
    assert result == {"leased": 1, "recovered": 1, "failed": 0}
    assert queue.calls == [(str(job_id), 0)]


@pytest.mark.asyncio
async def test_reconciliation_recovers_committed_dispatch_idempotently(session_factory, monkeypatch):
    from src import dispatch

    monkeypatch.setattr(dispatch, "async_session_factory", session_factory)
    user_id, job_id = None, None
    async with session_factory() as db:
        user = User(email="reconcile@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        user_id = user.id
        job = AnalysisJob(
            user_id=user.id,
            query="待恢复任务",
            platforms=["bilibili"],
            analysis_mode="standard",
            status="pending",
            retry_count=2,
            execution_version=5,
            arq_job_id=None,
            dispatch_pending_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    queue = CapturingQueue()
    now = datetime.now(timezone.utc)
    first = await reconcile_pending_dispatches(queue=queue, now=now)
    second = await reconcile_pending_dispatches(queue=queue, now=now)
    assert first == {"leased": 1, "recovered": 1, "failed": 0}
    assert second == {"leased": 0, "recovered": 0, "failed": 0}
    assert queue.calls == [(str(job_id), 5)]
    assert queue.ids == [f"analysis:{job_id}:v5"]

    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        events = list((await db.scalars(select(JobEvent).where(JobEvent.job_id == job_id))).all())
        assert job.user_id == user_id
        assert job.status == "pending"
        assert job.retry_count == 2
        assert job.execution_version == 5
        assert job.arq_job_id == f"analysis:{job_id}:v5"
        assert job.dispatch_pending_at is None
        assert [event.event_type for event in events] == ["dispatch_recovery_started", "dispatch_recovered"]


@pytest.mark.asyncio
async def test_reconciliation_uses_same_id_when_redis_already_received(session_factory, monkeypatch):
    from src import dispatch

    monkeypatch.setattr(dispatch, "async_session_factory", session_factory)
    async with session_factory() as db:
        user = User(email="redis-accepted@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id,
            query="Redis 已接收但数据库未确认",
            platforms=["bilibili"],
            analysis_mode="standard",
            status="pending",
            execution_version=3,
            dispatch_pending_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    queue = CapturingQueue()
    accepted_id = await queue.enqueue(str(job_id), 3)
    result = await reconcile_pending_dispatches(queue=queue, now=datetime.now(timezone.utc))
    assert result["recovered"] == 1
    assert queue.ids == [accepted_id, accepted_id]


@pytest.mark.asyncio
async def test_reconciliation_does_not_revive_other_states_or_recent_jobs(session_factory, monkeypatch):
    from src import dispatch

    monkeypatch.setattr(dispatch, "async_session_factory", session_factory)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with session_factory() as db:
        user = User(email="reconcile-states@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        for status in ("cancelled", "failed", "running", "waiting_user", "completed", "partial"):
            db.add(AnalysisJob(user_id=user.id, query=status, platforms=["bilibili"], analysis_mode="standard", status=status, dispatch_pending_at=old, idempotency_key=str(uuid.uuid4())))
        db.add(AnalysisJob(user_id=user.id, query="recent", platforms=["bilibili"], analysis_mode="standard", status="pending", dispatch_pending_at=datetime.now(timezone.utc), idempotency_key=str(uuid.uuid4())))
        db.add(AnalysisJob(user_id=user.id, query="already-dispatched", platforms=["bilibili"], analysis_mode="standard", status="pending", arq_job_id="analysis:existing:v0", dispatch_pending_at=old, idempotency_key=str(uuid.uuid4())))
        await db.commit()

    queue = CapturingQueue()
    result = await reconcile_pending_dispatches(queue=queue, now=datetime.now(timezone.utc))
    assert result == {"leased": 0, "recovered": 0, "failed": 0}
    assert queue.calls == []


@pytest.mark.asyncio
async def test_reconciliation_does_not_overwrite_new_execution_version(session_factory, monkeypatch):
    from src import dispatch

    monkeypatch.setattr(dispatch, "async_session_factory", session_factory)
    async with session_factory() as db:
        user = User(email="reconcile-version@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        job = AnalysisJob(user_id=user.id, query="版本竞争", platforms=["bilibili"], analysis_mode="standard", status="pending", execution_version=4, dispatch_pending_at=datetime.now(timezone.utc) - timedelta(minutes=5), idempotency_key=str(uuid.uuid4()))
        db.add(job)
        await db.commit()
        job_id = job.id

    queue = CapturingQueue()

    async def advance_version(current_job_id, _version):
        async with session_factory() as db:
            job = await db.get(AnalysisJob, current_job_id)
            job.execution_version = 5
            await db.commit()

    queue.on_enqueue = advance_version
    result = await reconcile_pending_dispatches(queue=queue, now=datetime.now(timezone.utc))
    assert result == {"leased": 1, "recovered": 0, "failed": 0}
    assert queue.calls == [(str(job_id), 4)]
    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.execution_version == 5
        assert job.arq_job_id is None


@pytest.mark.asyncio
async def test_reconciliation_failure_is_audited_and_rate_limited(session_factory, monkeypatch):
    from src import dispatch

    monkeypatch.setattr(dispatch, "async_session_factory", session_factory)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with session_factory() as db:
        user = User(email="reconcile-failure@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        job = AnalysisJob(user_id=user.id, query="恢复失败", platforms=["bilibili"], analysis_mode="standard", status="pending", retry_count=1, dispatch_pending_at=old, idempotency_key=str(uuid.uuid4()))
        db.add(job)
        await db.commit()
        job_id = job.id

    queue = CapturingQueue()
    queue.fail = True
    now = datetime.now(timezone.utc)
    first = await reconcile_pending_dispatches(queue=queue, now=now)
    second = await reconcile_pending_dispatches(queue=queue, now=now)
    assert first == {"leased": 1, "recovered": 0, "failed": 1}
    assert second == {"leased": 0, "recovered": 0, "failed": 0}
    assert queue.calls == [(str(job_id), 0)]
    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        events = list((await db.scalars(select(JobEvent).where(JobEvent.job_id == job_id))).all())
        assert job.status == "pending"
        assert job.retry_count == 1
        assert job.arq_job_id is None
        assert job.error_code == "DISPATCH_PENDING"
        assert job.dispatch_pending_at is not None
        assert [event.event_type for event in events] == ["dispatch_recovery_started", "dispatch_recovery_failed"]
