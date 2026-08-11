from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class LLMSecurityErrorCode(StrEnum):
    CLOUD_CONSENT_REQUIRED = "cloud_consent_required"
    FULLTEXT_CONSENT_REQUIRED = "fulltext_consent_required"
    PAYLOAD_LIMIT_EXCEEDED = "payload_limit_exceeded"
    TOKEN_LIMIT_EXCEEDED = "token_limit_exceeded"
    JOB_COST_LIMIT_EXCEEDED = "job_cost_limit_exceeded"
    DAILY_COST_LIMIT_EXCEEDED = "daily_cost_limit_exceeded"
    CONCURRENCY_LIMIT_EXCEEDED = "concurrency_limit_exceeded"


class LLMSecurityError(RuntimeError):
    """Safe policy rejection suitable for API and persisted job errors."""

    def __init__(self, code: LLMSecurityErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code


_PROVIDER_KINDS = frozenset({"local", "cloud"})
_EVIDENCE_SCOPES = frozenset(
    {"metadata_only", "abstract", "fulltext_excerpt", "fulltext", "notes"}
)
_FULLTEXT_SCOPES = frozenset({"fulltext_excerpt", "fulltext", "notes"})


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_finite_nonnegative_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite non-negative number")
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0:
        raise ValueError(f"{field_name} must be a finite non-negative number")
    return numeric


@dataclass(frozen=True, slots=True)
class DataEgressPolicy:
    cloud_egress_consent: bool
    fulltext_egress_consent: bool
    max_payload_chars: int

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.max_payload_chars, "max_payload_chars")
        if self.max_payload_chars < 1:
            raise ValueError("max_payload_chars must be positive")

    def authorize(
        self,
        provider_kind: str,
        evidence_scope: str,
        payload_chars: int,
    ) -> None:
        if provider_kind not in _PROVIDER_KINDS:
            raise ValueError("provider_kind must be 'local' or 'cloud'")
        if evidence_scope not in _EVIDENCE_SCOPES:
            raise ValueError("evidence_scope is not supported")
        _require_nonnegative_int(payload_chars, "payload_chars")
        if payload_chars > self.max_payload_chars:
            raise LLMSecurityError(
                LLMSecurityErrorCode.PAYLOAD_LIMIT_EXCEEDED,
                "LLM data payload exceeds the configured limit",
            )
        if provider_kind == "local":
            return
        if not self.cloud_egress_consent:
            raise LLMSecurityError(
                LLMSecurityErrorCode.CLOUD_CONSENT_REQUIRED,
                "Cloud LLM data egress is not authorized",
            )
        if evidence_scope in _FULLTEXT_SCOPES and not self.fulltext_egress_consent:
            raise LLMSecurityError(
                LLMSecurityErrorCode.FULLTEXT_CONSENT_REQUIRED,
                "Cloud full-text data egress is not authorized",
            )


@dataclass(frozen=True, slots=True)
class CostGuard:
    max_tokens_per_job: int
    max_cost_per_job: float
    max_daily_cost: float
    max_concurrent_llm_jobs: int

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.max_tokens_per_job, "max_tokens_per_job")
        _require_nonnegative_int(
            self.max_concurrent_llm_jobs, "max_concurrent_llm_jobs"
        )
        max_job_cost = _require_finite_nonnegative_number(
            self.max_cost_per_job, "max_cost_per_job"
        )
        max_daily_cost = _require_finite_nonnegative_number(
            self.max_daily_cost, "max_daily_cost"
        )
        if self.max_tokens_per_job < 1:
            raise ValueError("max_tokens_per_job must be positive")
        if max_job_cost <= 0:
            raise ValueError("max_cost_per_job must be finite and positive")
        if max_daily_cost <= 0:
            raise ValueError("max_daily_cost must be finite and positive")
        if self.max_concurrent_llm_jobs < 1:
            raise ValueError("max_concurrent_llm_jobs must be positive")

    def authorize(
        self,
        estimated_tokens: int,
        estimated_cost: float,
        daily_spend: float,
        active_jobs: int,
    ) -> None:
        self._validate_measurements(
            estimated_tokens=estimated_tokens,
            estimated_cost=estimated_cost,
            daily_spend=daily_spend,
            active_jobs=active_jobs,
        )
        if estimated_tokens > self.max_tokens_per_job:
            raise LLMSecurityError(
                LLMSecurityErrorCode.TOKEN_LIMIT_EXCEEDED,
                "LLM token estimate exceeds the per-job limit",
            )
        if estimated_cost > self.max_cost_per_job:
            raise LLMSecurityError(
                LLMSecurityErrorCode.JOB_COST_LIMIT_EXCEEDED,
                "LLM cost estimate exceeds the per-job limit",
            )
        if daily_spend + estimated_cost > self.max_daily_cost:
            raise LLMSecurityError(
                LLMSecurityErrorCode.DAILY_COST_LIMIT_EXCEEDED,
                "LLM cost estimate exceeds the daily limit",
            )
        if active_jobs >= self.max_concurrent_llm_jobs:
            raise LLMSecurityError(
                LLMSecurityErrorCode.CONCURRENCY_LIMIT_EXCEEDED,
                "LLM concurrency limit has been reached",
            )

    @staticmethod
    def _validate_measurements(
        *,
        estimated_tokens: int,
        estimated_cost: float,
        daily_spend: float,
        active_jobs: int,
    ) -> None:
        _require_nonnegative_int(estimated_tokens, "estimated_tokens")
        _require_finite_nonnegative_number(estimated_cost, "estimated_cost")
        _require_finite_nonnegative_number(daily_spend, "daily_spend")
        _require_nonnegative_int(active_jobs, "active_jobs")
