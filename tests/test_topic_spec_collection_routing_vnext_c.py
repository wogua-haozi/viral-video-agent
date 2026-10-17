import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import worker
from src.briefing import service as briefing_service
from src.briefing.schemas import BriefDecision, BriefOption, TopicSpec
from src.db.models import (
    AnalysisJob,
    CandidateAccount,
    CandidateSnapshot,
    CollectionSnapshot,
    JobClarification,
    User,
)
from src.db.session import Base, get_db
from src.graph import v2
from src.main import app
from src.queue import get_job_queue


def topic_spec(**overrides) -> dict:
    values = {
        "topic": "相机",
        "target_content": ["相机测评"],
        "include_creator_types": ["reviewer"],
        "exclude_content": ["旅行日志"],
        "time_window_days": 365,
        "allow_generalist": False,
        "competitor_definition": "持续发布相机相关内容的账号",
        "platform": "bilibili",
        "assumptions": [],
        "confidence": 0.88,
    }
    values.update(overrides)
    return values


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    database_path = (tmp_path / "topic-spec-routing.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


class CapturingQueue:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    async def enqueue(self, job_id: str, execution_version: int = 0) -> str:
        self.calls.append((job_id, execution_version))
        return f"analysis:{job_id}:v{execution_version}"


@pytest_asyncio.fixture
async def api_client(session_factory):
    queue = CapturingQueue()

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory, queue
    app.dependency_overrides.clear()


async def register(client: AsyncClient, email: str) -> uuid.UUID:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "strong-pass-123"},
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


@pytest.fixture
def fake_collection_dependencies(monkeypatch):
    calls = {"planner": 0, "researcher": 0, "tool": 0, "direct": 0}
    prompts = []

    class FakeLlm:
        def __init__(self, role: str):
            self.role = role

        async def ainvoke(self, messages):
            calls[self.role] += 1
            prompts.append(messages[-1].content)
            if self.role == "planner":
                content = json.dumps({
                    "tasks": [{
                        "description": "采集已确认 TopicSpec 对应的 B 站视频样本",
                        "evidence_type": "search",
                    }]
                }, ensure_ascii=False)
            else:
                content = json.dumps({
                    "tool": "search_videos",
                    "params": {
                        "keyword": "相机测评",
                        "platforms": ["bilibili"],
                        "limit": 10,
                    },
                }, ensure_ascii=False)
            return SimpleNamespace(
                content=content,
                usage_metadata={"input_tokens": 1, "output_tokens": 1},
            )

    def fake_get_llm(agent_name=None):
        return FakeLlm("researcher" if agent_name == "researcher" else "planner")

    async def fake_tool(tool_name, params):
        calls["tool"] += 1
        assert tool_name == "search_videos"
        assert params["platforms"] == ["bilibili"]
        return [{
            "platform": "bilibili",
            "bvid": "BV0000000001",
            "title": "虚构路由测试：相机测评",
            "platform_account_id": "12345",
            "display_name": "虚构路由账号",
            "profile_url": "https://space.bilibili.com/12345",
            "author": "虚构路由账号",
            "url": "https://www.bilibili.com/video/BV0000000001",
            "pubdate": int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()),
        }]

    async def fake_direct(user_request):
        calls["direct"] += 1
        return f"direct:{user_request}"

    monkeypatch.setattr(v2, "get_llm", fake_get_llm)
    monkeypatch.setattr(v2, "call_tool_via_mcp", fake_tool)
    monkeypatch.setattr(v2, "_direct_answer", fake_direct)
    return calls, prompts


async def invoke_collection(query: str, structured_scope: dict | None = None) -> dict:
    graph = v2.build_collection_graph_v2()
    return await graph.ainvoke(
        worker._initial_state(uuid.uuid4(), query, ["bilibili"], structured_scope)
    )


@pytest.mark.asyncio
async def test_short_query_runs_from_api_through_clarification_to_candidate_confirmation(
    api_client,
    monkeypatch,
    fake_collection_dependencies,
):
    client, factory, queue = api_client
    calls, _ = fake_collection_dependencies
    await register(client, "topic-routing-api@example.com")
    created = await client.post(
        "/jobs",
        json={
            "query": "相机",
            "platforms": ["bilibili"],
            "analysis_mode": "standard",
            "idempotency_key": "topic-routing-api-job",
        },
    )
    assert created.status_code == 202, created.text
    assert created.json()["query"] == "相机"
    job_id = uuid.UUID(created.json()["id"])
    assert queue.calls == [(str(job_id), 0)]

    brief_calls = []

    class FakeBriefValidator:
        async def validate(self, query, history, round_number):
            brief_calls.append({
                "query": query,
                "history": history,
                "round": round_number,
            })
            if round_number == 1:
                return BriefDecision(
                    need_clarification=True,
                    question="是否只纳入专业相机账号？",
                    options=[
                        BriefOption(
                            id="strict",
                            label="只看专业账号",
                            description="排除偶尔发布相机内容的综合账号",
                        ),
                        BriefOption(
                            id="generalist",
                            label="允许综合账号",
                            description="纳入稳定发布相机内容的综合账号",
                        ),
                    ],
                    allow_custom=True,
                    verification="需要确认账号范围",
                    confidence=0.6,
                )
            assert history == [{
                "round": 1,
                "question": "是否只纳入专业相机账号？",
                "selected_option_id": "strict",
                "custom_answer": None,
            }]
            return BriefDecision(
                need_clarification=False,
                verification="用户已确认只纳入专业账号",
                topic_spec=TopicSpec.model_validate(topic_spec()),
                confidence=0.88,
            )

    monkeypatch.setattr(worker, "async_session_factory", factory)
    monkeypatch.setattr(briefing_service, "async_session_factory", factory)
    monkeypatch.setattr(briefing_service, "BriefValidator", FakeBriefValidator)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)
    monkeypatch.setattr(worker, "ENABLE_CANDIDATE_CONFIRMATION", True)
    monkeypatch.setattr(worker, "collection_graph", v2.build_collection_graph_v2())

    await worker.run_analysis_job(
        {"provider_semaphore": asyncio.Semaphore(1)},
        str(job_id),
        0,
    )
    waiting = await client.get(f"/jobs/{job_id}")
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "waiting_user"
    clarification = await client.get(f"/jobs/{job_id}/clarification")
    assert clarification.status_code == 200
    request_id = clarification.json()["current"]["request_id"]

    answered = await client.post(
        f"/jobs/{job_id}/clarification",
        json={
            "request_id": request_id,
            "selected_option_id": "strict",
        },
    )
    assert answered.status_code == 202, answered.text
    assert answered.json()["status"] == "pending"
    assert answered.json()["execution_version"] == 1
    assert queue.calls == [(str(job_id), 0), (str(job_id), 1)]

    await worker.run_analysis_job(
        {"provider_semaphore": asyncio.Semaphore(1)},
        str(job_id),
        1,
    )

    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        clarification_rows = list((await db.scalars(
            select(JobClarification).where(JobClarification.job_id == job_id)
        )).all())
        collection_count = await db.scalar(
            select(func.count()).select_from(CollectionSnapshot).where(
                CollectionSnapshot.job_id == job_id
            )
        )
        candidate_snapshot_count = await db.scalar(
            select(func.count()).select_from(CandidateSnapshot).where(
                CandidateSnapshot.job_id == job_id
            )
        )
        candidate_count = await db.scalar(
            select(func.count())
            .select_from(CandidateAccount)
            .join(CandidateSnapshot, CandidateSnapshot.id == CandidateAccount.snapshot_id)
            .where(CandidateSnapshot.job_id == job_id)
        )
        assert job.query == "相机"
        assert job.topic_spec == topic_spec()
        assert job.status == "waiting_candidate_confirmation"
        assert len(clarification_rows) == 1
        assert clarification_rows[0].status == "answered"
        assert collection_count == 1
        assert candidate_snapshot_count == 1
        assert candidate_count == 1

    assert brief_calls == [
        {"query": "相机", "history": [], "round": 1},
        {
            "query": "相机",
            "history": [{
                "round": 1,
                "question": "是否只纳入专业相机账号？",
                "selected_option_id": "strict",
                "custom_answer": None,
            }],
            "round": 2,
        },
    ]
    assert calls == {"planner": 1, "researcher": 1, "tool": 1, "direct": 0}


@pytest.mark.asyncio
async def test_job_create_trims_two_character_query(api_client):
    client, factory, queue = api_client
    await register(client, "short-query-create@example.com")
    response = await client.post(
        "/jobs",
        json={
            "query": "  AI  ",
            "platforms": ["bilibili"],
            "analysis_mode": "standard",
            "idempotency_key": "short-query-create",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["query"] == "AI"
    job_id = uuid.UUID(response.json()["id"])
    async with factory() as db:
        assert (await db.get(AnalysisJob, job_id)).query == "AI"
    assert queue.calls == [(str(job_id), 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["   ", "相", "x" * 2001])
async def test_job_create_rejects_queries_outside_frozen_contract(api_client, query):
    client, _, queue = api_client
    await register(client, f"invalid-create-{uuid.uuid4()}@example.com")
    response = await client.post(
        "/jobs",
        json={
            "query": query,
            "platforms": ["bilibili"],
            "analysis_mode": "standard",
            "idempotency_key": f"invalid-create-{uuid.uuid4()}",
        },
    )
    assert response.status_code == 422
    assert queue.calls == []


@pytest.mark.asyncio
async def test_job_revision_uses_same_trimmed_two_character_query_contract(api_client):
    client, factory, queue = api_client
    await register(client, "short-query-revision@example.com")
    source = await client.post(
        "/jobs",
        json={
            "query": "分析B站相机赛道的竞争账号",
            "platforms": ["bilibili"],
            "analysis_mode": "standard",
            "idempotency_key": "short-query-revision-source",
        },
    )
    assert source.status_code == 202, source.text
    source_id = uuid.UUID(source.json()["id"])
    assert (await client.post(f"/jobs/{source_id}/cancel")).status_code == 200

    revised = await client.post(
        f"/jobs/{source_id}/revisions",
        json={
            "query": "  相机  ",
            "idempotency_key": "short-query-revision-target",
        },
    )
    assert revised.status_code == 202, revised.text
    assert revised.json()["query"] == "相机"
    revised_id = uuid.UUID(revised.json()["id"])
    async with factory() as db:
        assert (await db.get(AnalysisJob, revised_id)).query == "相机"

    for index, invalid_query in enumerate(("   ", "相", "x" * 2001), 1):
        invalid = await client.post(
            f"/jobs/{source_id}/revisions",
            json={
                "query": invalid_query,
                "idempotency_key": f"invalid-revision-{index}",
            },
        )
        assert invalid.status_code == 422

    assert queue.calls == [(str(source_id), 0), (str(revised_id), 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["相机", "分析相机账号", "AI 编程赛道的标题钩子"])
async def test_valid_topic_spec_routes_ambiguous_query_through_real_collection_graph(
    query,
    fake_collection_dependencies,
):
    calls, prompts = fake_collection_dependencies
    result = await invoke_collection(query, topic_spec())

    assert result["data_sufficient"] is True
    assert len(result["evidence"]) == 1
    assert result["topic_spec"]["platform"] == "bilibili"
    assert calls == {"planner": 1, "researcher": 1, "tool": 1, "direct": 0}
    assert query in prompts[0]
    assert "TopicSpec" in prompts[0]


@pytest.mark.asyncio
async def test_persisted_topic_spec_reaches_waiting_confirmation_once(
    session_factory,
    monkeypatch,
    fake_collection_dependencies,
):
    calls, _ = fake_collection_dependencies
    async with session_factory() as db:
        user = User(email="topic-routing@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id,
            query="相机",
            platforms=["bilibili"],
            analysis_mode="standard",
            status="pending",
            topic_spec=topic_spec(),
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(briefing_service, "async_session_factory", session_factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)
    monkeypatch.setattr(worker, "ENABLE_CANDIDATE_CONFIRMATION", True)
    brief_calls = 0

    async def counted_brief(current_job_id, expected_execution_version=None):
        nonlocal brief_calls
        brief_calls += 1
        return await briefing_service.validate_job_brief(
            current_job_id,
            expected_execution_version=expected_execution_version,
        )

    monkeypatch.setattr(worker, "validate_job_brief", counted_brief)
    await worker.run_analysis_job(
        {"provider_semaphore": asyncio.Semaphore(1)},
        str(job_id),
        0,
    )

    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.query == "相机"
        assert job.status == "waiting_candidate_confirmation"
        assert await db.scalar(
            select(func.count()).select_from(CollectionSnapshot).where(
                CollectionSnapshot.job_id == job_id
            )
        ) == 1
        assert await db.scalar(
            select(func.count()).select_from(CandidateAccount)
        ) >= 1

    assert brief_calls == 1
    assert calls == {"planner": 1, "researcher": 1, "tool": 1, "direct": 0}


@pytest.mark.asyncio
async def test_no_topic_spec_non_analysis_request_keeps_direct_answer_behavior(
    fake_collection_dependencies,
):
    calls, _ = fake_collection_dependencies
    result = await invoke_collection("你好")

    assert result["task_complete"] is True
    assert result["report_final"] == "direct:你好"
    assert calls == {"planner": 0, "researcher": 0, "tool": 0, "direct": 1}


@pytest.mark.asyncio
async def test_explicit_analysis_without_topic_spec_keeps_collection_behavior(
    fake_collection_dependencies,
):
    calls, _ = fake_collection_dependencies
    result = await invoke_collection("分析B站相机赛道的竞争账号")

    assert result["data_sufficient"] is True
    assert calls == {"planner": 1, "researcher": 1, "tool": 1, "direct": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_scope", [
    topic_spec(platform="douyin"),
    topic_spec(target_content=[]),
    {**topic_spec(), "unexpected": True},
])
async def test_invalid_topic_spec_is_rejected_before_any_graph_expansion(
    invalid_scope,
    fake_collection_dependencies,
):
    calls, _ = fake_collection_dependencies
    result = await invoke_collection("分析B站相机赛道的竞争账号", invalid_scope)

    assert result["task_complete"] is True
    assert result["termination_reason"] == "invalid_topic_spec"
    assert calls == {"planner": 0, "researcher": 0, "tool": 0, "direct": 0}


@pytest.mark.asyncio
async def test_candidate_feature_off_uses_legacy_full_graph_path(
    session_factory,
    monkeypatch,
):
    async with session_factory() as db:
        user = User(email="feature-off-routing@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id,
            query="分析B站相机赛道的竞争账号",
            platforms=["bilibili"],
            analysis_mode="standard",
            status="pending",
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", False)
    monkeypatch.setattr(worker, "ENABLE_CANDIDATE_CONFIRMATION", False)
    captured = {}

    async def forbidden_brief(*_args, **_kwargs):
        raise AssertionError("brief must stay disabled")

    async def forbidden_collection(*_args, **_kwargs):
        raise AssertionError("candidate collection graph must stay disabled")

    async def legacy_graph(_job_id, _user_id, query, platforms, structured_scope, execution_version):
        captured.update(
            query=query,
            platforms=platforms,
            topic_spec=structured_scope,
            execution_version=execution_version,
        )
        return {"report_final": "# legacy", "analysis": {"claims": []}, "evidence": []}

    async def fake_persist(_job_id, _result):
        return uuid.uuid4()

    monkeypatch.setattr(worker, "validate_job_brief", forbidden_brief)
    monkeypatch.setattr(worker, "_invoke_collection_graph", forbidden_collection)
    monkeypatch.setattr(worker, "_invoke_graph", legacy_graph)
    monkeypatch.setattr(worker, "_persist_result", fake_persist)
    await worker.run_analysis_job(
        {"provider_semaphore": asyncio.Semaphore(1)},
        str(job_id),
        0,
    )

    assert captured == {
        "query": "分析B站相机赛道的竞争账号",
        "platforms": ["bilibili"],
        "topic_spec": None,
        "execution_version": 0,
    }
