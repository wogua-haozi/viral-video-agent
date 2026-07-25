import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.briefing.schemas import TopicSpec


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    created_at: datetime
    is_active: bool


class JobCreate(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    platforms: list[str] = Field(default_factory=lambda: ["bilibili"])
    analysis_mode: Literal["standard", "deep"] = "standard"
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("platforms")
    @classmethod
    def bilibili_only(cls, value: list[str]) -> list[str]:
        if value != ["bilibili"]:
            raise ValueError("only bilibili is supported")
        return value


class JobRevisionCreate(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class JobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_type: str
    message: str
    progress: int
    level: str
    created_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    query: str
    platforms: list[str]
    analysis_mode: str
    status: str
    progress: int
    retry_count: int
    clarification_round: int
    execution_version: int
    revision_of_job_id: uuid.UUID | None = None
    can_retry: bool
    can_revise: bool
    can_confirm_candidates: bool
    topic_spec: TopicSpec | None = None
    interaction_usage: dict = Field(default_factory=dict)
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    report_id: uuid.UUID | None = None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    evidence_id: str
    tool: str
    source_type: str
    title: str
    source_url: str | None
    platform: str
    fetched_at: datetime
    raw_data: dict
    summary: str | None
    data_fields: dict
    transcript_segment: dict | None


class UsageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    asr_seconds: float


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    title: str
    content: str
    structured_claims: list[dict]
    status: str
    model_info: dict
    evidence: list[EvidenceRead] = Field(default_factory=list)
    usage: UsageRead | None = None
    created_at: datetime
    updated_at: datetime


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    useful: bool
    reason: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=2000)
    adopted: bool | None = None


class ShareCreate(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=90)
