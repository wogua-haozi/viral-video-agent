import asyncio
import logging
import uuid
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from arq import Retry, cron
from arq.connections import RedisSettings
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, TimeoutError as DatabaseTimeoutError

from src.agents.analyst import analyst_node
from src.agents.writer import writer_node
from src.api.errors import ERROR_MESSAGES
from src.briefing.service import validate_job_brief
from src.candidates.schemas import (
    CANDIDATE_SNAPSHOT_VERSION,
    COLLECTION_SNAPSHOT_VERSION,
    CandidateProjection,
    CandidateTopicSummary,
)
from src.candidates.service import (
    candidate_snapshot_payload,
    canonical_hash,
    collection_snapshot_payload,
    decision_payload_hash,
    extract_candidates,
    topic_summary,
)
from src.config import (
    ASR_MAX_VIDEOS,
    ASR_MAX_VIDEO_SECONDS,
    DEFAULT_LLM_MODEL_ID,
    DEFAULT_LLM_PROVIDER,
    ENABLE_CANDIDATE_CONFIRMATION,
    ENABLE_INTERACTIVE_BRIEF,
    GRAPH_VERSION,
    JOB_MAX_RETRIES,
    JOB_TIMEOUT_SECONDS,
    REDIS_URL,
    WORKER_MAX_JOBS,
)
from src.db.models import (
    AnalysisJob,
    CandidateAccount,
    CandidateSnapshot,
    CollectionSnapshot,
    EvidenceItem,
    JobEvent,
    Report,
)
from src.db.session import async_session_factory
from src.dispatch import reconcile_pending_dispatches
from src.gateway.cost_tracker import cost_tracker
from src.gateway.model_bootstrap import configure_optional_model_routes
from src.graph.builder import build_graph
from src.graph.v2 import build_collection_graph_v2, build_synthesis_graph_v2, evidence_gate_node, stable_evidence_id
from src.reporting.validation import finalize_report, validate_claims, validate_report_references
from src.repositories import CandidateRepository, JobRepository, UsageRepository
from src.tools.transcript import TranscriptError, get_transcript
from src.utils.asr_usage_tracker import ASRUsageState, asr_usage_tracker
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker

graph = build_graph()
collection_graph = build_collection_graph_v2()
synthesis_graph = build_synthesis_graph_v2()
logger = logging.getLogger(__name__)
WORKER_LEASE_SECONDS = 90
WORKER_HEARTBEAT_SECONDS = 5
WORKER_HEARTBEAT_STOP_GRACE_SECONDS = 5


class _JobStopped(asyncio.CancelledError):
    """The owner cancelled the job, or this execution no longer owns it."""


@dataclass
class _Execution:
    job_id: uuid.UUID
    version: int
    token: str
    cost_context: Context
    brief_baseline: dict
    phase: str = "analysis"
    asr_usage: ASRUsageState = field(default_factory=ASRUsageState)

    @property
    def asr_seconds(self) -> float:
        return self.asr_usage.asr_seconds

    def cost(self, job: AnalysisJob, *, final: bool = False) -> dict:
        cost = self.cost_context.run(cost_tracker.get_summary)
        if self.phase == "brief":
            # BriefValidator records completed calls in interaction_usage. Do
            # not also checkpoint those calls as graph usage while it runs.
            if not final:
                return {}
            interaction = job.interaction_usage or {}
            for field, interaction_field in (
                ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"),
                ("total_cost", "estimated_cost"),
            ):
                recorded = max(0, interaction.get(interaction_field, 0) - self.brief_baseline.get(interaction_field, 0))
                cost[field] = max(0, cost[field] - recorded)
        return cost


_execution: ContextVar[_Execution | None] = ContextVar("worker_execution", default=None)


def _owns_execution(job: AnalysisJob, execution: _Execution | None = None) -> bool:
    execution = execution or _execution.get()
    return execution is None or (
        job.id == execution.job_id
        and job.execution_version == execution.version
        and job.worker_token == execution.token
    )


async def _settle_usage(db, job: AnalysisJob, *, phase: str, asr_seconds: float = 0, final: bool = False):
    execution = _execution.get()
    attempt_id = execution.token if execution else f"legacy:{job.execution_version}:{phase}"
    cost = execution.cost(job, final=final) if execution else cost_tracker.get_summary()
    # A result may contain cached audio durations. Owned attempts use the
    # unified completed-call tracker, including direct and remote tool calls.
    seconds = execution.asr_seconds if execution else asr_seconds
    return await UsageRepository(db).settle_attempt(job, attempt_id, cost, seconds)


async def _cancel_and_wait(*tasks: asyncio.Task, grace_seconds: float = 0) -> None:
    cancelled = False
    if grace_seconds and any(not task.done() for task in tasks):
        grace = asyncio.create_task(asyncio.wait(tasks, timeout=grace_seconds))
        while not grace.done():
            try:
                await asyncio.shield(grace)
            except asyncio.CancelledError:
                cancelled = True
    for task in tasks:
        if not task.done():
            task.cancel()
    # Retrieve exceptions as well as await cleanup; no detached graph or
    # heartbeat may survive its owning execution. A second shutdown signal must
    # not interrupt a child that is stopping its subprocesses.
    cleanup = asyncio.gather(*tasks, return_exceptions=True)
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError


def _select_transcript_candidates(raw_data: list[dict], limit: int, max_seconds: int = ASR_MAX_VIDEO_SECONDS) -> list[str]:
    candidates: list[str] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("source_url")
        duration = item.get("duration")
        if duration and float(duration) > max_seconds:
            continue
        if url and "bilibili.com" in url and url not in candidates:
            candidates.append(url)
    return candidates[:limit]


async def _publish_event(job_id: uuid.UUID, event_type: str, message: str, progress: int, level: str = "info", redis=None) -> None:
    if redis is None:
        return
    try:
        await redis.hset(f"job:{job_id}:status", mapping={"status": event_type, "message": message, "progress": progress})
        await redis.expire(f"job:{job_id}:status", 86400)
        await redis.xadd(f"job:{job_id}:events", {"event_type": event_type, "message": message, "progress": progress, "level": level}, maxlen=200)
        await redis.expire(f"job:{job_id}:events", 86400)
    except Exception:
        # PostgreSQL events are authoritative. A cache outage must not repeat
        # paid analysis after its report has already committed.
        logger.warning("Redis event projection failed for job %s (%s)", job_id, event_type, exc_info=True)


async def _event(job_id: uuid.UUID, event_type: str, message: str, progress: int, level: str = "info", redis=None) -> None:
    async with async_session_factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        if not job or not _owns_execution(job) or job.status == "cancelled":
            raise _JobStopped
        job.progress = progress
        db.add(JobEvent(job_id=job_id, event_type=event_type, message=message, progress=progress, level=level))
        await db.commit()
    await _publish_event(job_id, event_type, message, progress, level, redis)


def _initial_state(user_id: uuid.UUID, query: str, platforms: list[str], topic_spec: dict | None = None) -> dict:
    return {
        "user_id": str(user_id),
        "user_request": query,
        "platforms": platforms,
        "topic_spec": topic_spec or {},
        "task_complete": False,
        "data_sufficient": False,
        "analysis_confidence": 0.0,
        "analysis_iterations": 0,
        "report_final": "",
        "report_draft": "",
        "report_revision_count": 0,
    }


async def _invoke_compiled_graph(compiled_graph, job_id: uuid.UUID, execution_version: int, state: dict) -> dict:
    execution = _execution.get()
    thread_id = f"{job_id}:{execution_version}"
    if execution:
        # Automatic retries retain execution_version, but must not append new
        # evidence to an abandoned attempt's in-memory graph checkpoint.
        thread_id += f":{execution.token}"
    task = asyncio.create_task(
        compiled_graph.ainvoke(
            state,
            config={"configurable": {"thread_id": thread_id}},
        )
    )
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=1.5)
            if done:
                return await task
            async with async_session_factory() as db:
                current = await JobRepository(db).get(job_id)
                if not current or current.status != "running" or current.execution_version != execution_version or not _owns_execution(current):
                    raise _JobStopped
    finally:
        await _cancel_and_wait(task)


async def _invoke_graph(job_id: uuid.UUID, user_id: uuid.UUID, query: str, platforms: list[str], topic_spec: dict | None = None, execution_version: int = 0) -> dict:
    return await _invoke_compiled_graph(
        graph,
        job_id,
        execution_version,
        _initial_state(user_id, query, platforms, topic_spec),
    )


async def _invoke_collection_graph(job_id: uuid.UUID, user_id: uuid.UUID, query: str, platforms: list[str], topic_spec: dict | None = None, execution_version: int = 0) -> dict:
    return await _invoke_compiled_graph(
        collection_graph,
        job_id,
        execution_version,
        _initial_state(user_id, query, platforms, topic_spec),
    )


async def _invoke_synthesis_graph(job_id: uuid.UUID, execution_version: int, state: dict) -> dict:
    return await _invoke_compiled_graph(synthesis_graph, job_id, execution_version, state)


async def _collect_transcript_evidence(result: dict, job_id: uuid.UUID, redis=None) -> dict:
    candidates = _select_transcript_candidates(result.get("raw_data", []), ASR_MAX_VIDEOS, ASR_MAX_VIDEO_SECONDS)
    transcript_data, transcript_evidence, total_seconds = [], [], 0.0
    for index, url in enumerate(candidates, 1):
        await _event(job_id, "transcribing", f"正在转写本次样本中的公开视频 {index}/{len(candidates)}。", 45 + index * 4, redis=redis)
        try:
            transcript = await get_transcript(url)
        except TranscriptError:
            continue
        if not transcript or not transcript.get("text"):
            continue
        evidence_id = stable_evidence_id("get_transcript", {"url": url})
        total_seconds += float(transcript.get("asr_seconds", 0))
        transcript_data.append({
            "title": f"视频转写 {index}",
            "source_url": url,
            "text": transcript["text"],
            "segments": transcript.get("segments", []),
            "_evidence_id": evidence_id,
        })
        transcript_evidence.append({
            "evidence_id": evidence_id,
            "tool": "get_transcript",
            "source_type": "transcript",
            "title": f"视频转写 {index}",
            "source_url": url,
            "platform": "bilibili",
            "fetched_at": transcript["fetched_at"],
            "raw_data": {
                "provider": transcript["provider"],
                "model": transcript["model"],
                "audio_hash": transcript["audio_hash"],
            },
            "summary": transcript["text"][:300],
            "data_fields": {},
            "transcript_segment": {
                "text": transcript["text"],
                "segments": transcript.get("segments", []),
            },
        })
    if not transcript_data:
        await _event(job_id, "analyzing", "ASR不可用或转写失败，已降级为元数据分析。", 68, "warning", redis)
        result["asr_seconds"] = 0
        return result
    result["raw_data"] = result.get("raw_data", []) + transcript_data
    result["evidence"] = result.get("evidence", []) + transcript_evidence
    result["asr_seconds"] = total_seconds
    return result


async def _enrich_deep_analysis(result: dict, job_id: uuid.UUID, redis=None) -> dict:
    evidence_before = len(result.get("evidence", []))
    result = await _collect_transcript_evidence(result, job_id, redis)
    if len(result.get("evidence", [])) == evidence_before:
        return result
    state = {
        **result,
        "analysis": {},
        "analysis_iterations": 0,
        "analysis_confidence": 0.0,
        "report_draft": "",
        "report_final": "",
        "report_revision_count": 0,
    }
    await _event(job_id, "analyzing", "正在分析口播、脚本结构与开头钩子。", 70, redis=redis)
    state.update(await analyst_node(state))
    state.update(await writer_node(state))
    state.update(await writer_node(state))
    return state


def _error_code(exc: Exception) -> tuple[str, bool]:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "candidate_snapshot_invalid" in message:
        return "CANDIDATE_SNAPSHOT_INVALID", False
    if "429" in message or "rate" in name:
        return "LLM_RATE_LIMITED", True
    if "401" in message or "403" in message or "authentication" in name:
        return "LLM_AUTH_FAILED", False
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in name:
        return "LLM_TIMEOUT", True
    if "bilibili" in message:
        return "BILIBILI_UNAVAILABLE", True
    return "WORKER_FAILED", True


async def _persist_collection_snapshot(job_id: uuid.UUID, execution_version: int, result: dict) -> dict:
    # Candidate identity is a separate contract from sample sufficiency. Never
    # turn a collection failure into an analyzable snapshot merely because its
    # tool output contains an account ID.
    if not result.get("termination_reason"):
        result = {**result, **evidence_gate_node(result)}
    if result.get("termination_reason") or not result.get("data_sufficient"):
        report_id = await _persist_result(job_id, {
            **result,
            "_expected_execution_version": execution_version,
        })
        return {"report_id": str(report_id), "candidate_count": 0}

    async with async_session_factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        if not job or job.status != "running" or job.execution_version != execution_version or not _owns_execution(job):
            raise _JobStopped

        usage = await _settle_usage(db, job, phase="collection", asr_seconds=float(result.get("asr_seconds", 0)))
        collection_usage = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "estimated_cost": usage.estimated_cost,
            "asr_seconds": usage.asr_seconds,
        }
        payload = collection_snapshot_payload(
            source_execution_version=execution_version,
            result=result,
            collection_usage=collection_usage,
        )
        content_hash = canonical_hash(payload)
        candidates = extract_candidates(result.get("evidence", []))
        summary = topic_summary(result.get("topic_spec"), job.query)
        candidate_payload = candidate_snapshot_payload(
            source_execution_version=execution_version,
            collection_snapshot_hash=content_hash,
            topic=summary,
            candidates=candidates,
        )
        snapshot_hash = canonical_hash(candidate_payload)

        existing = await db.scalar(
            select(CollectionSnapshot).where(
                CollectionSnapshot.job_id == job.id,
                CollectionSnapshot.source_execution_version == execution_version,
            )
        )
        if existing:
            if existing.content_hash != content_hash:
                raise ValueError("CANDIDATE_SNAPSHOT_INVALID: collection snapshot conflict")
            return {"snapshot_id": str(existing.id), "candidate_count": len(candidates)}

        collection_snapshot = CollectionSnapshot(
            job_id=job.id,
            source_execution_version=execution_version,
            schema_version=COLLECTION_SNAPSHOT_VERSION,
            content_hash=content_hash,
            workflow_version=str(result.get("workflow_version") or "v2"),
            topic_spec=result.get("topic_spec") or {},
            plan=result.get("plan") or [],
            raw_data=result.get("raw_data") or [],
            evidence=result.get("evidence") or [],
            tool_results=result.get("tool_results") or [],
            search_queries_used=result.get("search_queries_used") or [],
            collection_usage=collection_usage,
        )
        db.add(collection_snapshot)
        await db.flush()
        candidate_snapshot = CandidateSnapshot(
            collection_snapshot_id=collection_snapshot.id,
            job_id=job.id,
            source_execution_version=execution_version,
            schema_version=CANDIDATE_SNAPSHOT_VERSION,
            snapshot_hash=snapshot_hash,
            topic_summary=summary.model_dump(mode="json"),
            max_candidates=8,
        )
        db.add(candidate_snapshot)
        await db.flush()
        for sort_order, item in enumerate(candidates):
            values = item.model_dump(mode="json")
            values.pop("decision")
            db.add(CandidateAccount(snapshot_id=candidate_snapshot.id, sort_order=sort_order, **values))

        if candidates:
            job.status = "waiting_candidate_confirmation"
            job.progress = 55
            job.error_code = None
            job.error_message = None
            db.add(JobEvent(
                job_id=job.id,
                event_type="waiting_candidate_confirmation",
                message=f"已从本次 Evidence 快照提取 {len(candidates)} 个候选账号，等待逐项确认。",
                progress=55,
                level="info",
            ))
        else:
            job.status = "partial"
            job.progress = 100
            job.completed_at = datetime.now(timezone.utc)
            job.error_code = "CANDIDATE_EVIDENCE_INSUFFICIENT"
            job.error_message = ERROR_MESSAGES["CANDIDATE_EVIDENCE_INSUFFICIENT"]
            db.add(JobEvent(
                job_id=job.id,
                event_type="partial",
                message=job.error_message,
                progress=100,
                level="warning",
            ))
        await db.commit()
        return {"snapshot_id": str(candidate_snapshot.id), "candidate_count": len(candidates)}


def _candidate_projection(item: CandidateAccount) -> CandidateProjection:
    return CandidateProjection(
        candidate_id=item.candidate_id,
        platform=item.platform,
        platform_account_id=item.platform_account_id,
        display_name=item.display_name,
        profile_url=item.profile_url,
        source_evidence_ids=list(item.source_evidence_ids),
        matched_video_count=item.matched_video_count,
        sample_titles=list(item.sample_titles),
        evidence_links=list(item.evidence_links),
        why_surfaced=list(item.why_surfaced),
        identity_confidence=item.identity_confidence,
        decision="undecided",
    )


async def _load_synthesis_state(job_id: uuid.UUID, execution_version: int) -> dict:
    async with async_session_factory() as db:
        job = await JobRepository(db).get(job_id)
        run = await CandidateRepository(db).synthesis_run(job_id, execution_version)
        if not job or job.status != "running" or job.execution_version != execution_version or not _owns_execution(job) or not run:
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: synthesis run not found")
        batch = run.decision_batch
        snapshot = batch.snapshot
        collection = snapshot.collection_snapshot
        if (
            snapshot.job_id != job.id
            or collection.job_id != job.id
            or snapshot.source_execution_version + 1 > execution_version
            or snapshot.collection_snapshot_id != collection.id
        ):
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: ownership or execution mismatch")

        collection_result = {
            "workflow_version": collection.workflow_version,
            "topic_spec": collection.topic_spec,
            "plan": collection.plan,
            "raw_data": collection.raw_data,
            "evidence": collection.evidence,
            "tool_results": collection.tool_results,
            "search_queries_used": collection.search_queries_used,
        }
        collection_payload = collection_snapshot_payload(
            source_execution_version=collection.source_execution_version,
            result=collection_result,
            collection_usage=collection.collection_usage,
        )
        if canonical_hash(collection_payload) != collection.content_hash:
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: collection hash mismatch")

        ordered_candidates = sorted(snapshot.candidates, key=lambda item: item.sort_order)
        projections = [_candidate_projection(item) for item in ordered_candidates]
        summary = CandidateTopicSummary.model_validate(snapshot.topic_summary)
        candidate_payload = candidate_snapshot_payload(
            source_execution_version=snapshot.source_execution_version,
            collection_snapshot_hash=collection.content_hash,
            topic=summary,
            candidates=projections,
            max_candidates=snapshot.max_candidates,
        )
        if canonical_hash(candidate_payload) != snapshot.snapshot_hash:
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: candidate hash mismatch")

        candidates_by_row_id = {item.id: item for item in ordered_candidates}
        if len(batch.decisions) != len(ordered_candidates):
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: incomplete decisions")
        decisions = []
        confirmed = []
        uncertain = []
        excluded_count = 0
        for decision in batch.decisions:
            candidate = candidates_by_row_id.get(decision.candidate_account_id)
            if not candidate or decision.decision not in {"confirmed", "excluded", "uncertain"}:
                raise ValueError("CANDIDATE_SNAPSHOT_INVALID: unknown candidate decision")
            decisions.append({
                "candidate_id": candidate.candidate_id,
                "decision": decision.decision,
                "reason": decision.reason,
            })
            if decision.decision == "confirmed":
                confirmed.append(candidate)
            elif decision.decision == "uncertain":
                uncertain.append(candidate)
            else:
                excluded_count += 1
        if not confirmed:
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: no confirmed candidate")
        if decision_payload_hash(str(snapshot.id), decisions) != batch.payload_hash:
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: decision hash mismatch")

        evidence_by_id = {
            item.get("evidence_id"): item
            for item in collection.evidence
            if isinstance(item, dict) and item.get("evidence_id")
        }
        confirmed_ids = {
            evidence_id
            for candidate in confirmed
            for evidence_id in candidate.source_evidence_ids
        }
        if not confirmed_ids or not confirmed_ids.issubset(evidence_by_id):
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: candidate evidence missing")
        confirmed_urls = {
            evidence_by_id[evidence_id].get("source_url")
            for evidence_id in confirmed_ids
            if evidence_by_id[evidence_id].get("source_url")
        }
        selected_evidence = []
        for item in collection.evidence:
            if not isinstance(item, dict):
                continue
            if item.get("evidence_id") in confirmed_ids:
                selected_evidence.append(item)
            elif item.get("tool") == "get_transcript" and item.get("source_url") in confirmed_urls:
                selected_evidence.append(item)
        selected_ids = {item["evidence_id"] for item in selected_evidence}
        selected_raw_data = [
            item
            for item in collection.raw_data
            if isinstance(item, dict) and item.get("_evidence_id") in selected_ids
        ]
        if not selected_raw_data or not selected_evidence:
            raise ValueError("CANDIDATE_SNAPSHOT_INVALID: filtered evidence empty")

        confirmed_names = [item.display_name or "未提供账号名称" for item in confirmed]
        state = _initial_state(job.user_id, job.query, job.platforms, collection.topic_spec)
        state.update({
            "workflow_version": collection.workflow_version,
            "plan": collection.plan,
            "raw_data": selected_raw_data,
            "evidence": selected_evidence,
            "tool_results": collection.tool_results,
            "search_queries_used": collection.search_queries_used,
            "user_request": (
                f"{job.query}\n\n用户已确认本次只分析以下候选账号："
                + "、".join(confirmed_names)
                + "。不得扩展到其他账号。"
            ),
            "candidate_boundary": {
                "snapshot_id": str(snapshot.id),
                "snapshot_hash": snapshot.snapshot_hash,
                "source_execution_version": snapshot.source_execution_version,
                "confirmed_names": confirmed_names,
                "confirmed_candidate_ids": [item.candidate_id for item in confirmed],
                "uncertain_names": [item.display_name or "未提供账号名称" for item in uncertain],
                "excluded_count": excluded_count,
            },
        })
        # Selecting accounts can reduce a previously sufficient collection
        # below the configured sample minimum. Recheck the selected snapshot
        # without searching again or invoking any paid tool.
        state.update(evidence_gate_node(state))
        return state


def _candidate_boundary_markdown(boundary: dict | None) -> str:
    if not boundary:
        return ""
    confirmed = "、".join(boundary.get("confirmed_names") or []) or "无"
    uncertain = "、".join(boundary.get("uncertain_names") or []) or "无"
    return (
        "\n\n## 用户确认边界\n\n"
        f"- **纳入分析**：{confirmed}\n"
        f"- **未纳入或待确认范围**：{uncertain}\n"
        f"- **已排除候选**：{int(boundary.get('excluded_count', 0))} 个；未进入正常竞品结论。\n"
        "- 候选来自系统对本次公开 Evidence 快照的确定性提取，账号是否纳入由用户逐项确认。\n"
        "- 结论只适用于本次公开 Evidence 快照；用户确认不等于模型准确率，也不代表市场份额、全站排名、长期增长或完整行业覆盖。"
    )


def _parse_fetched_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    normalized = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


async def _persist_result(job_id: uuid.UUID, result: dict) -> uuid.UUID:
    evidence = result.get("evidence", [])
    claims = result.get("analysis", {}).get("claims", [])
    partial_without_analysis = bool(result.get("report_final")) and result.get("termination_reason") in {
        "insufficient_evidence", "tool_unavailable", "unsupported_platform", "invalid_topic_spec",
    }
    valid, reason = validate_claims(claims, evidence, allow_empty=partial_without_analysis)
    if not valid:
        raise ValueError(f"REPORT_VALIDATION_FAILED: {reason}")
    report_source = result.get("report_final", "") + _candidate_boundary_markdown(result.get("candidate_boundary"))
    content = finalize_report(report_source, claims, evidence)
    valid, reason = validate_report_references(content, evidence)
    if not valid:
        raise ValueError(f"REPORT_VALIDATION_FAILED: {reason}")
    trace = trace_tracker.get_summary()
    status = "completed" if result.get("report_final") and not result.get("termination_reason") else "partial"
    expected_execution_version = result.get("_expected_execution_version")
    async with async_session_factory() as db:
        repo = JobRepository(db)
        job = await repo.get_for_update(job_id)
        if (
            not job
            or job.status == "cancelled"
            or (expected_execution_version is not None and job.execution_version != expected_execution_version)
            or not _owns_execution(job)
        ):
            raise _JobStopped
        execution_version = job.execution_version
        existing = next((report for report in job.reports if report.model_info.get("execution_version", execution_version) == execution_version), None)
        if existing:
            return existing.id
        if job.status != "running":
            raise _JobStopped
        model_info = {
            "provider": DEFAULT_LLM_PROVIDER,
            "model": DEFAULT_LLM_MODEL_ID,
            "workflow": result.get("workflow_version", "v2"),
            "trace": trace,
            "fallback": fallback_counter.get_summary(),
            "execution_version": execution_version,
        }
        boundary = result.get("candidate_boundary")
        if boundary:
            model_info["candidate_confirmation"] = {
                "snapshot_id": boundary["snapshot_id"],
                "snapshot_hash": boundary["snapshot_hash"],
                "source_execution_version": boundary["source_execution_version"],
                "confirmed_candidate_ids": boundary["confirmed_candidate_ids"],
            }
        report = Report(
            job_id=job.id,
            user_id=job.user_id,
            title=job.query[:300],
            content=content,
            structured_claims=claims,
            status=status,
            model_info=model_info,
        )
        db.add(report)
        await db.flush()
        for item in evidence:
            db.add(EvidenceItem(
                report_id=report.id,
                job_id=job.id,
                evidence_id=item["evidence_id"],
                tool=item.get("tool", "unknown"),
                source_type=item.get("source_type", "tool_result"),
                title=item.get("title", "Evidence"),
                source_url=item.get("source_url"),
                platform=item.get("platform", "bilibili"),
                fetched_at=_parse_fetched_at(item["fetched_at"]),
                raw_data=item.get("raw_data", {}),
                summary=item.get("summary"),
                data_fields=item.get("data_fields", {}),
                transcript_segment=item.get("transcript_segment"),
            ))

        await _settle_usage(db, job, phase="report", asr_seconds=float(result.get("asr_seconds", 0)))
        job.status, job.progress, job.completed_at = status, 100, datetime.now(timezone.utc)
        if status == "partial":
            job.error_code, job.error_message = "EVIDENCE_INSUFFICIENT", ERROR_MESSAGES["EVIDENCE_INSUFFICIENT"]
        else:
            job.error_code = job.error_message = None
        db.add(JobEvent(
            job_id=job.id,
            event_type=status,
            message="报告已生成。" if status == "completed" else "已保存可用的部分结果。",
            progress=100,
            level="info",
        ))
        await db.commit()
        return report.id


async def _claim_job_once(
    job_id: uuid.UUID, expected_version: int | None, token: str, arq_job_id: str | None = None,
):
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        filters = [
            AnalysisJob.id == job_id,
            (AnalysisJob.status == "pending") | (
                (AnalysisJob.status == "running") & (AnalysisJob.worker_token == token)
            ),
        ]
        if expected_version is not None:
            filters.append(AnalysisJob.execution_version == int(expected_version))
        claimed = await db.execute(
            update(AnalysisJob)
            .where(*filters)
            .values(
                status="running", started_at=now, completed_at=None,
                error_code=None, error_message=None, dispatch_pending_at=None,
                # A fast claim can precede the API's enqueue acknowledgement.
                # Keep the real delivery identity under the same version/token
                # fence; calls without Arq context must not erase an existing ID.
                arq_job_id=arq_job_id if arq_job_id is not None else AnalysisJob.arq_job_id,
                worker_token=token,
                worker_lease_expires_at=now + timedelta(seconds=WORKER_LEASE_SECONDS),
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            return None
        job = await JobRepository(db).get_for_update(job_id)
        synthesis_run = (
            await CandidateRepository(db).synthesis_run(job.id, job.execution_version)
            if ENABLE_CANDIDATE_CONFIRMATION else None
        )
        await db.commit()
        return job, synthesis_run is not None, token


async def _claim_job(job_id: uuid.UUID, expected_version: int | None, arq_job_id: str | None = None):
    # Reuse the token if COMMIT succeeded but its acknowledgement was lost.
    # A retry may reclaim only its own running row, never another worker's.
    token = str(uuid.uuid4())
    for attempt in range(3):
        try:
            return await _claim_job_once(job_id, expected_version, token, arq_job_id)
        except (DBAPIError, DatabaseTimeoutError, ConnectionError, TimeoutError, asyncio.TimeoutError) as exc:
            # asyncpg connection setup can propagate native socket/timeout
            # exceptions without wrapping them in SQLAlchemy's DBAPIError.
            transient = isinstance(
                exc, (OperationalError, InterfaceError, DatabaseTimeoutError, ConnectionError, TimeoutError, asyncio.TimeoutError)
            ) or exc.connection_invalidated
            if not transient or attempt == 2:
                raise
            logger.warning("Job %s claim interrupted (%s); retrying.", job_id, type(exc).__name__)
            await asyncio.sleep(0.5 * 2 ** attempt)


async def _heartbeat(execution: _Execution, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    while True:
        try:
            await asyncio.wait_for(stop.wait(), WORKER_HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            pass
        else:
            return
        async with async_session_factory() as db:
            # CAS also supplies SQLite's write lock; a stale worker must never
            # extend the lease belonging to its replacement.
            renewed = await db.execute(
                update(AnalysisJob)
                .where(
                    AnalysisJob.id == execution.job_id,
                    AnalysisJob.execution_version == execution.version,
                    AnalysisJob.worker_token == execution.token,
                    AnalysisJob.status == "running",
                )
                .values(worker_lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=WORKER_LEASE_SECONDS))
                .execution_options(synchronize_session=False)
            )
            job = await JobRepository(db).get_for_update(execution.job_id)
            if renewed.rowcount != 1:
                terminal = job is not None and _owns_execution(job, execution) and job.status in {
                    "waiting_user", "waiting_candidate_confirmation", "completed", "partial",
                }
                await db.rollback()
                if terminal:
                    return
                raise _JobStopped
            await _settle_usage(db, job, phase="heartbeat")
            await db.commit()


async def _supervise(coroutine, execution: _Execution):
    stop_heartbeat = asyncio.Event()
    work = asyncio.create_task(coroutine)
    heartbeat = asyncio.create_task(_heartbeat(execution, stop_heartbeat))
    try:
        done, _ = await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return await work
        await heartbeat
        # Keep cancellation ownership here, so the finally block sends a
        # single cancel and then waits for graph/transcript cleanup.
        return await asyncio.shield(work)
    finally:
        # Do not normally cancel a DB driver between fetching and closing its
        # cursor. Let the in-flight checkpoint release its transaction before
        # final settlement, with a bounded grace period inside Arq's margin.
        stop_heartbeat.set()
        try:
            await _cancel_and_wait(work)
        finally:
            await _cancel_and_wait(heartbeat, grace_seconds=WORKER_HEARTBEAT_STOP_GRACE_SECONDS)


async def _finish_attempt(execution: _Execution, *, interrupted: bool = False, failure: tuple[str, bool] | None = None) -> tuple[bool, int | None]:
    """Settle once per token; never change a replacement execution's state."""
    async with async_session_factory() as db:
        job = await JobRepository(db).get_for_update(execution.job_id)
        if not job:
            return False, None
        await _settle_usage(db, job, phase="final", final=True)
        owns = _owns_execution(job, execution)
        interrupted_running = owns and job.status == "running"
        retry_delay = None
        if owns:
            if job.status == "running" and (interrupted or failure):
                code, retryable = failure or ("WORKER_FAILED", True)
                if retryable and job.retry_count < JOB_MAX_RETRIES:
                    job.retry_count += 1
                    job.status = "pending"
                    # Arq retains this execution's queue identity when Retry or
                    # infrastructure cancellation propagates to the worker.
                    if job.arq_job_id is None:
                        # Legacy/direct invocations may have no Arq context.
                        # Keep a durable intent so they cannot miss both scans.
                        job.dispatch_pending_at = datetime.now(timezone.utc)
                    retry_delay = 2 ** job.retry_count * 5
                    db.add(JobEvent(
                        job_id=job.id, event_type="queued", progress=job.progress, level="warning",
                        message=("Worker 执行中断，已保存用量并等待恢复。" if interrupted else f"临时故障，{retry_delay} 秒后自动重试。"),
                    ))
                else:
                    job.status = "failed"
                    job.completed_at = datetime.now(timezone.utc)
                    job.error_code = code
                    job.error_message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["WORKER_FAILED"])
                    db.add(JobEvent(job_id=job.id, event_type="failed", message=job.error_message, progress=job.progress, level="error"))
            elif job.status == "running":
                # All successful paths end in a report or a durable waiting
                # state. Treat an accidental early return as a visible failure.
                job.status = "failed"
                job.error_code = "WORKER_FAILED"
                job.error_message = ERROR_MESSAGES["WORKER_FAILED"]
                job.completed_at = datetime.now(timezone.utc)
                db.add(JobEvent(job_id=job.id, event_type="failed", message=job.error_message, progress=job.progress, level="error"))
            job.worker_token = None
            job.worker_lease_expires_at = None
        await db.commit()
        return interrupted_running, retry_delay


async def _execute_job(ctx: dict, job: AnalysisJob, synthesis_run: bool, execution: _Execution) -> None:
    job_id, execution_version = job.id, job.execution_version
    redis = ctx.get("redis")
    topic_spec = None
    if ENABLE_INTERACTIVE_BRIEF and not synthesis_run:
        brief_result = await validate_job_brief(job_id, expected_execution_version=execution_version)
        # The service committed these calls to interaction_usage. Capture the
        # new Context so the parent/heartbeat see graph usage after this reset.
        cost_tracker.reset()
        execution.cost_context = copy_context()
        execution.phase = "analysis"
        if not brief_result.ready:
            return
        topic_spec = brief_result.topic_spec.model_dump(mode="json") if brief_result.topic_spec else None
        async with async_session_factory() as db:
            current = await JobRepository(db).get(job_id)
            if not current or current.status != "running" or not _owns_execution(current):
                raise _JobStopped

    async with ctx["provider_semaphore"]:
        if synthesis_run:
            await _event(job_id, "analyzing", "正在从已确认的采集快照恢复并生成报告。", 70, redis=redis)
            state = await _load_synthesis_state(job_id, execution_version)
            if state.get("data_sufficient") and not state.get("termination_reason"):
                result = await _invoke_synthesis_graph(job_id, execution_version, state)
            else:
                result = state
            result["candidate_boundary"] = state["candidate_boundary"]
            result["_candidate_synthesis"] = True
        elif ENABLE_CANDIDATE_CONFIRMATION:
            await _event(job_id, "collecting", "正在采集B站数据并形成候选账号快照。", 15, redis=redis)
            result = await _invoke_collection_graph(job_id, job.user_id, job.query, job.platforms, topic_spec, execution_version)
            result["topic_spec"] = topic_spec or result.get("topic_spec") or {}
            if job.analysis_mode == "deep" and result.get("data_sufficient") and not result.get("termination_reason"):
                result = await _collect_transcript_evidence(result, job_id, redis)
            await _persist_collection_snapshot(job_id, execution_version, result)
            return
        elif job.analysis_mode == "deep" and GRAPH_VERSION == "v2":
            await _event(job_id, "collecting", "正在采集B站样本，准备视频内容转写。", 15, redis=redis)
            result = await _invoke_collection_graph(job_id, job.user_id, job.query, job.platforms, topic_spec, execution_version)
            if result.get("data_sufficient") and not result.get("termination_reason"):
                result = await _collect_transcript_evidence(result, job_id, redis)
                await _event(job_id, "analyzing", "正在基于采集与转写证据生成分析报告。", 70, redis=redis)
                asr_seconds = result.get("asr_seconds", 0)
                result = await _invoke_synthesis_graph(job_id, execution_version, result)
                result["asr_seconds"] = asr_seconds
        else:
            await _event(job_id, "collecting", "正在采集B站数据并检索知识库。", 15, redis=redis)
            result = await _invoke_graph(job_id, job.user_id, job.query, job.platforms, topic_spec, execution_version)
            if job.analysis_mode == "deep":
                # Preserve the opt-in legacy v1 contract. The v2 path above
                # performs synthesis once, after transcript evidence arrives.
                result = await _enrich_deep_analysis(result, job_id, redis)

    result["_expected_execution_version"] = execution_version
    await _event(job_id, "validating", "正在校验 Evidence 与结构化结论。", 78, redis=redis)
    await _event(job_id, "persisting", "正在保存报告、证据和用量记录。", 92, redis=redis)
    await _persist_result(job_id, result)
    final_status = "completed" if result.get("report_final") and not result.get("termination_reason") else "partial"
    # The terminal database event commits atomically with the report. Only its
    # optional Redis projection remains after that transaction.
    await _publish_event(job_id, final_status, "报告已生成。" if final_status == "completed" else "已保存可用的部分结果。", 100, redis=redis)


async def run_analysis_job(ctx: dict, job_id_value: str, execution_version_value: int | None = None) -> None:
    job_id = uuid.UUID(job_id_value)
    claimed = await _claim_job(job_id, execution_version_value, ctx.get("job_id"))
    if claimed is None:
        return
    job, synthesis_run, token = claimed
    cost_tracker.reset()
    asr_usage = asr_usage_tracker.reset()
    fallback_counter.reset()
    trace_tracker.reset()
    execution = _Execution(
        job_id=job.id, version=job.execution_version, token=token,
        cost_context=copy_context(), brief_baseline=dict(job.interaction_usage or {}),
        phase="brief" if ENABLE_INTERACTIVE_BRIEF and not synthesis_run else "analysis",
        asr_usage=asr_usage,
    )
    context_token = _execution.set(execution)
    try:
        # Includes Brief, provider-slot waiting, collection, ASR, synthesis and
        # persistence. Arq's extra 30 seconds are reserved for cancellation and
        # settlement, rather than allowing ASR to escape the job budget.
        supervision = asyncio.create_task(
            _supervise(_execute_job(ctx, job, synthesis_run, execution), execution)
        )
        try:
            await asyncio.wait_for(asyncio.shield(supervision), timeout=JOB_TIMEOUT_SECONDS)
        finally:
            # wait_for alone can abandon its cancellation wait when it receives
            # another shutdown signal. Own that wait before settling any usage.
            await _cancel_and_wait(supervision)
    except _JobStopped:
        await _finish_attempt(execution)
    except asyncio.CancelledError:
        interrupted_running, _ = await _finish_attempt(execution, interrupted=True)
        if interrupted_running:
            raise
    except Exception as exc:
        code, retryable = _error_code(exc)
        if "REPORT_VALIDATION_FAILED" in str(exc):
            code, retryable = "REPORT_VALIDATION_FAILED", False
        logger.warning("Analysis job %s failed (%s): %s", job_id, code, type(exc).__name__)
        _, retry_delay = await _finish_attempt(execution, failure=(code, retryable))
        if retry_delay is not None:
            raise Retry(defer=retry_delay) from exc
    else:
        await _finish_attempt(execution)
    finally:
        _execution.reset(context_token)


async def startup(ctx: dict) -> None:
    configure_optional_model_routes()
    ctx["provider_semaphore"] = asyncio.Semaphore(WORKER_MAX_JOBS)


class WorkerSettings:
    functions = [run_analysis_job]
    cron_jobs = [cron(reconcile_pending_dispatches, minute=set(range(60)), second=30, timeout=60)]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    max_jobs = WORKER_MAX_JOBS
    job_timeout = JOB_TIMEOUT_SECONDS + 30
    on_startup = startup
