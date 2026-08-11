from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, JsonValue, RootModel, field_validator


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_CREDENTIAL_VALUE_FIELDS = {
    "apikey",
    "authorization",
    "cookie",
    "credentials",
    "password",
    "secret",
    "token",
}
_REFERENCE_KEYS = {"credentialreference", "credentialref"}
_REFERENCE_PATTERN = re.compile(
    r"^[a-z][a-z0-9_.-]{1,31}:[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}$"
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)^\s*(?:bearer|basic)\s+\S{8,}\s*$"),
    re.compile(r"(?i)^\s*sk-[A-Za-z0-9_-]{10,}\s*$"),
    re.compile(
        r"(?i)(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*\S+"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"^[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$"),
)


class CredentialReference(RootModel[str]):
    @field_validator("root")
    @classmethod
    def is_opaque_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not _REFERENCE_PATTERN.fullmatch(normalized):
            raise ValueError("credential reference must be an opaque namespaced reference")
        return normalized


class JobPayload(RootModel[dict[str, JsonValue]]):
    @field_validator("root")
    @classmethod
    def contains_references_not_secrets(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        _validate_payload_node(value)
        return value


def _validate_payload_node(value: JsonValue, *, field_name: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(character for character in key.lower() if character.isalnum())
            if normalized in _REFERENCE_KEYS:
                if not isinstance(item, str):
                    raise ValueError("credential reference must be a string")
                CredentialReference.model_validate(item)
            elif normalized in _CREDENTIAL_VALUE_FIELDS:
                raise ValueError("job payloads must use credential references")
            _validate_payload_node(item, field_name=normalized)
    elif isinstance(value, list):
        for item in value:
            _validate_payload_node(item, field_name=field_name)
    elif (
        isinstance(value, str)
        and field_name not in _REFERENCE_KEYS
        and any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
    ):
        raise ValueError("job payloads must use credential references")


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
        return JobPayload.model_validate(value).root
