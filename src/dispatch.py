import logging
from datetime import datetime, timedelta, timezone

from arq.jobs import JobStatus
from sqlalchemy import and_, or_, select, update

from src.config import DISPATCH_RECONCILE_BATCH_SIZE, DISPATCH_RECONCILE_MIN_AGE_SECONDS, JOB_MAX_RETRIES, JOB_TIMEOUT_SECONDS
from src.db.models import AnalysisJob, CandidateSynthesisRun, JobEvent
from src.db.session import async_session_factory
from src.queue import JobQueue
from src.repositories import JobRepository


DISPATCH_PENDING_MESSAGE = "任务派发暂时未恢复。系统会稍后自动重试；如需立即处理，可先取消任务。"
logger = logging.getLogger(__name__)


async def recover_expired_jobs(now: datetime) -> int:
    """Fence workers that lost their lease and preserve frozen candidate decisions."""
    legacy_cutoff = now - timedelta(seconds=JOB_TIMEOUT_SECONDS + 30)
    expired = or_(
        AnalysisJob.worker_lease_expires_at <= now,
        and_(
            AnalysisJob.worker_lease_expires_at.is_(None),
            AnalysisJob.started_at <= legacy_cutoff,
        ),
    )
    recovered = 0
    async with async_session_factory() as db:
        jobs = list((await db.scalars(
            select(AnalysisJob)
            .where(AnalysisJob.status == "running", expired)
            .order_by(AnalysisJob.started_at)
            .limit(DISPATCH_RECONCILE_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )).all())
        for job in jobs:
            old_version = job.execution_version
            exhausted = job.retry_count >= JOB_MAX_RETRIES
            new_version = old_version + 1
            message = (
                "后台执行中断，已达到重试上限。可调整范围后创建新任务。"
                if exhausted else "后台执行中断，正在恢复本次分析，重试不重复占用额度。"
            )
            claimed = await db.execute(
                update(AnalysisJob)
                .where(
                    AnalysisJob.id == job.id,
                    AnalysisJob.status == "running",
                    AnalysisJob.execution_version == old_version,
                    expired,
                )
                .values(
                    execution_version=new_version,
                    retry_count=job.retry_count if exhausted else job.retry_count + 1,
                    worker_token=None,
                    worker_lease_expires_at=None,
                    arq_job_id=None,
                    status="failed" if exhausted else "pending",
                    started_at=None,
                    completed_at=now if exhausted else None,
                    dispatch_pending_at=None if exhausted else now - timedelta(seconds=DISPATCH_RECONCILE_MIN_AGE_SECONDS),
                    error_code="WORKER_FAILED" if exhausted else "DISPATCH_PENDING",
                    error_message=message,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                continue
            if not exhausted:
                previous_run = await db.scalar(select(CandidateSynthesisRun).where(
                    CandidateSynthesisRun.job_id == job.id,
                    CandidateSynthesisRun.execution_version == old_version,
                ))
                if previous_run:
                    db.add(CandidateSynthesisRun(
                        job_id=job.id,
                        decision_batch_id=previous_run.decision_batch_id,
                        execution_version=new_version,
                    ))
            db.add(JobEvent(
                job_id=job.id,
                event_type="failed" if exhausted else "worker_recovered",
                message=message,
                progress=job.progress,
                level="error" if exhausted else "warning",
            ))
            recovered += 1
        await db.commit()
    return recovered


async def recover_unclaimed_jobs(queue: JobQueue, now: datetime) -> int:
    """Recover acknowledged deliveries only after Arq confirms they are gone."""
    cutoff = now - timedelta(seconds=DISPATCH_RECONCILE_MIN_AGE_SECONDS)
    async with async_session_factory() as db:
        jobs = await JobRepository(db).lease_unclaimed_dispatches(cutoff, now, DISPATCH_RECONCILE_BATCH_SIZE)
        leased = [(job.id, job.execution_version, job.arq_job_id) for job in jobs]
        await db.commit()

    recovered = 0
    for job_id, version, arq_job_id in leased:
        try:
            status = await queue.status(arq_job_id)
        except Exception as exc:
            # A Redis outage is not evidence that the delivery was lost.
            logger.warning("Cannot inspect pending job %s (%s).", job_id, type(exc).__name__)
            continue
        if status not in {JobStatus.not_found, JobStatus.complete}:
            continue
        async with async_session_factory() as db:
            job = await JobRepository(db).get_for_update(job_id)
            if not job or job.status != "pending" or job.execution_version != version or job.arq_job_id != arq_job_id:
                continue
            exhausted = job.retry_count >= JOB_MAX_RETRIES
            message = (
                "任务多次未能开始执行，已达到重试上限。可调整范围后创建新任务。"
                if exhausted else "队列任务未能开始执行，正在恢复派发，重试不重复占用额度。"
            )
            claimed = await db.execute(
                update(AnalysisJob)
                .where(
                    AnalysisJob.id == job_id, AnalysisJob.status == "pending",
                    AnalysisJob.execution_version == version,
                    AnalysisJob.arq_job_id == arq_job_id,
                    AnalysisJob.dispatch_pending_at == now,
                )
                .values(
                    execution_version=version + 1,
                    retry_count=job.retry_count if exhausted else job.retry_count + 1,
                    status="failed" if exhausted else "pending",
                    arq_job_id=None, worker_token=None, worker_lease_expires_at=None,
                    started_at=None, completed_at=now if exhausted else None,
                    dispatch_pending_at=None if exhausted else cutoff,
                    error_code="WORKER_FAILED" if exhausted else "DISPATCH_PENDING",
                    error_message=message,
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                continue
            if not exhausted:
                previous_run = await db.scalar(select(CandidateSynthesisRun).where(
                    CandidateSynthesisRun.job_id == job_id,
                    CandidateSynthesisRun.execution_version == version,
                ))
                if previous_run:
                    db.add(CandidateSynthesisRun(
                        job_id=job_id, decision_batch_id=previous_run.decision_batch_id,
                        execution_version=version + 1,
                    ))
            db.add(JobEvent(
                job_id=job_id, event_type="failed" if exhausted else "dispatch_unclaimed",
                message=message, progress=job.progress, level="error" if exhausted else "warning",
            ))
            await db.commit()
            recovered += 1
    return recovered


async def reconcile_pending_dispatches(
    _ctx: dict | None = None,
    *,
    queue: JobQueue | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Recover expired workers, then re-dispatch durable pending intents."""
    queue = queue or JobQueue((_ctx or {}).get("redis"))
    now = now or datetime.now(timezone.utc)
    await recover_expired_jobs(now)
    await recover_unclaimed_jobs(queue, now)
    cutoff = now - timedelta(seconds=DISPATCH_RECONCILE_MIN_AGE_SECONDS)

    async with async_session_factory() as db:
        repo = JobRepository(db)
        jobs = await repo.lease_pending_dispatches(cutoff, now, DISPATCH_RECONCILE_BATCH_SIZE)
        leased = [(job.id, job.execution_version) for job in jobs]
        for job in jobs:
            db.add(JobEvent(
                job_id=job.id,
                event_type="dispatch_recovery_started",
                message="检测到未确认的队列派发，开始按原执行版本恢复。",
                progress=job.progress,
                level="warning",
            ))
        await db.commit()

    recovered = 0
    failed = 0
    for job_id, execution_version in leased:
        try:
            arq_job_id = await queue.enqueue(str(job_id), execution_version)
        except Exception:
            failed += 1
            async with async_session_factory() as db:
                job = await JobRepository(db).get_for_update(job_id)
                if job and job.status == "pending" and job.execution_version == execution_version and job.arq_job_id is None:
                    job.dispatch_pending_at = now
                    job.error_code = "DISPATCH_PENDING"
                    job.error_message = DISPATCH_PENDING_MESSAGE
                    db.add(JobEvent(
                        job_id=job.id,
                        event_type="dispatch_recovery_failed",
                        message=DISPATCH_PENDING_MESSAGE,
                        progress=job.progress,
                        level="error",
                    ))
                    await db.commit()
                else:
                    await db.rollback()
            continue

        async with async_session_factory() as db:
            job = await JobRepository(db).get_for_update(job_id)
            if job and job.status == "pending" and job.execution_version == execution_version and job.arq_job_id is None:
                job.arq_job_id = arq_job_id
                job.dispatch_pending_at = None
                if job.error_code == "DISPATCH_PENDING":
                    job.error_code = None
                    job.error_message = None
                db.add(JobEvent(
                    job_id=job.id,
                    event_type="dispatch_recovered",
                    message="任务已按原执行版本恢复派发。",
                    progress=job.progress,
                    level="info",
                ))
                await db.commit()
                recovered += 1
            else:
                await db.rollback()

    return {"leased": len(leased), "recovered": recovered, "failed": failed}
