import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import (
    AnalysisJob,
    CandidateDecisionBatch,
    CandidateSnapshot,
    CandidateSynthesisRun,
    EvidenceItem,
    JobClarification,
    JobEvent,
    Report,
    ReportFeedback,
    ShareLink,
    UsageRecord,
    User,
)


class UserRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: return await self.db.get(User, user_id)
    async def get_by_email(self, email: str) -> User | None: return await self.db.scalar(select(User).where(User.email == email.lower()))
    async def create(self, email: str, hashed_password: str) -> User:
        user = User(email=email.lower(), hashed_password=hashed_password); self.db.add(user); await self.db.commit(); await self.db.refresh(user); return user


class JobRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def get_owned(self, job_id: uuid.UUID, user_id: uuid.UUID) -> AnalysisJob | None:
        return await self.db.scalar(select(AnalysisJob).options(selectinload(AnalysisJob.reports), selectinload(AnalysisJob.clarifications)).where(AnalysisJob.id == job_id, AnalysisJob.user_id == user_id))
    async def get_owned_for_update(self, job_id: uuid.UUID, user_id: uuid.UUID) -> AnalysisJob | None:
        return await self.db.scalar(select(AnalysisJob).options(selectinload(AnalysisJob.reports), selectinload(AnalysisJob.clarifications)).where(AnalysisJob.id == job_id, AnalysisJob.user_id == user_id).execution_options(populate_existing=True).with_for_update())
    async def get_for_update(self, job_id: uuid.UUID) -> AnalysisJob | None:
        return await self.db.scalar(select(AnalysisJob).options(selectinload(AnalysisJob.reports), selectinload(AnalysisJob.clarifications)).where(AnalysisJob.id == job_id).execution_options(populate_existing=True).with_for_update())
    async def get(self, job_id: uuid.UUID) -> AnalysisJob | None: return await self.db.get(AnalysisJob, job_id)
    async def get_by_idempotency(self, user_id: uuid.UUID, key: str) -> AnalysisJob | None:
        return await self.db.scalar(select(AnalysisJob).options(selectinload(AnalysisJob.reports), selectinload(AnalysisJob.clarifications)).where(AnalysisJob.user_id == user_id, AnalysisJob.idempotency_key == key))
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        platforms: list[str],
        analysis_mode: str,
        idempotency_key: str,
        revision_of_job_id: uuid.UUID | None = None,
        dispatch_pending_at: datetime | None = None,
    ) -> AnalysisJob:
        job = AnalysisJob(
            user_id=user_id,
            query=query,
            platforms=platforms,
            analysis_mode=analysis_mode,
            idempotency_key=idempotency_key,
            revision_of_job_id=revision_of_job_id,
            dispatch_pending_at=dispatch_pending_at,
        )
        job.reports = []
        job.clarifications = []
        self.db.add(job)
        await self.db.flush()
        return job
    async def list_owned(self, user_id: uuid.UUID, limit: int, offset: int, status: str | None = None) -> tuple[list[AnalysisJob], int]:
        filters = [AnalysisJob.user_id == user_id];
        if status: filters.append(AnalysisJob.status == status)
        rows = list((await self.db.scalars(select(AnalysisJob).options(selectinload(AnalysisJob.reports), selectinload(AnalysisJob.clarifications)).where(*filters).order_by(AnalysisJob.created_at.desc()).limit(limit).offset(offset))).all())
        total = await self.db.scalar(select(func.count()).select_from(AnalysisJob).where(*filters)) or 0
        return rows, total
    async def save(self, job: AnalysisJob) -> AnalysisJob: await self.db.commit(); return job
    async def delete_owned(self, job: AnalysisJob) -> None: await self.db.delete(job); await self.db.commit()
    async def has_revisions(self, job_id: uuid.UUID) -> bool:
        return bool(await self.db.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.revision_of_job_id == job_id)))
    async def lease_pending_dispatches(self, cutoff: datetime, leased_at: datetime, limit: int) -> list[AnalysisJob]:
        jobs = list((await self.db.scalars(
            select(AnalysisJob)
            .where(
                AnalysisJob.status == "pending",
                AnalysisJob.arq_job_id.is_(None),
                AnalysisJob.dispatch_pending_at.is_not(None),
                AnalysisJob.dispatch_pending_at <= cutoff,
            )
            .order_by(AnalysisJob.dispatch_pending_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )).all())
        for job in jobs:
            job.dispatch_pending_at = leased_at
        return jobs
    async def lease_unclaimed_dispatches(self, cutoff: datetime, leased_at: datetime, limit: int) -> list[AnalysisJob]:
        filters = (
            AnalysisJob.status == "pending",
            AnalysisJob.arq_job_id.is_not(None),
            func.coalesce(AnalysisJob.started_at, AnalysisJob.created_at) <= cutoff,
            or_(AnalysisJob.dispatch_pending_at.is_(None), AnalysisJob.dispatch_pending_at <= cutoff),
        )
        jobs = list((await self.db.scalars(
            select(AnalysisJob).where(*filters)
            .order_by(
                func.coalesce(AnalysisJob.dispatch_pending_at, AnalysisJob.started_at, AnalysisJob.created_at),
                AnalysisJob.id,
            ).limit(limit)
            .with_for_update(skip_locked=True)
        )).all())
        leased = []
        for job in jobs:
            result = await self.db.execute(
                update(AnalysisJob)
                .where(
                    *filters, AnalysisJob.id == job.id,
                    AnalysisJob.execution_version == job.execution_version,
                    AnalysisJob.arq_job_id == job.arq_job_id,
                )
                .values(dispatch_pending_at=leased_at)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                leased.append(job)
        return leased
    async def clear_outputs(self, job_id: uuid.UUID) -> None:
        await self.db.execute(delete(EvidenceItem).where(EvidenceItem.job_id == job_id))
        await self.db.execute(delete(Report).where(Report.job_id == job_id))
    async def clear_report_outputs(self, job_id: uuid.UUID) -> None:
        await self.db.execute(delete(EvidenceItem).where(EvidenceItem.job_id == job_id))
        await self.db.execute(delete(Report).where(Report.job_id == job_id))
    async def add_event(self, job_id: uuid.UUID, event_type: str, message: str, progress: int, level: str = "info") -> JobEvent:
        event = JobEvent(job_id=job_id, event_type=event_type, message=message, progress=progress, level=level); self.db.add(event); await self.db.commit(); return event
    async def events(self, job_id: uuid.UUID) -> list[JobEvent]: return list((await self.db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.created_at))).all())
    async def clarifications(self, job_id: uuid.UUID) -> list[JobClarification]:
        return list((await self.db.scalars(select(JobClarification).where(JobClarification.job_id == job_id).order_by(JobClarification.round))).all())
    async def clarification_by_request(self, job_id: uuid.UUID, request_id: uuid.UUID) -> JobClarification | None:
        return await self.db.scalar(select(JobClarification).where(JobClarification.job_id == job_id, JobClarification.request_id == request_id))
    async def clarification_by_request_for_update(self, job_id: uuid.UUID, request_id: uuid.UUID) -> JobClarification | None:
        return await self.db.scalar(select(JobClarification).where(JobClarification.job_id == job_id, JobClarification.request_id == request_id).execution_options(populate_existing=True).with_for_update())


class UsageRepository:
    """Reserve one monthly slot per submitted job and retain measured attempt usage.

    Callers own the transaction. Worker settlement must hold the job row lock so
    two progress checkpoints cannot overwrite one another.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def lock_user(self, user_id: uuid.UUID) -> None:
        # An unchanged UPDATE serializes admissions per user on PostgreSQL, and
        # acquires SQLite's writer lock where SELECT FOR UPDATE has no effect.
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(is_active=User.is_active)
            .execution_options(synchronize_session=False)
        )

    async def reserve(self, job: AnalysisJob) -> UsageRecord:
        usage = UsageRecord(user_id=job.user_id, job_id=job.id, created_at=job.created_at)
        self.db.add(usage)
        await self.db.flush()
        return usage

    async def settle_attempt(
        self,
        job: AnalysisJob,
        attempt_id: str,
        cost: dict,
        asr_seconds: float = 0,
    ) -> UsageRecord:
        usage = await self.db.scalar(
            select(UsageRecord)
            .where(UsageRecord.job_id == job.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if usage is None:
            # Also supports pre-migration jobs and jobs created by local demos.
            usage = await self.reserve(job)
        checkpoints = dict(usage.accounted_attempts or {})
        self._apply_checkpoint(usage, checkpoints, "attempt:" + attempt_id, {
            "input_tokens": max(0, int(cost.get("input_tokens", 0) or 0)),
            "output_tokens": max(0, int(cost.get("output_tokens", 0) or 0)),
            "estimated_cost": max(0.0, float(cost.get("total_cost", cost.get("estimated_cost", 0)) or 0)),
            "asr_seconds": max(0.0, float(asr_seconds or 0)),
        })
        interaction = job.interaction_usage or {}
        self._apply_checkpoint(usage, checkpoints, "interaction", {
            "input_tokens": max(0, int(interaction.get("input_tokens", 0) or 0)),
            "output_tokens": max(0, int(interaction.get("output_tokens", 0) or 0)),
            "estimated_cost": max(0.0, float(interaction.get("estimated_cost", 0) or 0)),
            "asr_seconds": 0.0,
        })
        usage.accounted_attempts = checkpoints
        await self.db.flush()
        return usage

    @staticmethod
    def _apply_checkpoint(usage: UsageRecord, checkpoints: dict, key: str, current: dict) -> None:
        previous = checkpoints.get(key, {})
        high_water = {}
        for field, value in current.items():
            accounted = previous.get(field, 0)
            high_water[field] = max(accounted, value)
            total = (getattr(usage, field) or 0) + max(0, value - accounted)
            setattr(usage, field, round(total, 6) if field in {"estimated_cost", "asr_seconds"} else total)
        checkpoints[key] = high_water


class CandidateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _snapshot_options():
        return (
            selectinload(CandidateSnapshot.collection_snapshot),
            selectinload(CandidateSnapshot.candidates),
            selectinload(CandidateSnapshot.decision_batch)
            .selectinload(CandidateDecisionBatch.decisions),
        )

    async def get_owned_snapshot(
        self,
        snapshot_id: uuid.UUID,
        job_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> CandidateSnapshot | None:
        return await self.db.scalar(
            select(CandidateSnapshot)
            .join(AnalysisJob, AnalysisJob.id == CandidateSnapshot.job_id)
            .options(*self._snapshot_options())
            .where(
                CandidateSnapshot.id == snapshot_id,
                CandidateSnapshot.job_id == job_id,
                AnalysisJob.user_id == user_id,
            )
        )

    async def current_owned_snapshot(self, job: AnalysisJob, user_id: uuid.UUID) -> CandidateSnapshot | None:
        return await self.db.scalar(
            select(CandidateSnapshot)
            .join(AnalysisJob, AnalysisJob.id == CandidateSnapshot.job_id)
            .options(*self._snapshot_options())
            .where(
                CandidateSnapshot.job_id == job.id,
                CandidateSnapshot.source_execution_version == job.execution_version,
                AnalysisJob.user_id == user_id,
            )
        )

    async def decision_by_request(self, request_id: uuid.UUID) -> CandidateDecisionBatch | None:
        return await self.db.scalar(
            select(CandidateDecisionBatch)
            .options(
                selectinload(CandidateDecisionBatch.decisions),
                selectinload(CandidateDecisionBatch.snapshot),
            )
            .where(CandidateDecisionBatch.request_id == request_id)
        )

    async def synthesis_run(self, job_id: uuid.UUID, execution_version: int) -> CandidateSynthesisRun | None:
        return await self.db.scalar(
            select(CandidateSynthesisRun)
            .options(
                selectinload(CandidateSynthesisRun.decision_batch)
                .selectinload(CandidateDecisionBatch.decisions),
                selectinload(CandidateSynthesisRun.decision_batch)
                .selectinload(CandidateDecisionBatch.snapshot)
                .selectinload(CandidateSnapshot.collection_snapshot),
                selectinload(CandidateSynthesisRun.decision_batch)
                .selectinload(CandidateDecisionBatch.snapshot)
                .selectinload(CandidateSnapshot.candidates),
            )
            .where(
                CandidateSynthesisRun.job_id == job_id,
                CandidateSynthesisRun.execution_version == execution_version,
            )
        )

    async def latest_decision_batch(self, job_id: uuid.UUID) -> CandidateDecisionBatch | None:
        return await self.db.scalar(
            select(CandidateDecisionBatch)
            .where(CandidateDecisionBatch.job_id == job_id)
            .order_by(CandidateDecisionBatch.submitted_at.desc())
            .limit(1)
        )
class ReportRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def get_owned(self, report_id: uuid.UUID, user_id: uuid.UUID) -> Report | None:
        return await self.db.scalar(select(Report).options(selectinload(Report.evidence_items)).where(Report.id == report_id, Report.user_id == user_id))
    async def get_public(self, report_id: uuid.UUID) -> Report | None:
        return await self.db.scalar(select(Report).options(selectinload(Report.evidence_items)).where(Report.id == report_id))
    async def usage_for_job(self, job_id: uuid.UUID) -> UsageRecord | None: return await self.db.scalar(select(UsageRecord).where(UsageRecord.job_id == job_id))
    async def add_feedback(self, **values) -> None: self.db.add(ReportFeedback(**values)); await self.db.commit()
    async def add_share(self, **values) -> ShareLink: link = ShareLink(**values); self.db.add(link); await self.db.commit(); await self.db.refresh(link); return link
    async def get_share(self, token_hash: str) -> ShareLink | None: return await self.db.scalar(select(ShareLink).where(ShareLink.token_hash == token_hash))
    async def get_share_owned(self, share_id: uuid.UUID, report_id: uuid.UUID, user_id: uuid.UUID) -> ShareLink | None:
        return await self.db.scalar(select(ShareLink).where(ShareLink.id == share_id, ShareLink.report_id == report_id, ShareLink.user_id == user_id))
    async def usage_summary(self, user_id: uuid.UUID, since: datetime) -> dict:
        row = (await self.db.execute(select(func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.input_tokens), 0), func.coalesce(func.sum(UsageRecord.output_tokens), 0), func.coalesce(func.sum(UsageRecord.estimated_cost), 0.0), func.coalesce(func.sum(UsageRecord.asr_seconds), 0.0)).where(UsageRecord.user_id == user_id, UsageRecord.created_at >= since))).one()
        return {"jobs_used": row[0], "input_tokens": row[1], "output_tokens": row[2], "estimated_cost": row[3], "asr_seconds": row[4]}
