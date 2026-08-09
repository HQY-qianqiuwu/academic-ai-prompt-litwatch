from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class DeliveryChannel(StrEnum):
    DASHBOARD = "dashboard"
    EMAIL = "email"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class Delivery(BaseModel):
    id: str
    run_id: str
    subscription_id: str
    channel: DeliveryChannel
    status: DeliveryStatus
    digest: dict[str, object] = Field(default_factory=dict)
    attempted_at: datetime
    delivered_at: datetime | None = None
    safe_error: str | None = None

    @field_validator("attempted_at", "delivered_at")
    @classmethod
    def aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("delivery timestamps must be timezone-aware")
        return value.astimezone(UTC)
