import asyncio
import uuid
from datetime import datetime, timezone

from arq import Retry, cron
from arq.connections import RedisSettings
from sqlalchemy import select

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
    JOB_MAX_RETRIES,
    JOB_TIMEOUT_SECONDS,
    REDIS_URL,
    WORKER_MAX_JOBS,
)
from src.db.models import (
    CandidateAccount,
    CandidateSnapshot,
    CollectionSnapshot,
    EvidenceItem,
    JobEvent,
    Report,
    UsageRecord,
)
from src.db.session import async_session_factory
from src.dispatch import reconcile_pending_dispatches
from src.gateway.cost_tracker import cost_tracker
from src.gateway.model_bootstrap import configure_optional_model_routes
from src.graph.builder import build_graph
from src.graph.v2 import build_collection_graph_v2, build_synthesis_graph_v2, stable_evidence_id
from src.reporting.validation import finalize_report, validate_claims, validate_report_references
from src.repositories import CandidateRepository, JobRepository
from src.tools.transcript import TranscriptError, get_transcript
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker

graph = build_graph()
collection_graph = build_collection_graph_v2()
synthesis_graph = build_synthesis_graph_v2()


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


async def _event(job_id: uuid.UUID, event_type: str, message: str, progress: int, level: str = "info", redis=None) -> None:
    async with async_session_factory() as db:
        job = await JobRepository(db).get(job_id)
        if job:
            job.progress = progress
            await JobRepository(db).save(job)
            await JobRepository(db).add_event(job_id, event_type, message, progress, level)
    if redis:
        await redis.hset(f"job:{job_id}:status", mapping={"status": event_type, "message": message, "progress": progress})
        await redis.expire(f"job:{job_id}:status", 86400)
        await redis.xadd(f"job:{job_id}:events", {"event_type": event_type, "message": message, "progress": progress, "level": level}, maxlen=200)
        await redis.expire(f"job:{job_id}:events", 86400)


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
    task = asyncio.create_task(
        compiled_graph.ainvoke(
            state,
            config={"configurable": {"thread_id": f"{job_id}:{execution_version}"}},
        )
    )
    while not task.done():
        await asyncio.sleep(1.5)
        async with async_session_factory() as db:
            current = await JobRepository(db).get(job_id)
            if not current or current.status == "cancelled" or current.execution_version != execution_version:
                task.cancel()
                raise asyncio.CancelledError
    return await task


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


def _interaction_totals(job, current_cost: dict) -> dict:
    interaction = job.interaction_usage or {}
    return {
        "input_tokens": int(current_cost["input_tokens"]) + int(interaction.get("input_tokens", 0)),
        "output_tokens": int(current_cost["output_tokens"]) + int(interaction.get("output_tokens", 0)),
        "estimated_cost": round(float(current_cost["total_cost"]) + float(interaction.get("estimated_cost", 0.0)), 6),
    }


async def _persist_collection_snapshot(job_id: uuid.UUID, execution_version: int, result: dict) -> dict:
    current_cost = cost_tracker.get_summary()
    async with async_session_factory() as db:
        job = await JobRepository(db).get_for_update(job_id)
        if not job or job.status == "cancelled" or job.status != "running" or job.execution_version != execution_version:
            raise asyncio.CancelledError

        collection_usage = _interaction_totals(job, current_cost)
        collection_usage["asr_seconds"] = float(result.get("asr_seconds", 0))
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

        usage = await db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
        if usage:
            usage.input_tokens = collection_usage["input_tokens"]
            usage.output_tokens = collection_usage["output_tokens"]
            usage.estimated_cost = collection_usage["estimated_cost"]
            usage.asr_seconds = collection_usage["asr_seconds"]
        else:
            db.add(UsageRecord(
                user_id=job.user_id,
                job_id=job.id,
                input_tokens=collection_usage["input_tokens"],
                output_tokens=collection_usage["output_tokens"],
                estimated_cost=collection_usage["estimated_cost"],
                asr_seconds=collection_usage["asr_seconds"],
            ))

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
        if not job or job.status != "running" or job.execution_version != execution_version or not run:
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
            "data_sufficient": True,
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
    valid, reason = validate_claims(claims, evidence)
    if not valid:
        raise ValueError(f"REPORT_VALIDATION_FAILED: {reason}")
    report_source = result.get("report_final", "") + _candidate_boundary_markdown(result.get("candidate_boundary"))
    content = finalize_report(report_source, claims, evidence)
    valid, reason = validate_report_references(content, evidence)
    if not valid:
        raise ValueError(f"REPORT_VALIDATION_FAILED: {reason}")
    cost = cost_tracker.get_summary()
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
        ):
            raise asyncio.CancelledError
        model_info = {
            "provider": DEFAULT_LLM_PROVIDER,
            "model": DEFAULT_LLM_MODEL_ID,
            "workflow": result.get("workflow_version", "v2"),
            "trace": trace,
            "fallback": fallback_counter.get_summary(),
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

        usage = await db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
        if result.get("_candidate_synthesis") and usage:
            usage.input_tokens += int(cost["input_tokens"])
            usage.output_tokens += int(cost["output_tokens"])
            usage.estimated_cost = round(usage.estimated_cost + float(cost["total_cost"]), 6)
        else:
            totals = _interaction_totals(job, cost)
            if usage:
                usage.input_tokens = totals["input_tokens"]
                usage.output_tokens = totals["output_tokens"]
                usage.estimated_cost = totals["estimated_cost"]
                usage.asr_seconds = float(result.get("asr_seconds", usage.asr_seconds))
            else:
                db.add(UsageRecord(
                    user_id=job.user_id,
                    job_id=job.id,
                    input_tokens=totals["input_tokens"],
                    output_tokens=totals["output_tokens"],
                    estimated_cost=totals["estimated_cost"],
                    asr_seconds=float(result.get("asr_seconds", 0)),
                ))
        job.status, job.progress, job.completed_at = status, 100, datetime.now(timezone.utc)
        if status == "partial":
            job.error_code, job.error_message = "EVIDENCE_INSUFFICIENT", ERROR_MESSAGES["EVIDENCE_INSUFFICIENT"]
        await db.commit()
        return report.id


async def run_analysis_job(ctx: dict, job_id_value: str, execution_version_value: int | None = None) -> None:
    job_id = uuid.UUID(job_id_value)
    redis = ctx.get("redis")
    async with async_session_factory() as db:
        repo = JobRepository(db)
        job = await repo.get(job_id)
        if not job or job.status != "pending":
            return
        if execution_version_value is not None and job.execution_version != int(execution_version_value):
            return
        synthesis_run = (
            await CandidateRepository(db).synthesis_run(job.id, job.execution_version)
            if ENABLE_CANDIDATE_CONFIRMATION
            else None
        )
        job.status, job.started_at, job.error_code, job.error_message = "running", datetime.now(timezone.utc), None, None
        job.dispatch_pending_at = None
        await repo.save(job)
        user_id = job.user_id
        query = job.query
        platforms = job.platforms
        retry_count = job.retry_count
        analysis_mode = job.analysis_mode
        execution_version = job.execution_version
    cost_tracker.reset()
    fallback_counter.reset()
    trace_tracker.reset()
    try:
        topic_spec = None
        if ENABLE_INTERACTIVE_BRIEF and not synthesis_run:
            brief_result = await validate_job_brief(job_id, expected_execution_version=execution_version)
            if not brief_result.ready:
                return
            topic_spec = brief_result.topic_spec.model_dump(mode="json") if brief_result.topic_spec else None
            cost_tracker.reset()
            async with async_session_factory() as db:
                current = await JobRepository(db).get(job_id)
                if not current or current.status != "running" or current.execution_version != execution_version:
                    return

        async with ctx["provider_semaphore"]:
            if synthesis_run:
                await _event(job_id, "analyzing", "正在从已确认的采集快照恢复并生成报告。", 70, redis=redis)
                state = await _load_synthesis_state(job_id, execution_version)
                result = await asyncio.wait_for(
                    _invoke_synthesis_graph(job_id, execution_version, state),
                    timeout=JOB_TIMEOUT_SECONDS,
                )
                result["candidate_boundary"] = state["candidate_boundary"]
                result["_candidate_synthesis"] = True
            elif ENABLE_CANDIDATE_CONFIRMATION:
                await _event(job_id, "collecting", "正在采集B站数据并形成候选账号快照。", 15, redis=redis)
                result = await asyncio.wait_for(
                    _invoke_collection_graph(job_id, user_id, query, platforms, topic_spec, execution_version),
                    timeout=JOB_TIMEOUT_SECONDS,
                )
                result["topic_spec"] = topic_spec or result.get("topic_spec") or {}
                if analysis_mode == "deep":
                    result = await _collect_transcript_evidence(result, job_id, redis)
                await _persist_collection_snapshot(job_id, execution_version, result)
                return
            else:
                await _event(job_id, "collecting", "正在采集B站数据并检索知识库。", 15, redis=redis)
                result = await asyncio.wait_for(
                    _invoke_graph(job_id, user_id, query, platforms, topic_spec, execution_version),
                    timeout=JOB_TIMEOUT_SECONDS,
                )
                if analysis_mode == "deep":
                    result = await _enrich_deep_analysis(result, job_id, redis)

        result["_expected_execution_version"] = execution_version
        await _event(job_id, "validating", "正在校验 Evidence 与结构化结论。", 78, redis=redis)
        await _event(job_id, "persisting", "正在保存报告、证据和用量记录。", 92, redis=redis)
        await _persist_result(job_id, result)
        final_status = "partial" if result.get("termination_reason") else "completed"
        await _event(job_id, final_status, "报告已生成。" if final_status == "completed" else "已保存可用的部分结果。", 100, redis=redis)
    except asyncio.CancelledError:
        return
    except Exception as exc:
        code, retryable = _error_code(exc)
        if "REPORT_VALIDATION_FAILED" in str(exc):
            code, retryable = "REPORT_VALIDATION_FAILED", False
        if code in {"REPORT_VALIDATION_FAILED", "CANDIDATE_SNAPSHOT_INVALID"}:
            print(f"[worker] {code}: {str(exc)[:240]}")
        else:
            print(f"[worker] {code}: {type(exc).__name__}")
        async with async_session_factory() as db:
            repo = JobRepository(db)
            job = await repo.get(job_id)
            if not job or job.status == "cancelled":
                return
            if retryable and retry_count < JOB_MAX_RETRIES:
                job.retry_count += 1
                job.status = "pending"
                await repo.save(job)
                await repo.add_event(job_id, "queued", f"临时故障，{2 ** job.retry_count * 5} 秒后自动重试。", job.progress, "warning")
                raise Retry(defer=2 ** job.retry_count * 5) from exc
            job.status = "failed"
            job.error_code = code
            job.error_message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["WORKER_FAILED"])
            await repo.save(job)
            await repo.add_event(job_id, "failed", job.error_message, job.progress, "error")


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
