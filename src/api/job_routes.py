import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from src.api.errors import AppError, ERROR_MESSAGES
from src.api.schemas import JobCreate, JobEventRead, JobRead, JobRevisionCreate
from src.auth.dependencies import get_current_user
from src.briefing.schemas import ClarificationAnswer, ClarificationRead
from src.candidates.schemas import CandidateDecisionSubmit, CandidateListRead, CandidateRead, CandidateTopicSummary
from src.candidates.service import decision_payload_hash
from src.config import JOB_MAX_RETRIES, USER_MONTHLY_JOB_LIMIT
from src.db.models import (
    AnalysisJob,
    CandidateDecision,
    CandidateDecisionBatch,
    CandidateSnapshot,
    CandidateSynthesisRun,
    JobEvent,
    User,
)
from src.db.session import get_db
from src.dispatch import DISPATCH_PENDING_MESSAGE
from src.queue import JobQueue, get_job_queue
from src.repositories import CandidateRepository, JobRepository, ReportRepository, UsageRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _mark_enqueue_failed(db: AsyncSession, job_id: uuid.UUID, execution_version: int) -> None:
    repo = JobRepository(db)
    job = await repo.get_for_update(job_id)
    if job and job.execution_version == execution_version and job.status == "pending":
        job.status = "failed"
        job.error_code = "WORKER_FAILED"
        job.error_message = ERROR_MESSAGES["WORKER_FAILED"]
        job.dispatch_pending_at = None
        db.add(JobEvent(job_id=job.id, event_type="failed", message=job.error_message, progress=job.progress, level="error"))
        await db.commit()
        return
    await db.rollback()


async def _enqueue_committed_job(
    db: AsyncSession,
    queue: JobQueue,
    job_id: uuid.UUID,
    execution_version: int,
    *,
    mark_failed: bool = True,
) -> AnalysisJob | None:
    try:
        arq_job_id = await queue.enqueue(str(job_id), execution_version)
    except Exception:
        if mark_failed:
            await _mark_enqueue_failed(db, job_id, execution_version)
        raise

    repo = JobRepository(db)
    job = await repo.get_for_update(job_id)
    if job and job.execution_version == execution_version and job.status == "pending":
        job.arq_job_id = arq_job_id
        job.dispatch_pending_at = None
        await db.commit()
        return job
    # A fast worker may already have started or completed. End the read/lock
    # transaction without expiring the object returned through JobRead.
    await db.commit()
    return job


async def _leave_dispatch_pending(db: AsyncSession, job_id: uuid.UUID, execution_version: int) -> None:
    job = await JobRepository(db).get_for_update(job_id)
    if job and job.execution_version == execution_version and job.status == "pending":
        job.error_code = "DISPATCH_PENDING"
        job.error_message = DISPATCH_PENDING_MESSAGE
        db.add(JobEvent(
            job_id=job.id,
            event_type="dispatch_pending",
            message=DISPATCH_PENDING_MESSAGE,
            progress=job.progress,
            level="warning",
        ))
        await db.commit()
        return
    await db.rollback()


async def require_job(job_id: uuid.UUID, user: User, db: AsyncSession):
    job = await JobRepository(db).get_owned(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    return job


@router.post("", response_model=JobRead, status_code=202)
async def create_job(payload: JobCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), queue: JobQueue = Depends(get_job_queue)):
    usage_repo = UsageRepository(db)
    await usage_repo.lock_user(user.id)
    repo = JobRepository(db)
    existing = await repo.get_by_idempotency(user.id, payload.idempotency_key)
    if existing:
        if (
            existing.query != payload.query
            or existing.platforms != payload.platforms
            or existing.analysis_mode != payload.analysis_mode
            or existing.revision_of_job_id is not None
        ):
            raise AppError(409, "JOB_IDEMPOTENCY_CONFLICT", "这次提交标识已用于其他分析，请重新提交新的任务。")
        return existing
    if payload.analysis_mode == "deep":
        from src.tools.capabilities import get_tool_capabilities
        if not get_tool_capabilities()["get_transcript"].enabled:
            raise AppError(409, "ASR_UNAVAILABLE", ERROR_MESSAGES["ASR_UNAVAILABLE"])
    since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = await ReportRepository(db).usage_summary(user.id, since)
    if usage["jobs_used"] >= USER_MONTHLY_JOB_LIMIT:
        raise AppError(429, "USAGE_LIMIT_REACHED", "本月公开测试用量已用完。")
    now = datetime.now(timezone.utc)
    job = await repo.create(
        user_id=user.id,
        query=payload.query,
        platforms=payload.platforms,
        analysis_mode=payload.analysis_mode,
        idempotency_key=payload.idempotency_key,
        dispatch_pending_at=now,
    )
    await usage_repo.reserve(job)
    db.add(JobEvent(job_id=job.id, event_type="queued", message="任务已创建，等待后台 Worker。", progress=0, level="info"))
    await db.commit()
    try:
        scheduled_job = await _enqueue_committed_job(db, queue, job.id, job.execution_version)
    except Exception as exc:
        raise AppError(503, "WORKER_FAILED", ERROR_MESSAGES["WORKER_FAILED"]) from exc
    return scheduled_job or job


@router.get("", response_model=dict)
async def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), status: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    items, total = await JobRepository(db).list_owned(user.id, limit, offset, status)
    return {"items": [JobRead.model_validate(item) for item in items], "total": total}


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await require_job(job_id, user, db)


def _candidate_list(snapshot: CandidateSnapshot, job: AnalysisJob) -> CandidateListRead:
    decisions = {
        item.candidate_account_id: item
        for item in (snapshot.decision_batch.decisions if snapshot.decision_batch else [])
    }
    candidates = []
    for item in sorted(snapshot.candidates, key=lambda candidate: candidate.sort_order):
        decision = decisions.get(item.id)
        candidates.append(CandidateRead(
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
            decision=decision.decision if decision else "undecided",
            reason=decision.reason if decision else "",
        ))
    return CandidateListRead(
        snapshot_id=snapshot.id,
        snapshot_version=snapshot.schema_version,
        topic_spec=CandidateTopicSummary.model_validate(snapshot.topic_summary),
        candidates=candidates,
        max_candidates=snapshot.max_candidates,
        can_submit=job.can_confirm_candidates and snapshot.decision_batch is None,
        snapshot_hash=snapshot.snapshot_hash,
    )


async def _candidate_snapshot_for_job(db: AsyncSession, job: AnalysisJob) -> CandidateSnapshot | None:
    options = (
        selectinload(CandidateSnapshot.candidates),
        selectinload(CandidateSnapshot.decision_batch).selectinload(CandidateDecisionBatch.decisions),
    )
    snapshot = await db.scalar(
        select(CandidateSnapshot)
        .options(*options)
        .where(
            CandidateSnapshot.job_id == job.id,
            CandidateSnapshot.source_execution_version == job.execution_version,
        )
    )
    if snapshot:
        return snapshot
    synthesis_run = await db.scalar(
        select(CandidateSynthesisRun)
        .options(
            selectinload(CandidateSynthesisRun.decision_batch)
            .selectinload(CandidateDecisionBatch.snapshot)
            .selectinload(CandidateSnapshot.candidates),
            selectinload(CandidateSynthesisRun.decision_batch)
            .selectinload(CandidateDecisionBatch.snapshot)
            .selectinload(CandidateSnapshot.decision_batch)
            .selectinload(CandidateDecisionBatch.decisions),
        )
        .where(
            CandidateSynthesisRun.job_id == job.id,
            CandidateSynthesisRun.execution_version == job.execution_version,
        )
    )
    return synthesis_run.decision_batch.snapshot if synthesis_run else None


@router.get("/{job_id}/candidates", response_model=CandidateListRead)
async def get_candidates(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await require_job(job_id, user, db)
    snapshot = await _candidate_snapshot_for_job(db, job)
    if not snapshot:
        raise AppError(404, "CANDIDATE_SNAPSHOT_NOT_FOUND", ERROR_MESSAGES["CANDIDATE_SNAPSHOT_NOT_FOUND"])
    return _candidate_list(snapshot, job)


@router.post("/{job_id}/candidates/decisions", response_model=JobRead, status_code=202)
async def submit_candidate_decisions(
    job_id: uuid.UUID,
    payload: CandidateDecisionSubmit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
):
    payload_hash = decision_payload_hash(
        str(payload.snapshot_id),
        [item.model_dump(mode="json") for item in payload.decisions],
    )
    job_repo = JobRepository(db)
    candidate_repo = CandidateRepository(db)
    job = await job_repo.get_owned_for_update(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])

    existing = await candidate_repo.decision_by_request(payload.request_id)
    if existing:
        if (
            existing.job_id == job.id
            and existing.snapshot_id == payload.snapshot_id
            and existing.submitted_by == user.id
            and existing.payload_hash == payload_hash
        ):
            return job
        raise AppError(409, "CANDIDATE_DECISION_CONFLICT", ERROR_MESSAGES["CANDIDATE_DECISION_CONFLICT"])

    snapshot = await db.scalar(
        select(CandidateSnapshot)
        .options(
            selectinload(CandidateSnapshot.candidates),
            selectinload(CandidateSnapshot.decision_batch),
        )
        .where(
            CandidateSnapshot.id == payload.snapshot_id,
            CandidateSnapshot.job_id == job.id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if not snapshot or snapshot.source_execution_version != job.execution_version:
        raise AppError(409, "CANDIDATE_SNAPSHOT_NOT_FOUND", ERROR_MESSAGES["CANDIDATE_SNAPSHOT_NOT_FOUND"])
    if job.status != "waiting_candidate_confirmation" or not job.can_confirm_candidates:
        raise AppError(409, "CANDIDATE_DECISION_INVALID", ERROR_MESSAGES["CANDIDATE_DECISION_INVALID"])
    if snapshot.decision_batch:
        raise AppError(409, "CANDIDATE_DECISION_ALREADY_SUBMITTED", ERROR_MESSAGES["CANDIDATE_DECISION_ALREADY_SUBMITTED"])

    submitted_ids = [item.candidate_id for item in payload.decisions]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise AppError(422, "CANDIDATE_DECISION_INVALID", ERROR_MESSAGES["CANDIDATE_DECISION_INVALID"])
    candidates_by_id = {item.candidate_id: item for item in snapshot.candidates}
    if set(submitted_ids) != set(candidates_by_id):
        raise AppError(422, "CANDIDATE_DECISION_INVALID", ERROR_MESSAGES["CANDIDATE_DECISION_INVALID"])
    if not any(item.decision == "confirmed" for item in payload.decisions):
        raise AppError(422, "CANDIDATE_DECISION_INVALID", "至少纳入一个候选账号后才能继续。")

    batch = CandidateDecisionBatch(
        request_id=payload.request_id,
        snapshot_id=snapshot.id,
        job_id=job.id,
        submitted_by=user.id,
        payload_hash=payload_hash,
    )
    db.add(batch)
    await db.flush()
    for item in payload.decisions:
        db.add(CandidateDecision(
            batch_id=batch.id,
            candidate_account_id=candidates_by_id[item.candidate_id].id,
            decision=item.decision,
            reason=item.reason,
        ))

    job.status = "pending"
    job.progress = max(job.progress, 60)
    job.error_code = None
    job.error_message = None
    job.execution_version += 1
    job.arq_job_id = None
    job.dispatch_pending_at = datetime.now(timezone.utc)
    execution_version = job.execution_version
    db.add(CandidateSynthesisRun(
        job_id=job.id,
        decision_batch_id=batch.id,
        execution_version=execution_version,
    ))
    db.add(JobEvent(
        job_id=job.id,
        event_type="candidate_decisions_submitted",
        message="已保存候选确认，任务将基于原采集快照继续生成报告。",
        progress=job.progress,
        level="info",
    ))
    await db.commit()
    try:
        scheduled_job = await _enqueue_committed_job(db, queue, job.id, execution_version, mark_failed=False)
    except Exception as exc:
        await _leave_dispatch_pending(db, job.id, execution_version)
        raise AppError(503, "DISPATCH_PENDING", DISPATCH_PENDING_MESSAGE) from exc
    return scheduled_job or job


@router.get("/{job_id}/events", response_model=dict)
async def get_events(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_job(job_id, user, db)
    events = await JobRepository(db).events(job_id)
    return {"items": [JobEventRead.model_validate(event) for event in events]}


@router.get("/{job_id}/clarification", response_model=dict)
async def get_clarification(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await require_job(job_id, user, db)
    items = await JobRepository(db).clarifications(job_id)
    current = next((item for item in reversed(items) if item.status == "pending"), None) if job.status == "waiting_user" else None
    history = [item for item in items if item.status == "answered"]
    return {
        "job_id": job_id,
        "max_rounds": 2,
        "current": ClarificationRead.model_validate(current) if current else None,
        "history": [ClarificationRead.model_validate(item) for item in history],
    }


@router.post("/{job_id}/clarification", response_model=JobRead, status_code=202)
async def answer_clarification(
    job_id: uuid.UUID,
    payload: ClarificationAnswer,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
):
    repo = JobRepository(db)
    job = await repo.get_owned_for_update(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    request = await repo.clarification_by_request_for_update(job_id, payload.request_id)
    if request and request.status == "answered":
        if request.selected_option_id == payload.selected_option_id and request.custom_answer == payload.custom_answer:
            return job
        raise AppError(409, "CLARIFICATION_CONFLICT", ERROR_MESSAGES["CLARIFICATION_CONFLICT"])
    if job.status != "waiting_user" or not request or request.status != "pending":
        raise AppError(409, "CLARIFICATION_INVALID", ERROR_MESSAGES["CLARIFICATION_INVALID"])
    if payload.selected_option_id:
        option_ids = {str(item.get("id", "")) for item in request.options if isinstance(item, dict)}
        if payload.selected_option_id not in option_ids:
            raise AppError(422, "CLARIFICATION_INVALID", ERROR_MESSAGES["CLARIFICATION_INVALID"])
    if payload.custom_answer and not request.allow_custom:
        raise AppError(422, "CLARIFICATION_INVALID", ERROR_MESSAGES["CLARIFICATION_INVALID"])

    request.status = "answered"
    request.selected_option_id = payload.selected_option_id
    request.custom_answer = payload.custom_answer
    request.answered_at = datetime.now(timezone.utc)
    job.status = "pending"
    job.progress = max(job.progress, 5)
    job.error_code = None
    job.error_message = None
    job.execution_version += 1
    job.arq_job_id = None
    job.dispatch_pending_at = datetime.now(timezone.utc)
    execution_version = job.execution_version
    db.add(JobEvent(job_id=job.id, event_type="clarification_answered", message="已收到研究范围补充，任务将重新判断范围。", progress=job.progress, level="info"))
    await db.commit()
    try:
        scheduled_job = await _enqueue_committed_job(db, queue, job.id, execution_version)
    except Exception as exc:
        raise AppError(503, "WORKER_FAILED", ERROR_MESSAGES["WORKER_FAILED"]) from exc
    return scheduled_job or job


@router.post("/{job_id}/cancel", response_model=JobRead)
async def cancel_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await JobRepository(db).get_owned_for_update(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    if job.status not in {"pending", "running", "waiting_user", "waiting_candidate_confirmation"}:
        return job
    job.status, job.cancelled_at, job.error_code, job.error_message = "cancelled", datetime.now(timezone.utc), "JOB_CANCELLED", ERROR_MESSAGES["JOB_CANCELLED"]
    job.dispatch_pending_at = None
    await JobRepository(db).save(job)
    await JobRepository(db).add_event(job.id, "cancelled", "用户已取消任务。", job.progress, "warning")
    return job


@router.post("/{job_id}/retry", response_model=JobRead, status_code=202)
async def retry_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), queue: JobQueue = Depends(get_job_queue)):
    repo = JobRepository(db)
    job = await repo.get_owned_for_update(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    if job.has_active_worker:
        raise AppError(409, "JOB_STOPPING", "任务正在停止，请稍后重试。")
    if job.retry_count >= JOB_MAX_RETRIES:
        raise AppError(409, "JOB_RETRY_LIMIT_REACHED", "这个任务已达到重试上限，可以调整范围后创建新任务。")
    if not job.can_retry:
        raise AppError(409, "JOB_NOT_RETRYABLE", ERROR_MESSAGES["JOB_NOT_RETRYABLE"])
    decision_batch = await CandidateRepository(db).latest_decision_batch(job.id)
    if decision_batch:
        await repo.clear_report_outputs(job.id)
    else:
        await repo.clear_outputs(job.id)
    set_committed_value(job, "reports", [])
    job.retry_count += 1
    job.execution_version += 1
    job.status, job.progress, job.error_code, job.error_message, job.cancelled_at = "pending", 0, None, None, None
    job.arq_job_id = None
    job.worker_token = None
    job.worker_lease_expires_at = None
    job.started_at = None
    job.completed_at = None
    job.dispatch_pending_at = datetime.now(timezone.utc)
    execution_version = job.execution_version
    if decision_batch:
        db.add(CandidateSynthesisRun(
            job_id=job.id,
            decision_batch_id=decision_batch.id,
            execution_version=execution_version,
        ))
    db.add(JobEvent(job_id=job.id, event_type="queued", message=f"任务已重新入队（第 {job.retry_count} 次重试）。", progress=0, level="info"))
    await db.commit()
    try:
        scheduled_job = await _enqueue_committed_job(db, queue, job.id, execution_version)
    except Exception as exc:
        raise AppError(503, "WORKER_FAILED", ERROR_MESSAGES["WORKER_FAILED"]) from exc
    return scheduled_job or job


@router.post("/{job_id}/revisions", response_model=JobRead, status_code=202)
async def revise_job(
    job_id: uuid.UUID,
    payload: JobRevisionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
):
    usage_repo = UsageRepository(db)
    await usage_repo.lock_user(user.id)
    repo = JobRepository(db)
    source = await repo.get_owned_for_update(job_id, user.id)
    if not source:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])

    existing = await repo.get_by_idempotency(user.id, payload.idempotency_key)
    if existing:
        if existing.revision_of_job_id == source.id and existing.query == payload.query:
            return existing
        raise AppError(409, "JOB_REVISION_CONFLICT", ERROR_MESSAGES["JOB_REVISION_CONFLICT"])
    if not source.can_revise:
        raise AppError(409, "JOB_REVISION_INVALID", ERROR_MESSAGES["JOB_REVISION_INVALID"])

    since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = await ReportRepository(db).usage_summary(user.id, since)
    if usage["jobs_used"] >= USER_MONTHLY_JOB_LIMIT:
        raise AppError(429, "USAGE_LIMIT_REACHED", "本月公开测试用量已用完。")
    if source.analysis_mode == "deep":
        from src.tools.capabilities import get_tool_capabilities
        if not get_tool_capabilities()["get_transcript"].enabled:
            raise AppError(409, "ASR_UNAVAILABLE", ERROR_MESSAGES["ASR_UNAVAILABLE"])

    now = datetime.now(timezone.utc)
    source_was_waiting = source.status == "waiting_user"
    if source_was_waiting:
        source.status = "cancelled"
        source.cancelled_at = now
        source.error_code = "JOB_CANCELLED"
        source.error_message = ERROR_MESSAGES["JOB_CANCELLED"]
        source.dispatch_pending_at = None

    revised = await repo.create(
        user_id=user.id,
        query=payload.query,
        platforms=source.platforms,
        analysis_mode=source.analysis_mode,
        idempotency_key=payload.idempotency_key,
        revision_of_job_id=source.id,
        dispatch_pending_at=now,
    )
    await usage_repo.reserve(revised)
    db.add(JobEvent(
        job_id=source.id,
        event_type="scope_revision_created",
        message=(
            f"已取消旧任务并创建修订任务 {str(revised.id)[:8]}；回答保留。"
            if source_was_waiting
            else f"已创建修订任务 {str(revised.id)[:8]}；原任务保留。"
        ),
        progress=source.progress,
        level="info",
    ))
    db.add(JobEvent(
        job_id=revised.id,
        event_type="scope_revision_started",
        message="由上一任务的范围修订创建。",
        progress=0,
        level="info",
    ))
    await db.commit()
    try:
        scheduled_job = await _enqueue_committed_job(db, queue, revised.id, revised.execution_version)
    except Exception as exc:
        raise AppError(503, "WORKER_FAILED", ERROR_MESSAGES["WORKER_FAILED"]) from exc
    return scheduled_job or revised


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await JobRepository(db).get_owned_for_update(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    if job.has_active_worker:
        raise AppError(409, "JOB_STOPPING", "任务正在停止，请稍后删除。")
    if job.status in {"pending", "running"}:
        raise AppError(409, "JOB_RUNNING", "运行中的任务请先取消。")
    if await JobRepository(db).has_revisions(job.id):
        raise AppError(409, "JOB_HAS_REVISIONS", ERROR_MESSAGES["JOB_HAS_REVISIONS"])
    await JobRepository(db).delete_owned(job)
