from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from litwatch.models import Paper


class SubscriptionPaperStatus(StrEnum):
    SEEN = "seen"
    RECOMMENDED = "recommended"


class SubscriptionPaperHistory(BaseModel):
    subscription_id: str
    canonical_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int = Field(ge=1)
    status: SubscriptionPaperStatus
    first_recommended_at: datetime | None = None
    last_recommended_at: datetime | None = None
    recommendation_count: int = Field(default=0, ge=0)
    last_rank_score: float | None = None
    last_relevance_score: float | None = None
    last_quality_score: float | None = None
    last_run_id: int | None = None

    @field_validator(
        "first_seen_at",
        "last_seen_at",
        "first_recommended_at",
        "last_recommended_at",
    )
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("paper history timestamps must be timezone-aware")
        return value.astimezone(UTC)


class ObservationResult(BaseModel):
    """Observed papers, deterministically ordered by canonical ID."""

    new_papers: list[Paper] = Field(default_factory=list)
    seen_papers: list[Paper] = Field(default_factory=list)
    updated_papers: list[Paper] = Field(default_factory=list)

    @property
    def new_count(self) -> int:
        return len(self.new_papers)

    @property
    def seen_count(self) -> int:
        return len(self.seen_papers)

    @property
    def updated_count(self) -> int:
        return len(self.updated_papers)
