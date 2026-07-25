import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.job_routes import router
from src.candidates.schemas import CandidateDecisionSubmit, CandidateProjection, deterministic_candidate_id
from src.candidates.service import (
    candidate_snapshot_payload,
    canonical_hash,
    collection_snapshot_payload,
    decision_payload_hash,
    extract_candidates,
    topic_summary,
)
from src.db.models import (
    AnalysisJob,
    CandidateDecisionBatch,
    CandidateSnapshot,
    CandidateSynthesisRun,
    CollectionSnapshot,
    EvidenceItem,
    Report,
    UsageRecord,
    User,
)
from src.db.session import Base, get_db
from src.gateway.cost_tracker import cost_tracker
from src.main import app
from src.queue import get_job_queue
from src import worker


def topic_spec() -> dict:
    return {
        "topic": "相机",
        "target_content": ["相机测评"],
        "include_creator_types": ["reviewer"],
        "exclude_content": ["旅行日志"],
        "time_window_days": 365,
        "allow_generalist": False,
        "competitor_definition": "持续发布相机测评的账号",
        "platform": "bilibili",
        "assumptions": [],
        "confidence": 0.9,
    }


def video_evidence(mid: str | None, index: int, *, name: str | None = None, title: str | None = None) -> tuple[dict, dict]:
    evidence_id = f"ev_{index:016x}"
    bvid = f"BV{index:010d}"
    display_name = name or f"候选账号{index}"
    source_url = f"https://www.bilibili.com/video/{bvid}"
    raw = {
        "platform": "bilibili",
        "bvid": bvid,
        "title": title or f"真实视频标题{index}",
        "platform_account_id": mid,
        "display_name": display_name,
        "profile_url": f"https://space.bilibili.com/{mid}" if mid else None,
        "author": display_name,
        "url": source_url,
        "view": index * 100,
        "_evidence_id": evidence_id,
    }
    evidence = {
        "evidence_id": evidence_id,
        "tool": "search_videos",
        "source_type": "bilibili_video",
        "title": raw["title"],
        "source_url": source_url,
        "platform": "bilibili",
        "fetched_at": datetime(2026, 7, 25, tzinfo=timezone.utc).isoformat(),
        "raw_data": {key: value for key, value in raw.items() if key != "_evidence_id"},
        "summary": None,
        "data_fields": {
            "bvid": bvid,
            "platform_account_id": mid,
            "display_name": display_name,
            "profile_url": raw["profile_url"],
        },
        "transcript_segment": None,
    }
    return raw, evidence


def transcript_evidence(index: int, source_url: str) -> tuple[dict, dict]:
    evidence_id = f"ev_{index:016x}"
    raw = {
        "title": "视频转写",
        "source_url": source_url,
        "text": "公开视频转写文本",
        "_evidence_id": evidence_id,
    }
    evidence = {
        "evidence_id": evidence_id,
        "tool": "get_transcript",
        "source_type": "transcript",
        "title": "视频转写",
        "source_url": source_url,
        "platform": "bilibili",
        "fetched_at": datetime(2026, 7, 25, tzinfo=timezone.utc).isoformat(),
        "raw_data": {"provider": "fake", "model": "fake", "audio_hash": "hash"},
        "summary": "公开视频转写文本",
        "data_fields": {},
        "transcript_segment": {"text": "公开视频转写文本", "segments": []},
    }
    return raw, evidence


def collection_result(items: list[tuple[dict, dict]]) -> dict:
    return {
        "workflow_version": "v2",
        "topic_spec": topic_spec(),
        "plan": ["采集真实视频样本"],
        "raw_data": [item[0] for item in items],
        "evidence": [item[1] for item in items],
        "tool_results": [{"tool": "search_videos", "status": "success"}],
        "search_queries_used": ["相机测评"],
        "asr_seconds": 0,
    }


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    database_path = (tmp_path / "candidate-confirmation.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


class CapturingQueue:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []
        self.fail = False

    async def enqueue(self, job_id: str, execution_version: int = 0) -> str:
        self.calls.append((job_id, execution_version))
        if self.fail:
            raise RuntimeError("queue unavailable")
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
    response = await client.post("/auth/register", json={"email": email, "password": "strong-pass-123"})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def create_job(factory, user_id: uuid.UUID, *, status: str = "running", execution_version: int = 0) -> uuid.UUID:
    async with factory() as db:
        job = AnalysisJob(
            user_id=user_id,
            query="分析B站相机赛道的竞争账号",
            platforms=["bilibili"],
            analysis_mode="standard",
            status=status,
            execution_version=execution_version,
            topic_spec=topic_spec(),
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.commit()
        return job.id


async def persist_candidates(factory, job_id: uuid.UUID, items: list[tuple[dict, dict]], execution_version: int = 0):
    worker.async_session_factory = factory
    cost_tracker.reset()
    return await worker._persist_collection_snapshot(job_id, execution_version, collection_result(items))


def test_candidate_identity_deduplication_sorting_limit_and_hash_are_deterministic():
    evidence = []
    for index, mid in enumerate(["20", "10", "20", "30", None, "40", "50", "60", "70", "80", "90"], 1):
        _, item = video_evidence(mid, index, name="同名账号" if mid in {"10", "20"} else None)
        evidence.append(item)
    candidates = extract_candidates(evidence)
    assert len(candidates) == 8
    assert candidates[0].platform_account_id == "20"
    assert candidates[0].matched_video_count == 2
    assert candidates[0].source_evidence_ids == ["ev_0000000000000001", "ev_0000000000000003"]
    assert candidates[1].platform_account_id == "10"
    assert candidates[0].display_name == candidates[1].display_name
    assert candidates[0].candidate_id != candidates[1].candidate_id
    assert all(item.platform_account_id for item in candidates)
    assert all(len(item.sample_titles) <= 3 for item in candidates)
    assert all(len(item.evidence_links) <= 3 for item in candidates)
    assert deterministic_candidate_id("20") == candidates[0].candidate_id
    summary = topic_summary(topic_spec())
    payload = candidate_snapshot_payload(
        source_execution_version=3,
        collection_snapshot_hash="a" * 64,
        topic=summary,
        candidates=candidates,
    )
    assert canonical_hash(payload) == canonical_hash(payload)


def test_candidate_contract_and_decision_payload_are_strict():
    candidate = extract_candidates([video_evidence("123", 1)[1]])[0]
    with pytest.raises(ValidationError):
        CandidateProjection.model_validate({**candidate.model_dump(), "followers": 100})
    with pytest.raises(ValidationError):
        CandidateDecisionSubmit.model_validate({
            "request_id": str(uuid.uuid4()),
            "snapshot_id": str(uuid.uuid4()),
            "decisions": [{"candidate_id": candidate.candidate_id, "decision": "undecided"}],
        })
    decisions = [{"candidate_id": candidate.candidate_id, "decision": "confirmed", "reason": " 匹配 "}]
    assert decision_payload_hash("snapshot", decisions) == decision_payload_hash("snapshot", list(reversed(decisions)))


@pytest.mark.asyncio
async def test_collection_persists_across_sessions_and_pauses_before_synthesis(session_factory):
    async with session_factory() as db:
        user = User(email="collection@example.com", hashed_password="hashed")
        db.add(user)
        await db.commit()
        user_id = user.id
    job_id = await create_job(session_factory, user_id)
    result = await persist_candidates(session_factory, job_id, [video_evidence("100", 1), video_evidence("100", 2), video_evidence("200", 3)])
    assert result["candidate_count"] == 2

    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        collection = await db.scalar(select(CollectionSnapshot).where(CollectionSnapshot.job_id == job_id))
        snapshot = await db.scalar(select(CandidateSnapshot).where(CandidateSnapshot.job_id == job_id))
        usage = await db.scalar(select(UsageRecord).where(UsageRecord.job_id == job_id))
        assert job.status == "waiting_candidate_confirmation"
        assert job.progress == 55
        assert job.can_retry is False
        assert job.can_revise is True
        assert job.can_confirm_candidates is True
        assert collection.evidence[0]["evidence_id"] == "ev_0000000000000001"
        assert snapshot.source_execution_version == 0
        assert usage is not None
        payload = collection_snapshot_payload(
            source_execution_version=0,
            result={
                "workflow_version": collection.workflow_version,
                "topic_spec": collection.topic_spec,
                "plan": collection.plan,
                "raw_data": collection.raw_data,
                "evidence": collection.evidence,
                "tool_results": collection.tool_results,
                "search_queries_used": collection.search_queries_used,
            },
            collection_usage=collection.collection_usage,
        )
        assert canonical_hash(payload) == collection.content_hash


@pytest.mark.asyncio
async def test_snapshots_are_isolated_by_job_and_execution_version(session_factory):
    async with session_factory() as db:
        first_user = User(email="isolation-1@example.com", hashed_password="hashed")
        second_user = User(email="isolation-2@example.com", hashed_password="hashed")
        db.add_all([first_user, second_user])
        await db.commit()
    first_job = await create_job(session_factory, first_user.id)
    second_job = await create_job(session_factory, second_user.id)
    await persist_candidates(session_factory, first_job, [video_evidence("100", 1)])
    await persist_candidates(session_factory, second_job, [video_evidence("200", 2)])

    async with session_factory() as db:
        first = await db.get(AnalysisJob, first_job)
        first.status = "running"
        first.execution_version = 1
        await db.commit()
    await persist_candidates(session_factory, first_job, [video_evidence("300", 3)], execution_version=1)

    async with session_factory() as db:
        rows = list((await db.scalars(select(CollectionSnapshot).order_by(CollectionSnapshot.job_id, CollectionSnapshot.source_execution_version))).all())
        assert len(rows) == 3
        assert len({(row.job_id, row.source_execution_version) for row in rows}) == 3
        assert len({row.content_hash for row in rows}) == 3


@pytest.mark.asyncio
async def test_no_legal_candidate_finishes_partial_without_empty_waiting_state(session_factory):
    async with session_factory() as db:
        user = User(email="no-candidate@example.com", hashed_password="hashed")
        db.add(user)
        await db.commit()
    job_id = await create_job(session_factory, user.id)
    await persist_candidates(session_factory, job_id, [video_evidence(None, 1)])
    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        snapshot = await db.scalar(select(CandidateSnapshot).where(CandidateSnapshot.job_id == job_id))
        count = await db.scalar(select(func.count()).select_from(CandidateSnapshot).where(CandidateSnapshot.job_id == job_id))
        assert job.status == "partial"
        assert job.error_code == "CANDIDATE_EVIDENCE_INSUFFICIENT"
        assert job.can_confirm_candidates is False
        assert snapshot is not None
        assert count == 1


async def prepare_api_snapshot(client, factory, email="candidate-api@example.com"):
    owner_id = await register(client, email)
    job_id = await create_job(factory, owner_id)
    await persist_candidates(factory, job_id, [video_evidence("100", 1), video_evidence("200", 2)])
    response = await client.get(f"/jobs/{job_id}/candidates")
    assert response.status_code == 200
    return owner_id, job_id, response.json()


def decision_request(snapshot: dict, request_id: uuid.UUID | None = None, *, first="confirmed", second="excluded") -> dict:
    return {
        "request_id": str(request_id or uuid.uuid4()),
        "snapshot_id": snapshot["snapshot_id"],
        "decisions": [
            {"candidate_id": snapshot["candidates"][0]["candidate_id"], "decision": first, "reason": "匹配范围"},
            {"candidate_id": snapshot["candidates"][1]["candidate_id"], "decision": second},
        ],
    }


@pytest.mark.asyncio
async def test_candidate_get_is_owned_and_returns_limited_projection(api_client):
    client, factory, _ = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory)
    assert snapshot["can_submit"] is True
    assert snapshot["max_candidates"] == 8
    assert len(snapshot["candidates"]) == 2
    assert len(snapshot["candidates"][0]["evidence_links"]) == 1
    assert "raw_data" not in snapshot
    await client.post("/auth/logout")
    await register(client, "candidate-other@example.com")
    assert (await client.get(f"/jobs/{job_id}/candidates")).status_code == 404


@pytest.mark.asyncio
async def test_decision_validation_requires_all_unique_known_and_confirmed(api_client):
    client, factory, queue = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-validation@example.com")
    base = decision_request(snapshot)
    missing = await client.post(f"/jobs/{job_id}/candidates/decisions", json={**base, "decisions": base["decisions"][:1]})
    duplicate = await client.post(f"/jobs/{job_id}/candidates/decisions", json={**base, "request_id": str(uuid.uuid4()), "decisions": [base["decisions"][0], base["decisions"][0]]})
    unknown = await client.post(f"/jobs/{job_id}/candidates/decisions", json={**base, "request_id": str(uuid.uuid4()), "decisions": [{**base["decisions"][0], "candidate_id": deterministic_candidate_id("999")}, base["decisions"][1]]})
    no_confirmed = await client.post(f"/jobs/{job_id}/candidates/decisions", json=decision_request(snapshot, first="excluded", second="uncertain"))
    undecided = await client.post(f"/jobs/{job_id}/candidates/decisions", json={**base, "request_id": str(uuid.uuid4()), "decisions": [{**base["decisions"][0], "decision": "undecided"}, base["decisions"][1]]})
    assert [missing.status_code, duplicate.status_code, unknown.status_code, no_confirmed.status_code, undecided.status_code] == [422, 422, 422, 422, 422]
    assert queue.calls == []


@pytest.mark.asyncio
async def test_decision_submit_is_idempotent_conflict_safe_and_enqueues_once(api_client):
    client, factory, queue = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-idempotency@example.com")
    request_id = uuid.uuid4()
    payload = decision_request(snapshot, request_id)
    first = await client.post(f"/jobs/{job_id}/candidates/decisions", json=payload)
    duplicate = await client.post(f"/jobs/{job_id}/candidates/decisions", json=payload)
    conflict = await client.post(f"/jobs/{job_id}/candidates/decisions", json={**payload, "decisions": [{**payload["decisions"][0], "reason": "不同内容"}, payload["decisions"][1]]})
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["execution_version"] == duplicate.json()["execution_version"] == 1
    assert first.json()["status"] == "pending"
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "CANDIDATE_DECISION_CONFLICT"
    assert queue.calls == [(str(job_id), 1)]
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(CandidateDecisionBatch)) == 1
        assert await db.scalar(select(func.count()).select_from(CandidateSynthesisRun)) == 1


@pytest.mark.asyncio
async def test_enqueue_failure_preserves_dispatch_intent_for_reconciliation(api_client):
    client, factory, queue = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-enqueue@example.com")
    queue.fail = True
    payload = decision_request(snapshot)
    response = await client.post(f"/jobs/{job_id}/candidates/decisions", json=payload)
    assert response.status_code == 503
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.status == "pending"
        assert job.execution_version == 1
        assert job.arq_job_id is None
        assert job.dispatch_pending_at is not None
        assert job.error_code == "DISPATCH_PENDING"
    duplicate = await client.post(f"/jobs/{job_id}/candidates/decisions", json=payload)
    assert duplicate.status_code == 202
    assert len(queue.calls) == 1


@pytest.mark.asyncio
async def test_request_body_limit_rejects_large_payload_before_validation(api_client):
    client, factory, _ = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-body@example.com")
    response = await client.post(
        f"/jobs/{job_id}/candidates/decisions",
        content=b"x" * (16 * 1024 + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "REQUEST_BODY_TOO_LARGE"


@pytest.mark.asyncio
async def test_synthesis_restores_snapshot_and_filters_excluded_and_uncertain_evidence(api_client, monkeypatch):
    client, factory, _ = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-synthesis@example.com")
    confirmed_url = snapshot["candidates"][0]["evidence_links"][0]["source_url"]
    transcript = transcript_evidence(99, confirmed_url)
    async with factory() as db:
        collection = await db.scalar(select(CollectionSnapshot).where(CollectionSnapshot.job_id == job_id))
        collection.raw_data = list(collection.raw_data) + [transcript[0]]
        collection.evidence = list(collection.evidence) + [transcript[1]]
        result = {
            "workflow_version": collection.workflow_version,
            "topic_spec": collection.topic_spec,
            "plan": collection.plan,
            "raw_data": collection.raw_data,
            "evidence": collection.evidence,
            "tool_results": collection.tool_results,
            "search_queries_used": collection.search_queries_used,
        }
        payload = collection_snapshot_payload(source_execution_version=0, result=result, collection_usage=collection.collection_usage)
        collection.content_hash = canonical_hash(payload)
        candidate_snapshot = await db.scalar(select(CandidateSnapshot).where(CandidateSnapshot.job_id == job_id))
        candidates = extract_candidates(collection.evidence)
        candidate_snapshot.snapshot_hash = canonical_hash(candidate_snapshot_payload(
            source_execution_version=0,
            collection_snapshot_hash=collection.content_hash,
            topic=topic_summary(collection.topic_spec),
            candidates=candidates,
        ))
        await db.commit()
    latest = (await client.get(f"/jobs/{job_id}/candidates")).json()
    payload = decision_request(latest, first="confirmed", second="uncertain")
    assert (await client.post(f"/jobs/{job_id}/candidates/decisions", json=payload)).status_code == 202
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = "running"
        await db.commit()
    monkeypatch.setattr(worker, "async_session_factory", factory)
    state = await worker._load_synthesis_state(job_id, 1)
    selected_ids = {item["evidence_id"] for item in state["evidence"]}
    assert snapshot["candidates"][0]["source_evidence_ids"][0] in selected_ids
    assert snapshot["candidates"][1]["source_evidence_ids"][0] not in selected_ids
    assert transcript[1]["evidence_id"] in selected_ids
    assert snapshot["candidates"][1]["display_name"] not in str(state["raw_data"])
    assert state["candidate_boundary"]["uncertain_names"] == [snapshot["candidates"][1]["display_name"]]


@pytest.mark.asyncio
async def test_synthesis_worker_skips_brief_collection_search_and_asr(api_client, monkeypatch):
    client, factory, _ = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-no-recollect@example.com")
    assert (await client.post(f"/jobs/{job_id}/candidates/decisions", json=decision_request(snapshot))).status_code == 202
    monkeypatch.setattr(worker, "async_session_factory", factory)
    monkeypatch.setattr(worker, "ENABLE_CANDIDATE_CONFIRMATION", True)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("collection path must not run during synthesis")

    monkeypatch.setattr(worker, "validate_job_brief", forbidden)
    monkeypatch.setattr(worker, "_invoke_collection_graph", forbidden)
    monkeypatch.setattr(worker, "_invoke_graph", forbidden)
    monkeypatch.setattr(worker, "_collect_transcript_evidence", forbidden)
    captured = {}

    async def fake_synthesis(_job_id, _execution_version, state):
        captured["evidence_ids"] = [item["evidence_id"] for item in state["evidence"]]
        return {**state, "report_final": "# 报告", "analysis": {"claims": []}}

    async def fake_persist(_job_id, result):
        captured["boundary"] = result["candidate_boundary"]
        return uuid.uuid4()

    monkeypatch.setattr(worker, "_invoke_synthesis_graph", fake_synthesis)
    monkeypatch.setattr(worker, "_persist_result", fake_persist)
    await worker.run_analysis_job({"provider_semaphore": asyncio.Semaphore(1)}, str(job_id), 1)
    assert captured["evidence_ids"] == snapshot["candidates"][0]["source_evidence_ids"]
    assert captured["boundary"]["excluded_count"] == 1


@pytest.mark.asyncio
async def test_report_contains_confirmation_boundary_and_only_snapshot_evidence(api_client, monkeypatch):
    client, factory, _ = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-report@example.com")
    payload = decision_request(snapshot, first="confirmed", second="uncertain")
    assert (await client.post(f"/jobs/{job_id}/candidates/decisions", json=payload)).status_code == 202
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = "running"
        await db.commit()
    monkeypatch.setattr(worker, "async_session_factory", factory)
    state = await worker._load_synthesis_state(job_id, 1)
    evidence_id = state["evidence"][0]["evidence_id"]
    cost_tracker.reset()
    report_id = await worker._persist_result(job_id, {
        **state,
        "report_final": f"# 竞争账号分析\n\n已确认样本观察 [{evidence_id}]",
        "analysis": {"claims": [{
            "claim": "已确认样本提供了可观察内容",
            "claim_type": "observation",
            "evidence_ids": [evidence_id],
            "confidence": 0.8,
        }]},
        "_candidate_synthesis": True,
        "_expected_execution_version": 1,
    })
    async with factory() as db:
        report = await db.get(Report, report_id)
        evidence_rows = list((await db.scalars(select(EvidenceItem).where(EvidenceItem.report_id == report_id))).all())
        assert "候选来自系统" in report.content
        assert "用户确认不等于模型准确率" in report.content
        assert snapshot["candidates"][1]["display_name"] in report.content
        assert len(evidence_rows) == 1
        assert evidence_rows[0].evidence_id == evidence_id


@pytest.mark.asyncio
async def test_snapshot_hash_tampering_stops_synthesis(api_client, monkeypatch):
    client, factory, _ = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-tamper@example.com")
    assert (await client.post(f"/jobs/{job_id}/candidates/decisions", json=decision_request(snapshot))).status_code == 202
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = "running"
        collection = await db.scalar(select(CollectionSnapshot).where(CollectionSnapshot.job_id == job_id))
        collection.plan = ["被篡改"]
        await db.commit()
    monkeypatch.setattr(worker, "async_session_factory", factory)
    with pytest.raises(ValueError, match="collection hash mismatch"):
        await worker._load_synthesis_state(job_id, 1)


@pytest.mark.asyncio
async def test_manual_retry_reuses_decisions_and_snapshot_without_recollection(api_client):
    client, factory, queue = api_client
    _, job_id, snapshot = await prepare_api_snapshot(client, factory, "candidate-retry@example.com")
    assert (await client.post(f"/jobs/{job_id}/candidates/decisions", json=decision_request(snapshot))).status_code == 202
    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        job.status = "failed"
        job.error_code = "WORKER_FAILED"
        job.error_message = "失败"
        await db.commit()
    retried = await client.post(f"/jobs/{job_id}/retry")
    assert retried.status_code == 202
    assert retried.json()["execution_version"] == 2
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(CollectionSnapshot).where(CollectionSnapshot.job_id == job_id)) == 1
        assert await db.scalar(select(func.count()).select_from(CandidateDecisionBatch).where(CandidateDecisionBatch.job_id == job_id)) == 1
        assert await db.scalar(select(func.count()).select_from(CandidateSynthesisRun).where(CandidateSynthesisRun.job_id == job_id)) == 2
    assert queue.calls == [(str(job_id), 1), (str(job_id), 2)]


@pytest.mark.asyncio
async def test_cancel_waiting_confirmation_preserves_cancelled_state_and_capabilities(api_client):
    client, factory, _ = api_client
    _, job_id, _ = await prepare_api_snapshot(client, factory, "candidate-cancel@example.com")
    response = await client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["can_retry"] is True
    assert response.json()["can_revise"] is True
    assert response.json()["can_confirm_candidates"] is False


def test_phase_graphs_reuse_only_expected_core_nodes():
    collection_nodes = set(worker.collection_graph.get_graph().nodes)
    synthesis_nodes = set(worker.synthesis_graph.get_graph().nodes)
    assert {"entry", "planner_v2", "researcher_v2", "evidence_gate"}.issubset(collection_nodes)
    assert "analyst" not in collection_nodes and "writer" not in collection_nodes
    assert {"analyst", "writer"}.issubset(synthesis_nodes)
    assert "planner_v2" not in synthesis_nodes and "researcher_v2" not in synthesis_nodes


def test_frontend_consumes_server_capability_and_accessible_candidate_controls():
    page = Path("frontend/src/app/jobs/[id]/page.tsx").read_text(encoding="utf-8")
    component = Path("frontend/src/components/CandidateConfirmation.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "job.can_confirm_candidates" in page
    assert "<fieldset" in component and "<legend" in component
    assert 'role="alert"' in component
    assert "confirmedCount < 1" in component
    assert "decision: CandidateDecision" in api
    assert sum(line.strip().startswith("ENABLE_CANDIDATE_CONFIRMATION:") for line in compose.splitlines()) == 2
    assert "ENABLE_CANDIDATE_CONFIRMATION=false" in env_example
