from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SubscriptionRunTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    CATCH_UP = "catch_up"


class SubscriptionRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class SubscriptionRun(BaseModel):
    id: str
    subscription_id: str
    run_key: str
    trigger: SubscriptionRunTrigger
    scheduled_for_at: datetime | None = None
    period_key: str | None = None
    started_at: datetime
    heartbeat_at: datetime
    finished_at: datetime | None = None
    status: SubscriptionRunStatus
    attempt_count: int = Field(default=1, ge=1)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    raw_count: int = Field(default=0, ge=0)
    dedup_count: int = Field(default=0, ge=0)
    duplicates_removed: int = Field(default=0, ge=0)
    historical_duplicates_removed: int = Field(default=0, ge=0)
    new_count: int = Field(default=0, ge=0)
    eligible_count: int = Field(default=0, ge=0)
    recommended_count: int = Field(default=0, ge=0)
    provider_status: list[dict[str, object]] = Field(default_factory=list)
    safe_error: str | None = None

    @field_validator(
        "scheduled_for_at",
        "started_at",
        "heartbeat_at",
        "finished_at",
        "lease_expires_at",
    )
    @classmethod
    def aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run timestamps must be timezone-aware")
        return value.astimezone(UTC)


class Recommendation(BaseModel):
    id: str
    run_id: str
    subscription_id: str
    canonical_id: str
    rank_position: int = Field(ge=1)
    rank_score: float
    relevance_score: float
    quality_score: float
    score_detail: dict[str, object] = Field(default_factory=dict)
    recommended_at: datetime

    @field_validator("recommended_at")
    @classmethod
    def recommended_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recommendation timestamp must be timezone-aware")
        return value.astimezone(UTC)
