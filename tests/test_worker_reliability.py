"""Worker lifecycle regressions; all model, transcript and queue work is local."""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from contextvars import copy_context
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
import aiosqlite
from arq import Retry
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from langchain_core.messages import AIMessage

from src import worker
from src.db.models import AnalysisJob, EvidenceItem, JobEvent, Report, UsageRecord, User
from src.db.session import Base
from src.gateway.cost_tracker import cost_tracker
from src.utils.asr_usage_tracker import asr_usage_tracker
import src.tools.transcript as transcript_module


@pytest_asyncio.fixture
async def database(tmp_path, monkeypatch):
    # Use a fresh connection per transaction in these cancellation-heavy
    # SQLite fixtures; production locking is tested separately on PostgreSQL.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}", poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(worker, "async_session_factory", factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", False)
    monkeypatch.setattr(worker, "ENABLE_CANDIDATE_CONFIRMATION", False)
    monkeypatch.setattr(worker, "GRAPH_VERSION", "v2")
    monkeypatch.setattr(worker, "WORKER_HEARTBEAT_SECONDS", 0.01)
    cost_tracker.reset()
    yield factory
    await engine.dispose()


async def new_job(database, *, mode="standard", status="pending", retries=0):
    async with database() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="local-fixture")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id, query="分析公开相机视频", platforms=["bilibili"],
            analysis_mode=mode, status=status, retry_count=retries,
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.flush()
        db.add(UsageRecord(user_id=user.id, job_id=job.id))
        await db.commit()
        return job.id


def ctx(redis=None):
    result = {"provider_semaphore": asyncio.Semaphore(1)}
    if redis is not None:
        result["redis"] = redis
    return result


def collection(count=1):
    items = []
    for index in range(count):
        url = f"https://www.bilibili.com/video/BV{index:010d}"
        items.append({
            "evidence_id": f"ev_{index + 1:016x}", "tool": "search_videos",
            "source_type": "bilibili_video", "title": f"公开相机样本 {index}",
            "source_url": url, "platform": "bilibili", "raw_data": {},
            "data_fields": {"view": 100},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    return {
        "workflow_version": "v2", "data_sufficient": True, "evidence": items,
        "raw_data": [{"url": item["source_url"], "duration": 60, "_evidence_id": item["evidence_id"]} for item in items],
    }


def report_result(state=None):
    state = state or collection()
    evidence_id = state["evidence"][0]["evidence_id"]
    return {
        **state,
        "report_final": f"# 公开样本报告\n\n本次公开样本 [{evidence_id}]。",
        "analysis": {"claims": [{
            "claim": "本次采集到公开相机视频样本", "claim_type": "observation",
            "evidence_ids": [evidence_id], "confidence": 0.8,
        }]},
    }


async def read_job_and_usage(database, job_id):
    async with database() as db:
        job = await db.get(AnalysisJob, job_id)
        usage = await db.scalar(select(UsageRecord).where(UsageRecord.job_id == job_id))
        return job, usage


@pytest.mark.asyncio
async def test_graph_timeout_cancels_and_awaits_the_actual_graph():
    started = asyncio.Event()
    cleaned = asyncio.Event()
    graph_task = None

    class BlockingGraph:
        async def ainvoke(self, _state, config):
            nonlocal graph_task
            graph_task = asyncio.current_task()
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.01)
                cleaned.set()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(worker._invoke_compiled_graph(BlockingGraph(), uuid.uuid4(), 0, {}), timeout=0.03)
    assert started.is_set()
    assert cleaned.is_set()
    assert graph_task.done()


@pytest.mark.asyncio
async def test_same_version_can_only_be_claimed_once(database):
    job_id = await new_job(database)
    claims = await asyncio.gather(worker._claim_job(job_id, 0), worker._claim_job(job_id, 0))
    assert sum(claim is not None for claim in claims) == 1
    job, _ = await read_job_and_usage(database, job_id)
    assert job.status == "running"
    assert job.worker_token
    assert job.worker_lease_expires_at


@pytest.mark.asyncio
async def test_heartbeat_observing_a_committed_terminal_state_exits_cleanly(database):
    job_id = await new_job(database)
    job, _, token = await worker._claim_job(job_id, 0)
    execution = worker._Execution(job_id, 0, token, copy_context(), {})
    async with database() as db:
        current = await db.get(AnalysisJob, job_id)
        current.status = "completed"
        await db.commit()
    # The monitor may observe this commit before the work coroutine returns.
    # Accessing expired ORM fields after rollback must not require implicit IO.
    await asyncio.wait_for(worker._heartbeat(execution), 2)
    current, _ = await read_job_and_usage(database, job_id)
    assert current.status == "completed"
    assert current.worker_token == token


@pytest.mark.asyncio
async def test_cancel_finishes_active_heartbeat_cursor_before_settlement(database, monkeypatch):
    job_id = await new_job(database)
    entered = asyncio.Event()
    fetching = asyncio.Event()
    release_fetch = asyncio.Event()
    fetch_cancelled = False
    original_fetch = aiosqlite.Cursor.fetchall

    async def paused_fetch(cursor):
        nonlocal fetch_cancelled
        if entered.is_set() and asyncio.current_task().get_coro().__qualname__ == "_heartbeat" and not fetching.is_set():
            # The SELECT has executed while the heartbeat owns the SQLite
            # write transaction, but its cursor has not been consumed/closed.
            fetching.set()
            try:
                await release_fetch.wait()
            except asyncio.CancelledError:
                fetch_cancelled = True
                raise
        return await original_fetch(cursor)

    async def blocking_graph(*_args):
        cost_tracker.log_usage("analyst", "fixture", 17, 3)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(aiosqlite.Cursor, "fetchall", paused_fetch)
    monkeypatch.setattr(worker, "_invoke_graph", blocking_graph)
    task = asyncio.create_task(worker.run_analysis_job(ctx(), str(job_id), 0))
    await asyncio.wait_for(fetching.wait(), 2)
    task.cancel()
    await asyncio.sleep(0.01)
    release_fetch.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not fetch_cancelled
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "pending" and job.worker_token is None
    assert (usage.input_tokens, usage.output_tokens) == (17, 3)


@pytest.mark.asyncio
async def test_heartbeat_stop_grace_is_bounded(monkeypatch):
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def stalled_heartbeat(_execution, _stop):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def completed_work():
        await entered.wait()
        return "complete"

    monkeypatch.setattr(worker, "_heartbeat", stalled_heartbeat)
    monkeypatch.setattr(worker, "WORKER_HEARTBEAT_STOP_GRACE_SECONDS", 0.02)
    assert await asyncio.wait_for(worker._supervise(completed_work(), None), 1) == "complete"
    assert cleaned.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", [False, True])
async def test_infrastructure_cancel_propagates_and_keeps_measured_usage(database, monkeypatch, exhausted):
    job_id = await new_job(database, retries=worker.JOB_MAX_RETRIES if exhausted else 0)
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def blocking_graph(*_args):
        cost_tracker.log_usage("analyst", "deepseek-v4-pro", 17, 3)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr(worker, "_invoke_graph", blocking_graph)
    task = asyncio.create_task(worker.run_analysis_job(ctx(), str(job_id), 0))
    await asyncio.wait_for(started.wait(), 2)
    # At least one heartbeat must durably checkpoint usage before shutdown.
    for _ in range(100):
        job, usage = await read_job_and_usage(database, job_id)
        if usage.input_tokens == 17:
            break
        await asyncio.sleep(0.01)
    assert usage.input_tokens == 17
    assert job.worker_token
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == ("failed" if exhausted else "pending")
    assert job.retry_count == (worker.JOB_MAX_RETRIES if exhausted else 1)
    assert job.worker_token is None
    assert job.worker_lease_expires_at is None
    assert (usage.input_tokens, usage.output_tokens) == (17, 3)

    if not exhausted:
        async def recovered_graph(*_args):
            cost_tracker.log_usage("analyst", "deepseek-v4-pro", 5, 2)
            return report_result()
        monkeypatch.setattr(worker, "_invoke_graph", recovered_graph)
        await worker.run_analysis_job(ctx(), str(job_id), 0)
        job, usage = await read_job_and_usage(database, job_id)
        assert job.status == "completed"
        assert (usage.input_tokens, usage.output_tokens) == (22, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_signal", [False, True])
async def test_user_cancel_stops_work_without_requeue_and_settles_usage(database, monkeypatch, cancel_signal):
    job_id = await new_job(database)
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def blocking_graph(*_args):
        cost_tracker.log_usage("analyst", "deepseek-v4-pro", 9, 2)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr(worker, "_invoke_graph", blocking_graph)
    task = asyncio.create_task(worker.run_analysis_job(ctx(), str(job_id), 0))
    await asyncio.wait_for(started.wait(), 2)
    async with database() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = "cancelled"
        job.cancelled_at = datetime.now(timezone.utc)
        await db.commit()
    if cancel_signal:
        task.cancel()
    await asyncio.wait_for(task, 2)
    job, usage = await read_job_and_usage(database, job_id)
    assert cleaned.is_set()
    assert job.status == "cancelled"
    assert job.retry_count == 0
    assert job.worker_token is None
    assert (usage.input_tokens, usage.output_tokens) == (9, 2)


@pytest.mark.asyncio
async def test_deep_v2_synthesizes_once_after_transcript_evidence(database, monkeypatch):
    job_id = await new_job(database, mode="deep")
    calls = []

    async def collect(*_args):
        calls.append("collection")
        return collection()

    async def transcript(_url):
        calls.append("asr")
        asr_usage_tracker.record({"asr_usage_receipt": {"id": "fixture-completed-asr", "seconds": 60}})
        return {"text": "公开视频口播", "provider": "fixture", "model": "fixture", "audio_hash": "fixture", "fetched_at": datetime.now(timezone.utc).isoformat(), "asr_seconds": 60}

    async def synthesize(_job_id, _version, state):
        calls.append("synthesis")
        assert len(state["evidence"]) == 2
        assert state["evidence"][1]["source_type"] == "transcript"
        result = report_result(state)
        result.pop("asr_seconds", None)  # Graph state need not expose accounting fields.
        return result

    async def forbidden(*_args):
        raise AssertionError("deep v2 must not run the full graph or a second synthesis")

    monkeypatch.setattr(worker, "_invoke_collection_graph", collect)
    monkeypatch.setattr(worker, "get_transcript", transcript)
    monkeypatch.setattr(worker, "_invoke_synthesis_graph", synthesize)
    monkeypatch.setattr(worker, "_invoke_graph", forbidden)
    monkeypatch.setattr(worker, "_enrich_deep_analysis", forbidden)
    await worker.run_analysis_job(ctx(), str(job_id), 0)
    assert calls == ["collection", "asr", "synthesis"]
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "completed"
    assert usage.asr_seconds == 60
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Report)) == 1
        assert await db.scalar(select(func.count()).select_from(EvidenceItem)) == 2


@pytest.mark.asyncio
async def test_total_timeout_includes_asr_and_retains_completed_asr_usage(database, monkeypatch):
    job_id = await new_job(database, mode="deep")
    entered_second = asyncio.Event()
    cleaned = asyncio.Event()
    asr_calls = 0
    # This scenario needs two samples regardless of the developer's .env cap.
    monkeypatch.setattr(worker, "ASR_MAX_VIDEOS", 2)
    monkeypatch.setattr(worker, "JOB_TIMEOUT_SECONDS", 0.2)

    async def collect(*_args):
        cost_tracker.log_usage("planner", "deepseek-v4-pro", 10, 2)
        return collection(2)

    async def transcript(_url):
        nonlocal asr_calls
        asr_calls += 1
        if asr_calls == 1:
            asr_usage_tracker.record({"asr_usage_receipt": {"id": "fixture-first-asr", "seconds": 60}})
            return {"text": "首个已完成转写", "provider": "fixture", "model": "fixture", "audio_hash": "fixture", "fetched_at": datetime.now(timezone.utc).isoformat(), "asr_seconds": 60}
        entered_second.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def forbidden(*_args):
        raise AssertionError("synthesis must not start after ASR times out")

    monkeypatch.setattr(worker, "_invoke_collection_graph", collect)
    monkeypatch.setattr(worker, "get_transcript", transcript)
    monkeypatch.setattr(worker, "_invoke_synthesis_graph", forbidden)
    with pytest.raises(Retry):
        await worker.run_analysis_job(ctx(), str(job_id), 0)
    assert entered_second.is_set() and cleaned.is_set()
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "pending"
    assert job.worker_token is None
    assert usage.asr_seconds == 60
    assert usage.input_tokens == 10


@pytest.mark.asyncio
async def test_completion_cache_failure_does_not_repeat_paid_work(database, monkeypatch, caplog):
    job_id = await new_job(database)
    calls = 0

    async def graph(*_args):
        nonlocal calls
        calls += 1
        cost_tracker.log_usage("writer", "deepseek-v4-pro", 7, 5)
        return report_result()

    class FlakyRedis:
        async def hset(self, _key, mapping):
            if mapping["status"] == "completed":
                raise ConnectionError("injected cache outage after report commit")
        async def expire(self, *_args): pass
        async def xadd(self, *_args, **_kwargs): pass

    monkeypatch.setattr(worker, "_invoke_graph", graph)
    await worker.run_analysis_job(ctx(FlakyRedis()), str(job_id), 0)
    await worker.run_analysis_job(ctx(FlakyRedis()), str(job_id), 0)
    job, usage = await read_job_and_usage(database, job_id)
    assert calls == 1
    assert job.status == "completed"
    assert job.retry_count == 0
    assert usage.input_tokens == 7
    assert "Redis event projection failed" in caplog.text
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Report)) == 1
        assert await db.scalar(select(func.count()).select_from(JobEvent).where(JobEvent.event_type == "completed")) == 1


@pytest.mark.asyncio
async def test_result_replay_is_idempotent_for_report_evidence_and_usage(database):
    job_id = await new_job(database, status="running")
    cost_tracker.log_usage("writer", "deepseek-v4-pro", 10, 5)
    result = {**report_result(), "_expected_execution_version": 0}
    first = await worker._persist_result(job_id, result)
    second = await worker._persist_result(job_id, result)
    assert first == second
    _, usage = await read_job_and_usage(database, job_id)
    assert (usage.input_tokens, usage.output_tokens) == (10, 5)
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Report)) == 1
        assert await db.scalar(select(func.count()).select_from(EvidenceItem)) == 1


@pytest.mark.asyncio
async def test_late_failure_cannot_overwrite_a_replacement_execution(database, monkeypatch):
    job_id = await new_job(database)
    replacement_token = str(uuid.uuid4())

    async def late_failure(*_args):
        cost_tracker.log_usage("analyst", "deepseek-v4-pro", 11, 3)
        async with database() as db:
            job = await db.get(AnalysisJob, job_id)
            job.execution_version = 1
            job.worker_token = replacement_token
            job.worker_lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=90)
            await db.commit()
        raise TimeoutError("old execution finished after replacement")

    monkeypatch.setattr(worker, "_invoke_graph", late_failure)
    await worker.run_analysis_job(ctx(), str(job_id), 0)
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "running"
    assert job.execution_version == 1
    assert job.worker_token == replacement_token
    assert job.retry_count == 0
    assert usage.input_tokens == 11


@pytest.mark.asyncio
async def test_brief_context_reset_preserves_graph_usage_without_double_count(database, monkeypatch):
    job_id = await new_job(database)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)

    async def brief(jid, **_kwargs):
        cost_tracker.log_usage("planner", "deepseek-v4-pro", 7, 5)
        async with database() as db:
            job = await db.get(AnalysisJob, jid)
            job.interaction_usage = {"input_tokens": 7, "output_tokens": 5, "estimated_cost": cost_tracker.get_summary()["total_cost"], "calls": 1}
            await db.commit()
        return SimpleNamespace(ready=True, topic_spec=None)

    async def graph(*_args):
        cost_tracker.log_usage("analyst", "deepseek-v4-pro", 11, 2)
        return report_result()

    monkeypatch.setattr(worker, "validate_job_brief", brief)
    monkeypatch.setattr(worker, "_invoke_graph", graph)
    await worker.run_analysis_job(ctx(), str(job_id), 0)
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "completed"
    assert (usage.input_tokens, usage.output_tokens) == (18, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("interaction_already_recorded", [False, True])
async def test_brief_cancellation_settles_each_returned_call_once(database, monkeypatch, interaction_already_recorded):
    job_id = await new_job(database)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)
    entered = asyncio.Event()

    async def brief(jid, **_kwargs):
        cost_tracker.log_usage("planner", "deepseek-v4-pro", 7, 5)
        if interaction_already_recorded:
            async with database() as db:
                job = await db.get(AnalysisJob, jid)
                job.interaction_usage = {"input_tokens": 7, "output_tokens": 5, "estimated_cost": cost_tracker.get_summary()["total_cost"], "calls": 1}
                await db.commit()
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "validate_job_brief", brief)
    task = asyncio.create_task(worker.run_analysis_job(ctx(), str(job_id), 0))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _, usage = await read_job_and_usage(database, job_id)
    assert (usage.input_tokens, usage.output_tokens) == (7, 5)


@pytest.mark.asyncio
async def test_database_persistence_failure_is_visible_and_retains_usage(database, monkeypatch):
    job_id = await new_job(database)

    async def graph(*_args):
        cost_tracker.log_usage("writer", "deepseek-v4-pro", 13, 5)
        return report_result()

    async def broken_persistence(*_args):
        raise RuntimeError("injected database transaction failure")

    monkeypatch.setattr(worker, "_invoke_graph", graph)
    monkeypatch.setattr(worker, "_persist_result", broken_persistence)
    with pytest.raises(Retry):
        await worker.run_analysis_job(ctx(), str(job_id), 0)
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "pending"
    assert usage.input_tokens == 13
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Report)) == 0


def install_local_asr(monkeypatch):
    """Exercise the actual transcript entry point without network or audio IO."""
    cache = {}
    calls = []

    class Provider:
        name = "fixture"
        available = True

        async def transcribe(self, **kwargs):
            calls.append(kwargs["video_url"])
            return {
                "text": "实际完成的测试转写", "source_url": kwargs["video_url"],
                "provider": "fixture", "model": "fixture", "audio_hash": kwargs["audio_hash"],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

    async def cache_get(key):
        return dict(cache[key]) if key in cache else None

    async def cache_set(keys, value):
        for key in keys:
            cache[key] = dict(value)

    async def extract_audio(url):
        return url.encode(), "mp3", 60.0

    monkeypatch.setattr(transcript_module, "get_transcript_providers", lambda: [Provider()])
    monkeypatch.setattr(transcript_module, "_extract_audio", extract_audio)
    monkeypatch.setattr(transcript_module, "_cache_get", cache_get)
    monkeypatch.setattr(transcript_module, "_cache_set", cache_set)
    return calls


@pytest.mark.asyncio
async def test_deep_retry_and_new_job_do_not_charge_cached_asr_again(database, monkeypatch):
    job_id = await new_job(database, mode="deep")
    provider_calls = install_local_asr(monkeypatch)
    synthesis_calls = 0

    async def collect(*_args):
        return collection()

    async def synthesize(_job_id, _version, state):
        nonlocal synthesis_calls
        synthesis_calls += 1
        if synthesis_calls == 1:
            raise TimeoutError("analysis failed after provider returned")
        return report_result(state)

    monkeypatch.setattr(worker, "_invoke_collection_graph", collect)
    monkeypatch.setattr(worker, "_invoke_synthesis_graph", synthesize)
    with pytest.raises(Retry):
        await worker.run_analysis_job(ctx(), str(job_id), 0)
    _, usage = await read_job_and_usage(database, job_id)
    assert usage.asr_seconds == 60

    await worker.run_analysis_job(ctx(), str(job_id), 0)
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "completed"
    assert usage.asr_seconds == 60
    attempts = [entry for key, entry in usage.accounted_attempts.items() if key.startswith("attempt:")]
    assert sorted(entry["asr_seconds"] for entry in attempts) == [0, 60]

    another_job_id = await new_job(database, mode="deep")
    await worker.run_analysis_job(ctx(), str(another_job_id), 0)
    another_job, another_usage = await read_job_and_usage(database, another_job_id)
    assert another_job.status == "completed"
    assert another_usage.asr_seconds == 0
    assert len(provider_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["remote", "local_fallback", "in_process"])
async def test_researcher_transcripts_share_attempt_usage_across_transports(database, monkeypatch, transport):
    from mcp.client import session as session_module, sse as sse_module
    from src.graph import v2

    job_id = await new_job(database)
    provider_calls = install_local_asr(monkeypatch)
    url = "https://www.bilibili.com/video/BV1xx411c7mD"
    remote_payload = {
        "text": "远端工具返回的转写", "source_url": url, "audio_seconds": 60, "asr_seconds": 60,
        "asr_usage_receipt": {"id": "remote-completed-call", "seconds": 60},
    }

    @asynccontextmanager
    async def transport_stream(_url):
        if transport == "local_fallback":
            raise ConnectionError("injected unavailable MCP transport")
        yield None, None

    class Session:
        def __init__(self, *_args, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def initialize(self): pass
        async def call_tool(self, tool_name, params):
            assert tool_name == "get_transcript"
            if transport == "in_process":
                payload = await transcript_module.get_transcript(params["video_url"])
            else:
                payload = remote_payload
            return SimpleNamespace(structured_content={"result": payload})

    class LLM:
        async def ainvoke(self, _messages):
            return AIMessage(content=json.dumps({"tool": "get_transcript", "params": {"video_url": url}}))

    async def graph(*_args):
        state = {
            "platforms": ["bilibili"],
            "research_tasks": [{"description": "转写指定公开视频", "evidence_type": "transcript"}],
            "current_step": 0,
        }
        result = await asyncio.create_task(v2.researcher_v2_node(state))
        # Receiving the same completed-call receipt again must not double it.
        await v2.call_tool_via_mcp("get_transcript", {"video_url": url})
        assert result["tool_results"][0]["status"] == "success"
        return report_result(result)

    monkeypatch.setattr(sse_module, "sse_client", transport_stream)
    monkeypatch.setattr(session_module, "ClientSession", Session)
    monkeypatch.setattr(v2, "get_llm", lambda _agent: LLM())
    monkeypatch.setattr(worker, "_invoke_graph", graph)
    await worker.run_analysis_job(ctx(), str(job_id), 0)
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "completed"
    assert usage.asr_seconds == 60
    assert len(provider_calls) == (0 if transport == "remote" else 1)


@pytest.mark.asyncio
async def test_completed_asr_is_checkpointed_even_if_cancelled_during_cache_write(database, monkeypatch):
    job_id = await new_job(database)
    provider_calls = install_local_asr(monkeypatch)
    cache_entered = asyncio.Event()

    async def cache_write(*_args):
        cache_entered.set()
        await asyncio.Event().wait()

    async def graph(*_args):
        await transcript_module.get_transcript("https://www.bilibili.com/video/BV1xx411c7mD")
        raise AssertionError("cache write must be interrupted")

    monkeypatch.setattr(transcript_module, "_cache_set", cache_write)
    monkeypatch.setattr(worker, "_invoke_graph", graph)
    task = asyncio.create_task(worker.run_analysis_job(ctx(), str(job_id), 0))
    await asyncio.wait_for(cache_entered.wait(), 2)
    for _ in range(100):
        _, usage = await read_job_and_usage(database, job_id)
        if usage.asr_seconds == 60:
            break
        await asyncio.sleep(0.01)
    assert usage.asr_seconds == 60
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "pending" and job.worker_token is None
    assert usage.asr_seconds == 60
    assert len(provider_calls) == 1


@pytest.mark.asyncio
async def test_remote_asr_receipt_survives_cancellation_during_mcp_cleanup(database, monkeypatch):
    from mcp.client import session as session_module, sse as sse_module
    from src.agents.researcher import call_tool_via_mcp

    job_id = await new_job(database)
    cleanup_entered = asyncio.Event()

    @asynccontextmanager
    async def transport_stream(_url):
        yield None, None

    class Session:
        def __init__(self, *_args, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args):
            cleanup_entered.set()
            await asyncio.Event().wait()
        async def initialize(self): pass
        async def call_tool(self, *_args):
            return SimpleNamespace(structured_content={"result": {
                "text": "远端已完成的转写",
                "asr_usage_receipt": {"id": "remote-before-cleanup", "seconds": 75},
            }})

    async def graph(*_args):
        await call_tool_via_mcp("get_transcript", {"video_url": "https://www.bilibili.com/video/BV1xx411c7mD"})
        raise AssertionError("MCP cleanup must be interrupted")

    monkeypatch.setattr(sse_module, "sse_client", transport_stream)
    monkeypatch.setattr(session_module, "ClientSession", Session)
    monkeypatch.setattr(worker, "_invoke_graph", graph)
    task = asyncio.create_task(worker.run_analysis_job(ctx(), str(job_id), 0))
    await asyncio.wait_for(cleanup_entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    job, usage = await read_job_and_usage(database, job_id)
    assert job.status == "pending" and job.worker_token is None
    assert usage.asr_seconds == 75


@pytest.mark.asyncio
async def test_parallel_jobs_keep_their_asr_usage_isolated(database, monkeypatch):
    job_ids = [await new_job(database), await new_job(database)]
    install_local_asr(monkeypatch)
    arrivals = 0
    both_returned = asyncio.Event()
    durations = {job_ids[0]: 60, job_ids[1]: 90}
    async def extract_audio(url):
        return url.encode(), "mp3", float(url.rsplit("/", 1)[-1])

    monkeypatch.setattr(transcript_module, "_extract_audio", extract_audio)

    async def graph(job_id, *_args):
        nonlocal arrivals
        await asyncio.create_task(transcript_module.get_transcript(f"https://www.bilibili.com/video/{durations[job_id]}"))
        arrivals += 1
        if arrivals == 2:
            both_returned.set()
        await both_returned.wait()
        return report_result()

    monkeypatch.setattr(worker, "_invoke_graph", graph)
    await asyncio.wait_for(asyncio.gather(*(
        worker.run_analysis_job(ctx(), str(job_id), 0) for job_id in job_ids
    )), 5)
    for job_id, expected_seconds in durations.items():
        job, usage = await read_job_and_usage(database, job_id)
        assert job.status == "completed"
        assert usage.asr_seconds == expected_seconds
