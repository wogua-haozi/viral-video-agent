import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import worker
from src.briefing import service as briefing_service
from src.db.models import AnalysisJob, CandidateAccount, CollectionSnapshot, User
from src.db.session import Base
from src.graph import v2


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
