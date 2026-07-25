import hashlib
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_CANDIDATES = 8
CANDIDATE_REASON_MAX_LENGTH = 200
CANDIDATE_SNAPSHOT_VERSION = "candidate-snapshot.v1"
COLLECTION_SNAPSHOT_VERSION = "collection-snapshot.v1"

CandidateDecisionValue = Literal["undecided", "confirmed", "excluded", "uncertain"]
SubmittedCandidateDecisionValue = Literal["confirmed", "excluded", "uncertain"]


def deterministic_candidate_id(platform_account_id: str) -> str:
    identity = f"bilibili|mid:{platform_account_id}"
    return f"cand_{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


class CandidateEvidenceLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_id: str = Field(max_length=40)
    title: str = Field(max_length=300)
    source_url: str = Field(max_length=1000)


class CandidateProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str = Field(pattern=r"^cand_[a-f0-9]{24}$")
    platform: Literal["bilibili"] = "bilibili"
    platform_account_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=20)
    display_name: str = Field(max_length=200)
    profile_url: str
    source_evidence_ids: list[str] = Field(min_length=1, max_length=100)
    matched_video_count: int = Field(ge=1, le=100)
    sample_titles: list[str] = Field(min_length=1, max_length=3)
    evidence_links: list[CandidateEvidenceLink] = Field(default_factory=list, max_length=3)
    why_surfaced: list[str] = Field(min_length=1, max_length=3)
    identity_confidence: Literal["high"] = "high"
    decision: Literal["undecided"] = "undecided"

    @field_validator("profile_url")
    @classmethod
    def canonical_profile_url(cls, value: str, info):
        platform_account_id = info.data.get("platform_account_id")
        if value != f"https://space.bilibili.com/{platform_account_id}":
            raise ValueError("profile_url must match platform_account_id")
        return value
class CandidateTopicSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    topic: str = Field(min_length=1, max_length=120)
    target_content: list[str] = Field(default_factory=list, max_length=8)
    competitor_definition: str = Field(default="", max_length=500)
    time_window_days: int | None = Field(default=None, ge=1, le=3650)
    assumptions: list[str] = Field(default_factory=list, max_length=8)


class CandidateRead(CandidateProjection):
    decision: CandidateDecisionValue = "undecided"
    reason: str = Field(default="", max_length=CANDIDATE_REASON_MAX_LENGTH)


class CandidateListRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    snapshot_id: uuid.UUID
    snapshot_version: str
    topic_spec: CandidateTopicSummary
    candidates: list[CandidateRead] = Field(max_length=MAX_CANDIDATES)
    max_candidates: int = Field(default=MAX_CANDIDATES, ge=1, le=MAX_CANDIDATES)
    can_submit: bool
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CandidateDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: str = Field(pattern=r"^cand_[a-f0-9]{24}$")
    decision: SubmittedCandidateDecisionValue
    reason: str = Field(default="", max_length=CANDIDATE_REASON_MAX_LENGTH)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class CandidateDecisionSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    snapshot_id: uuid.UUID
    decisions: list[CandidateDecisionInput] = Field(min_length=1, max_length=MAX_CANDIDATES)
