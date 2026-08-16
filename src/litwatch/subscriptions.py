from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

MAX_SUBSCRIPTION_SEARCH_LIMIT = 50
PROVIDER_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")
LOCAL_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


class SubscriptionFrequency(StrEnum):
    WEEKLY = "weekly"


def _strip_required(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


def _normalize_string_list(value: object) -> object:
    if not isinstance(value, list):
        return value
    normalized: list[object] = []
    for item in value:
        normalized.append(item.strip() if isinstance(item, str) else item)
    return normalized


class SubscriptionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=500)
    keywords: list[str] = Field(default_factory=list)
    providers: list[str] = Field(min_length=1)
    search_limit: StrictInt = Field(default=10, ge=1, le=MAX_SUBSCRIPTION_SEARCH_LIMIT)
    recommendation_limit: StrictInt = Field(
        default=5, ge=1, le=MAX_SUBSCRIPTION_SEARCH_LIMIT
    )
    frequency: SubscriptionFrequency = SubscriptionFrequency.WEEKLY
    weekday: StrictInt = Field(default=0, ge=0, le=6)
    local_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    enabled: StrictBool = True
    email_enabled: StrictBool = True

    @field_validator("name", "topic", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return _strip_required(value)

    @field_validator("keywords", "providers", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> object:
        return _normalize_string_list(value)

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("keywords must not contain blank values")
        if len(value) != len(set(value)):
            raise ValueError("keywords must be unique")
        return value

    @field_validator("providers")
    @classmethod
    def validate_provider_identifiers(cls, value: list[str]) -> list[str]:
        if any(not PROVIDER_IDENTIFIER_PATTERN.fullmatch(item) for item in value):
            raise ValueError("provider identifiers must use lowercase letters and numbers")
        if len(value) != len(set(value)):
            raise ValueError("provider identifiers must be unique")
        return value

    @field_validator("local_time", mode="before")
    @classmethod
    def validate_local_time(cls, value: object) -> object:
        value = _strip_required(value)
        if isinstance(value, str) and not LOCAL_TIME_PATTERN.fullmatch(value):
            raise ValueError("local_time must use 24-hour HH:MM format")
        return value

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, value: object) -> object:
        value = _strip_required(value)
        if not isinstance(value, str) or not value:
            return value
        try:
            zone = ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone") from None
        if zone.key != value:
            raise ValueError("timezone must use its canonical IANA name")
        return value

    @model_validator(mode="after")
    def recommendation_limit_fits_search(self) -> SubscriptionSpec:
        if self.recommendation_limit > self.search_limit:
            raise ValueError("recommendation_limit must not exceed search_limit")
        return self


class Subscription(SubscriptionSpec):
    id: str
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    next_run_at: datetime | None = None

    @field_validator(
        "created_at",
        "updated_at",
        "last_run_at",
        "last_success_at",
        "next_run_at",
    )
    @classmethod
    def require_timezone_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("subscription timestamps must be timezone-aware")
        return value.astimezone(UTC)
