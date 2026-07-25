import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_job_user_idempotency"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ix_analysis_jobs_pending_dispatch", "status", "dispatch_pending_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text)
    platforms: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["bilibili"])
    analysis_mode: Mapped[str] = mapped_column(String(20), default="standard")
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    clarification_round: Mapped[int] = mapped_column(Integer, default=0)
    execution_version: Mapped[int] = mapped_column(Integer, default=0)
    revision_of_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analysis_jobs.id", name="fk_analysis_jobs_revision_of_job_id", ondelete="RESTRICT"), nullable=True, index=True)
    dispatch_pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    topic_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    interaction_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    arq_job_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reports: Mapped[list["Report"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    clarifications: Mapped[list["JobClarification"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    collection_snapshots: Mapped[list["CollectionSnapshot"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    candidate_snapshots: Mapped[list["CandidateSnapshot"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    @property
    def report_id(self) -> uuid.UUID | None:
        return self.reports[-1].id if self.reports else None

    @property
    def can_retry(self) -> bool:
        return self.status in {"failed", "cancelled", "partial"} and not any(
            item.status == "pending" for item in self.clarifications
        )

    @property
    def can_revise(self) -> bool:
        return self.status in {"waiting_user", "waiting_candidate_confirmation", "failed", "cancelled", "completed", "partial"}

    @property
    def can_confirm_candidates(self) -> bool:
        return self.status == "waiting_candidate_confirmation"


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    structured_claims: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    model_info: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    job: Mapped[AnalysisJob] = relationship(back_populates="reports")
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(back_populates="report")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (UniqueConstraint("job_id", "evidence_id", name="uq_evidence_job_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evidence_id: Mapped[str] = mapped_column(String(40), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=True, index=True)
    tool: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str] = mapped_column(String(32), default="bilibili")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    transcript_segment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job: Mapped[AnalysisJob] = relationship(back_populates="evidence_items")
    report: Mapped[Report | None] = relationship(back_populates="evidence_items")


class ReportFeedback(Base):
    __tablename__ = "report_feedback"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    useful: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(100), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    adopted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), unique=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    asr_seconds: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShareLink(Base):
    __tablename__ = "share_links"
    __table_args__ = (UniqueConstraint("token_hash"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    progress: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(20), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobClarification(Base):
    __tablename__ = "job_clarifications"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_job_clarifications_request_id"),
        UniqueConstraint("job_id", "round", name="uq_job_clarifications_job_round"),
        Index("ix_job_clarifications_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    options: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    allow_custom: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    selected_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custom_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job: Mapped[AnalysisJob] = relationship(back_populates="clarifications")


class CollectionSnapshot(Base):
    __tablename__ = "collection_snapshots"
    __table_args__ = (
        UniqueConstraint("job_id", "source_execution_version", name="uq_collection_snapshot_job_execution"),
        Index("ix_collection_snapshots_job_execution", "job_id", "source_execution_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    source_execution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(20), nullable=False)
    topic_spec: Mapped[dict] = mapped_column(JSON, nullable=False)
    plan: Mapped[list] = mapped_column(JSON, nullable=False)
    raw_data: Mapped[list] = mapped_column(JSON, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False)
    tool_results: Mapped[list] = mapped_column(JSON, nullable=False)
    search_queries_used: Mapped[list] = mapped_column(JSON, nullable=False)
    collection_usage: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    job: Mapped[AnalysisJob] = relationship(back_populates="collection_snapshots")
    candidate_snapshot: Mapped["CandidateSnapshot | None"] = relationship(back_populates="collection_snapshot", cascade="all, delete-orphan", uselist=False)


class CandidateSnapshot(Base):
    __tablename__ = "candidate_snapshots"
    __table_args__ = (
        UniqueConstraint("collection_snapshot_id", name="uq_candidate_snapshot_collection"),
        UniqueConstraint("job_id", "source_execution_version", name="uq_candidate_snapshot_job_execution"),
        Index("ix_candidate_snapshots_job_execution", "job_id", "source_execution_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    collection_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_snapshots.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    source_execution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    max_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    job: Mapped[AnalysisJob] = relationship(back_populates="candidate_snapshots")
    collection_snapshot: Mapped[CollectionSnapshot] = relationship(back_populates="candidate_snapshot")
    candidates: Mapped[list["CandidateAccount"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan", order_by="CandidateAccount.sort_order")
    decision_batch: Mapped["CandidateDecisionBatch | None"] = relationship(back_populates="snapshot", cascade="all, delete-orphan", uselist=False)


class CandidateAccount(Base):
    __tablename__ = "candidate_accounts"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "candidate_id", name="uq_candidate_account_snapshot_candidate"),
        UniqueConstraint("snapshot_id", "platform", "platform_account_id", name="uq_candidate_account_snapshot_identity"),
        Index("ix_candidate_accounts_snapshot_order", "snapshot_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_snapshots.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(40), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_account_id: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    profile_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    matched_video_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_titles: Mapped[list] = mapped_column(JSON, nullable=False)
    evidence_links: Mapped[list] = mapped_column(JSON, nullable=False)
    why_surfaced: Mapped[list] = mapped_column(JSON, nullable=False)
    identity_confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[CandidateSnapshot] = relationship(back_populates="candidates")
    decisions: Mapped[list["CandidateDecision"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class CandidateDecisionBatch(Base):
    __tablename__ = "candidate_decision_batches"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_candidate_decision_batches_request_id"),
        UniqueConstraint("snapshot_id", name="uq_candidate_decision_batches_snapshot_id"),
        Index("ix_candidate_decision_batches_job_id", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_snapshots.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    snapshot: Mapped[CandidateSnapshot] = relationship(back_populates="decision_batch")
    decisions: Mapped[list["CandidateDecision"]] = relationship(back_populates="batch", cascade="all, delete-orphan")
    synthesis_runs: Mapped[list["CandidateSynthesisRun"]] = relationship(back_populates="decision_batch", cascade="all, delete-orphan")


class CandidateDecision(Base):
    __tablename__ = "candidate_decisions"
    __table_args__ = (UniqueConstraint("batch_id", "candidate_account_id", name="uq_candidate_decision_batch_candidate"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_decision_batches.id", ondelete="CASCADE"), nullable=False)
    candidate_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_accounts.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    batch: Mapped[CandidateDecisionBatch] = relationship(back_populates="decisions")
    candidate: Mapped[CandidateAccount] = relationship(back_populates="decisions")


class CandidateSynthesisRun(Base):
    __tablename__ = "candidate_synthesis_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "execution_version", name="uq_candidate_synthesis_run_job_execution"),
        Index("ix_candidate_synthesis_runs_job_execution", "job_id", "execution_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    decision_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_decision_batches.id", ondelete="CASCADE"), nullable=False)
    execution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    decision_batch: Mapped[CandidateDecisionBatch] = relationship(back_populates="synthesis_runs")
