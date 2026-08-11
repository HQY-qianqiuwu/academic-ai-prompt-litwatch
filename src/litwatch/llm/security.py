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


@dataclass(frozen=True, slots=True)
class DataEgressPolicy:
    cloud_egress_consent: bool
    fulltext_egress_consent: bool
    max_payload_chars: int

    def __post_init__(self) -> None:
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
        if payload_chars < 0:
            raise ValueError("payload_chars must be non-negative")
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
        if self.max_tokens_per_job < 1:
            raise ValueError("max_tokens_per_job must be positive")
        if not isfinite(self.max_cost_per_job) or self.max_cost_per_job <= 0:
            raise ValueError("max_cost_per_job must be finite and positive")
        if not isfinite(self.max_daily_cost) or self.max_daily_cost <= 0:
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
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens must be non-negative")
        if not isfinite(estimated_cost) or estimated_cost < 0:
            raise ValueError("estimated_cost must be finite and non-negative")
        if not isfinite(daily_spend) or daily_spend < 0:
            raise ValueError("daily_spend must be finite and non-negative")
        if active_jobs < 0:
            raise ValueError("active_jobs must be non-negative")
