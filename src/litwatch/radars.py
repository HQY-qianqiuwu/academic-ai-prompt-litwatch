from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from litwatch.models import Paper

MIN_RADAR_YEAR = 1900
MAX_RADAR_YEAR = 2100
MAX_RADAR_RANGE_YEARS = 20
MAX_RADAR_SEARCH_LIMIT = 50
PROVIDER_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _strip_required(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _normalize_string_list(value: object) -> object:
    if not isinstance(value, list):
        return value
    return [item.strip() if isinstance(item, str) else item for item in value]


class RadarSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=500)
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    providers: list[str] = Field(min_length=1)
    start_year: StrictInt = Field(ge=MIN_RADAR_YEAR, le=MAX_RADAR_YEAR)
    end_year: StrictInt = Field(ge=MIN_RADAR_YEAR, le=MAX_RADAR_YEAR)
    recent_window_years: StrictInt = Field(default=2, ge=1, le=5)
    search_limit_per_period: StrictInt = Field(
        default=30, ge=1, le=MAX_RADAR_SEARCH_LIMIT
    )
    enabled: StrictBool = True

    @field_validator("name", "topic", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return _strip_required(value)

    @field_validator("keywords", "exclude_keywords", "providers", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return _normalize_string_list(value)

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def validate_phrases(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("keyword lists must not contain blank values")
        normalized = [item.casefold() for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("keyword lists must contain unique values")
        return value

    @field_validator("providers")
    @classmethod
    def validate_provider_identifiers(cls, value: list[str]) -> list[str]:
        if any(not PROVIDER_IDENTIFIER_PATTERN.fullmatch(item) for item in value):
            raise ValueError("provider identifiers must use lowercase letters and numbers")
        if len(value) != len(set(value)):
            raise ValueError("provider identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_range_and_phrases(self) -> RadarSpec:
        range_years = self.end_year - self.start_year + 1
        if range_years < 1:
            raise ValueError("start_year must not be after end_year")
        if range_years > MAX_RADAR_RANGE_YEARS:
            raise ValueError(f"Radar year range must not exceed {MAX_RADAR_RANGE_YEARS} years")
        if self.recent_window_years > range_years:
            raise ValueError("recent_window_years must fit within the Radar year range")
        included = {item.casefold() for item in self.keywords}
        excluded = {item.casefold() for item in self.exclude_keywords}
        if included & excluded:
            raise ValueError("keywords and exclude_keywords must not overlap")
        return self


class ResearchRadar(RadarSpec):
    id: str
    created_at: datetime
    updated_at: datetime
    last_scan_at: datetime | None = None
    last_success_at: datetime | None = None

    @field_validator("created_at", "updated_at", "last_scan_at", "last_success_at")
    @classmethod
    def require_aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Radar timestamps must be timezone-aware")
        return value.astimezone(UTC)


class RadarScanStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RadarScan(BaseModel):
    id: str
    radar_id: str
    started_at: datetime
    heartbeat_at: datetime
    finished_at: datetime | None = None
    status: RadarScanStatus
    start_year: int
    end_year: int
    raw_count: int = Field(default=0, ge=0)
    dedup_count: int = Field(default=0, ge=0)
    new_count: int = Field(default=0, ge=0)
    provider_status: list[dict[str, object]] = Field(default_factory=list)
    analysis: dict[str, object] = Field(default_factory=dict)
    safe_error: str | None = None

    @field_validator("started_at", "heartbeat_at", "finished_at")
    @classmethod
    def require_aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Radar scan timestamps must be timezone-aware")
        return value.astimezone(UTC)


class RadarPaper(BaseModel):
    radar_id: str
    canonical_id: str
    first_seen_at: datetime
    last_seen_at: datetime
    first_scan_id: str
    last_scan_id: str
    publication_year: int | None = None
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    representative_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RadarObservationResult(BaseModel):
    new_papers: list[Paper] = Field(default_factory=list)
    seen_papers: list[Paper] = Field(default_factory=list)
    updated_papers: list[Paper] = Field(default_factory=list)
