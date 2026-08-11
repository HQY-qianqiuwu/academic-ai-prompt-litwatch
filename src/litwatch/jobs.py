from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, JsonValue, field_validator


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_BLOCKED_PAYLOAD_KEYS = {
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
}
_REFERENCE_KEYS = {"credentialreference", "credentialref"}


def validate_secret_free_payload(value: JsonValue) -> JsonValue:
    """Reject credential-bearing fields while allowing opaque references."""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(character for character in key.lower() if character.isalnum())
            if normalized not in _REFERENCE_KEYS and any(
                blocked in normalized for blocked in _BLOCKED_PAYLOAD_KEYS
            ):
                raise ValueError("job payloads must use credential references")
            validate_secret_free_payload(item)
    elif isinstance(value, list):
        for item in value:
            validate_secret_free_payload(item)
    return value


class JobRecord(BaseModel):
    job_id: str
    job_type: str
    idempotency_key: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(ge=1)
    timeout_seconds: int = Field(gt=0)
    input_hash: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    result_reference: str | None = None
    safe_error_code: str | None = None
    safe_error_message: str | None = None
    cancellation_requested_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None

    @field_validator(
        "created_at",
        "started_at",
        "finished_at",
        "heartbeat_at",
        "cancellation_requested_at",
        "lease_expires_at",
    )
    @classmethod
    def timestamps_are_aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("job timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("payload")
    @classmethod
    def payload_contains_references_not_secrets(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        validate_secret_free_payload(value)
        return value
