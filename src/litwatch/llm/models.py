from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMErrorCode(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION = "authentication"
    UPSTREAM = "upstream"
    PARSE = "parse"
    VALIDATION = "validation"


class LLMGatewayError(RuntimeError):
    """Normalized error that never contains provider response or credential data."""

    def __init__(
        self,
        code: LLMErrorCode,
        safe_message: str,
        *,
        attempts: int = 1,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.attempts = attempts


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=200)
    system_instruction: str = Field(min_length=1, max_length=20_000)
    user_instruction: str = Field(default="", max_length=20_000)
    untrusted_evidence: str = Field(default="", max_length=200_000)
    provider_kind: Literal["local", "cloud"]
    evidence_scope: Literal[
        "metadata_only", "abstract", "fulltext_excerpt", "fulltext", "notes"
    ]
    max_output_tokens: int = Field(default=2_048, ge=1, le=100_000)
    temperature: float = Field(default=0, ge=0, le=2)

    @field_validator("model", "system_instruction", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def payload_chars(self) -> int:
        """Count all caller-provided text that may leave the local runtime."""
        return len(self.user_instruction) + len(self.untrusted_evidence)


class LLMUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LLMResponse(BaseModel):
    content: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    provider_request_id: str | None = None
    model: str | None = None


class LLMBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_cost_per_million: float = Field(
        default=0, ge=0, allow_inf_nan=False, strict=True
    )
    output_cost_per_million: float = Field(
        default=0, ge=0, allow_inf_nan=False, strict=True
    )
    estimated_tokens: int = Field(ge=0, strict=True)
    estimated_cost: float = Field(ge=0, allow_inf_nan=False, strict=True)
    daily_spend: float = Field(ge=0, allow_inf_nan=False, strict=True)
    active_jobs: int = Field(ge=0, strict=True)


StructuredValue = TypeVar("StructuredValue", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class LLMResult(Generic[StructuredValue]):
    value: StructuredValue
    usage: LLMUsage
    cost_usd: float
    provider_request_id: str | None
    model: str | None
