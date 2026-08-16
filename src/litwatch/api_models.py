"""HTTP API schemas for LitWatch literature search."""

from __future__ import annotations

from datetime import datetime

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    field_validator,
    model_validator,
)

from litwatch.analysis_models import EvidenceScope
from litwatch.deliveries import Delivery
from litwatch.jobs import JobPayload, JobRecord, JobStatus
from litwatch.models import Paper
from litwatch.provider_config import (
    DEFAULT_CREDENTIAL_REFERENCES,
    ProviderConfig,
    ProviderProfile,
    ProviderType,
)
from litwatch.radars import RadarSpec
from litwatch.services import (
    LiteratureSearchDiagnostics,
    LiteratureSearchResult,
    ProviderErrorCode,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services.subscription_runs import SubscriptionRunResult
from litwatch.sources.registry import InMemoryCredentialStore, ProviderCapability
from litwatch.subscription_runs import Recommendation, SubscriptionRun
from litwatch.subscriptions import Subscription, SubscriptionFrequency, SubscriptionSpec


class LiteratureSearchRequest(BaseModel):
    """Validated input for the unified literature search endpoint."""

    topic: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    providers: list[str] | None = Field(default=None, min_length=1)

    @field_validator("topic", mode="before")
    @classmethod
    def strip_topic(cls, value: object) -> object:
        """Normalize surrounding whitespace before length validation."""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("providers")
    @classmethod
    def validate_providers(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        normalized = [provider.strip() for provider in value]
        if any(not provider for provider in normalized):
            raise ValueError("provider identifiers must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("provider identifiers must be unique")
        return normalized


class JobCreateRequest(BaseModel):
    """Validated, secret-free input for a durable background job."""

    model_config = ConfigDict(extra="forbid")

    job_type: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=256)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)

    @field_validator("job_type", "idempotency_key", mode="before")
    @classmethod
    def strip_job_identifiers(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("payload")
    @classmethod
    def reject_inline_credentials(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        return JobPayload.model_validate(value).root


class PaperAnalysisJobRequest(BaseModel):
    """Public payload shape for a durable typed paper-analysis job."""

    model_config = ConfigDict(extra="forbid", strict=True)

    canonical_id: str = Field(min_length=1, max_length=1_000)
    topic_id: str = Field(min_length=1, max_length=100)
    evidence_scope: EvidenceScope = Field(strict=False)
    evidence: str | None = Field(default=None, max_length=36_000)

    @field_validator("canonical_id", "topic_id", mode="before")
    @classmethod
    def strip_identifiers(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def evidence_matches_declared_scope(self) -> PaperAnalysisJobRequest:
        if self.evidence_scope is EvidenceScope.FULLTEXT:
            raise ValueError("complete full-text analysis is not supported")
        if (
            self.evidence_scope is EvidenceScope.FULLTEXT_EXCERPT
            and not (self.evidence or "").strip()
        ):
            raise ValueError("full-text evidence is required for the declared scope")
        if (
            self.evidence_scope is not EvidenceScope.FULLTEXT_EXCERPT
            and self.evidence is not None
        ):
            raise ValueError("evidence is only accepted for a full-text scope")
        return self


class JobResponse(BaseModel):
    """Public job status projection with internal inputs and leases omitted."""

    job_id: str
    job_type: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    max_attempts: int
    result_reference: str | None
    safe_error_code: str | None
    safe_error_message: str | None
    cancellation_requested_at: datetime | None
    status_url: str

    @classmethod
    def from_record(cls, record: JobRecord) -> JobResponse:
        return cls(
            job_id=record.job_id,
            job_type=record.job_type,
            status=record.status,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            attempt=record.attempt,
            max_attempts=record.max_attempts,
            result_reference=record.result_reference,
            safe_error_code=record.safe_error_code,
            safe_error_message=record.safe_error_message,
            cancellation_requested_at=record.cancellation_requested_at,
            status_url=f"/api/v2/jobs/{record.job_id}",
        )


class JobListResponse(BaseModel):
    """Bounded page of safe job projections."""

    items: list[JobResponse]
    limit: int
    offset: int
    total: int
    has_more: bool


class RadarCreateRequest(RadarSpec):
    """Validated, secret-free Research Radar configuration."""


class RadarUpdateRequest(BaseModel):
    """Partial Radar update; the domain service validates the merged spec."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    topic: str | None = None
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    providers: list[str] | None = None
    start_year: int | None = None
    end_year: int | None = None
    recent_window_years: int | None = None
    search_limit_per_period: int | None = None
    enabled: bool | None = None


class LiteraturePaperResponse(BaseModel):
    """Stable public projection of provider-backed paper metadata."""

    canonical_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    url: str | None
    abstract: str | None
    sources: list[str]

    @classmethod
    def from_paper(cls, paper: Paper) -> LiteraturePaperResponse:
        """Project a validated Paper without inventing missing metadata."""
        return cls(
            canonical_id=paper.canonical_id,
            title=paper.title,
            authors=[author.name for author in paper.authors],
            year=paper.publication_date.year if paper.publication_date else None,
            venue=paper.venue or None,
            doi=paper.doi or None,
            url=paper.url or None,
            abstract=paper.abstract or None,
            sources=list(paper.sources),
        )


class ProviderSearchStatusResponse(BaseModel):
    """Sanitized execution diagnostics with no upstream exception text."""

    provider: str
    status: ProviderExecutionStatus
    fetched_count: int
    returned_count: int
    elapsed_ms: int
    error_code: ProviderErrorCode | None

    @classmethod
    def from_status(cls, status: ProviderSearchStatus) -> ProviderSearchStatusResponse:
        return cls.model_validate(status.model_dump())


class PaperRankingDiagnosticResponse(BaseModel):
    canonical_id: str
    rank_score: float
    relevance_score: float
    quality_score: float


class LiteratureSearchDiagnosticsResponse(BaseModel):
    raw_count: int
    dedup_count: int
    duplicates_removed: int
    candidate_limit_per_provider: int
    ranking: list[PaperRankingDiagnosticResponse]

    @classmethod
    def from_diagnostics(
        cls, diagnostics: LiteratureSearchDiagnostics
    ) -> LiteratureSearchDiagnosticsResponse:
        return cls.model_validate(diagnostics.model_dump())


class LiteratureSearchResponse(BaseModel):
    """Response envelope for a unified literature search."""

    query: str
    paper_count: int
    papers: list[LiteraturePaperResponse]
    provider_status: list[ProviderSearchStatusResponse] = Field(default_factory=list)
    diagnostics: LiteratureSearchDiagnosticsResponse

    @classmethod
    def from_result(cls, result: LiteratureSearchResult) -> LiteratureSearchResponse:
        """Serialize the service result through the explicit API contract."""
        return cls(
            query=result.query,
            paper_count=result.paper_count,
            papers=[LiteraturePaperResponse.from_paper(paper) for paper in result.papers],
            provider_status=[
                ProviderSearchStatusResponse.from_status(status)
                for status in result.provider_status
            ],
            diagnostics=LiteratureSearchDiagnosticsResponse.from_diagnostics(
                result.diagnostics
            ),
        )


class SubscriptionCreateRequest(SubscriptionSpec):
    """Create a persisted weekly research subscription."""


class SubscriptionUpdateRequest(BaseModel):
    """Partial subscription update; omitted fields remain unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    topic: str | None = None
    keywords: list[str] | None = None
    providers: list[str] | None = None
    search_limit: int | None = None
    recommendation_limit: int | None = None
    frequency: SubscriptionFrequency | None = None
    weekday: int | None = None
    local_time: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    email_enabled: bool | None = None

    @model_validator(mode="after")
    def require_non_null_changes(self) -> SubscriptionUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("at least one subscription field must be provided")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("subscription fields must not be null")
        return self


class SubscriptionResponse(BaseModel):
    """UTC, secret-free projection of persisted subscription configuration."""

    id: str
    name: str
    topic: str
    keywords: list[str]
    providers: list[str]
    search_limit: int
    recommendation_limit: int
    frequency: SubscriptionFrequency
    weekday: int
    local_time: str
    timezone: str
    enabled: bool
    email_enabled: bool
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None
    last_success_at: datetime | None
    next_run_at: datetime | None

    @classmethod
    def from_subscription(cls, subscription: Subscription) -> SubscriptionResponse:
        return cls.model_validate(subscription.model_dump())


class EmailSettingsResponse(BaseModel):
    recipient_email: str
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    has_auth_code: bool

    @classmethod
    def from_settings(cls, settings) -> EmailSettingsResponse:
        return cls(**settings.model_dump())


class EmailSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_email: str | None = None
    enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_auth_code: str | None = None


class EmailSettingsTestResponse(BaseModel):
    ok: bool
    safe_error: str | None = None


class RecommendationResponse(BaseModel):
    canonical_id: str
    rank_position: int
    rank_score: float
    relevance_score: float
    quality_score: float

    @classmethod
    def from_recommendation(cls, recommendation: Recommendation) -> RecommendationResponse:
        return cls.model_validate(
            recommendation.model_dump(
                include={
                    "canonical_id",
                    "rank_position",
                    "rank_score",
                    "relevance_score",
                    "quality_score",
                }
            )
        )


class SubscriptionRunResponse(BaseModel):
    run: SubscriptionRun
    recommendations: list[RecommendationResponse]
    delivery: Delivery | None = None

    @classmethod
    def from_result(cls, result: SubscriptionRunResult) -> SubscriptionRunResponse:
        run = result.run
        recommendations = result.recommendations
        return cls(
            run=run,
            recommendations=[
                RecommendationResponse.from_recommendation(item)
                for item in recommendations
            ],
            delivery=result.delivery,
        )


class ProviderCapabilityResponse(BaseModel):
    """Public capability declaration; runnable is false for future adapters."""

    name: str
    provider_type: ProviderType
    display_name: str
    runnable: bool
    default_selected: bool
    requires_api_key: bool
    supports_anonymous: bool
    capabilities: list[str]

    @classmethod
    def from_capability(cls, capability: ProviderCapability) -> ProviderCapabilityResponse:
        return cls(
            name=capability.provider_type.value,
            provider_type=capability.provider_type,
            display_name=capability.display_name,
            runnable=capability.runnable,
            default_selected=capability.default_selected,
            requires_api_key=capability.requires_api_key,
            supports_anonymous=capability.supports_anonymous,
            capabilities=list(capability.capabilities),
        )


class ProviderConfigWrite(BaseModel):
    """Full or partial provider update with write-only credential input."""

    provider_id: str
    provider_type: ProviderType | None = None
    enabled: bool | None = None
    default_selected: bool | None = None
    base_url: AnyHttpUrl | None = None
    requires_api_key: bool | None = None
    credential_reference: str | None = None
    options: dict[str, JsonValue] | None = None
    api_key: SecretStr | None = Field(default=None, json_schema_extra={"writeOnly": True})
    clear_secret: bool = False

    @model_validator(mode="after")
    def secret_update_is_unambiguous(self) -> ProviderConfigWrite:
        if self.api_key is not None and self.clear_secret:
            raise ValueError("api_key and clear_secret cannot be used together")
        if self.api_key is not None and not self.api_key.get_secret_value().strip():
            raise ValueError("api_key must not be blank; use clear_secret to remove it")
        return self

    @property
    def is_partial(self) -> bool:
        required = {"provider_type", "enabled", "base_url"}
        return not required.issubset(self.model_fields_set)

    def to_config(self, existing: ProviderConfig | None = None) -> ProviderConfig:
        values = existing.model_dump(mode="python") if existing is not None else {
            "provider_id": self.provider_id,
            "requires_api_key": False,
            "options": {},
        }
        values["provider_id"] = self.provider_id
        configurable_fields = {
            "provider_type",
            "enabled",
            "default_selected",
            "base_url",
            "requires_api_key",
            "credential_reference",
            "options",
        }
        for field_name in configurable_fields:
            if field_name not in self.model_fields_set:
                continue
            field_value = getattr(self, field_name)
            if field_value is None and field_name != "credential_reference":
                raise ValueError(f"{field_name} must not be null")
            values[field_name] = field_value

        if existing is not None and self.enabled is False and "default_selected" not in self.model_fields_set:
            values["default_selected"] = False

        provider_type = values.get("provider_type")
        if self.api_key is not None and not values.get("credential_reference"):
            reference = DEFAULT_CREDENTIAL_REFERENCES.get(provider_type)
            if reference:
                values["credential_reference"] = reference
        return ProviderConfig.model_validate(values)


class ProviderProfileWrite(BaseModel):
    """Profile upsert request. Raw credentials are deliberately absent from responses."""

    profile_id: str = "default"
    providers: list[ProviderConfigWrite] = Field(min_length=1)

    def to_profile(self, existing: ProviderProfile | None = None) -> ProviderProfile:
        if not any(provider.is_partial for provider in self.providers):
            return ProviderProfile(
                profile_id=self.profile_id,
                providers=[provider.to_config() for provider in self.providers],
            )
        if existing is None:
            raise ValueError("partial update requires an existing provider profile")

        merged = [provider.model_copy(deep=True) for provider in existing.providers]
        positions = {provider.provider_id: index for index, provider in enumerate(merged)}
        for update in self.providers:
            try:
                position = positions[update.provider_id]
            except KeyError:
                raise ValueError(
                    f"partial update cannot create provider {update.provider_id!r}"
                ) from None
            merged[position] = update.to_config(merged[position])
        return ProviderProfile(profile_id=self.profile_id, providers=merged)


class ProviderConfigResponse(BaseModel):
    """Secret-free provider configuration and credential readiness state."""

    provider_id: str
    provider_type: ProviderType
    enabled: bool
    default_selected: bool
    base_url: str
    requires_api_key: bool
    credential_reference: str | None
    options: dict[str, JsonValue]
    configured: bool
    credential_configured: bool


class ProviderProfileResponse(BaseModel):
    """Secret-free provider profile returned by GET and POST endpoints."""

    profile_id: str
    providers: list[ProviderConfigResponse]

    @classmethod
    def from_profile(
        cls,
        profile: ProviderProfile,
        credential_store: InMemoryCredentialStore,
    ) -> ProviderProfileResponse:
        return cls(
            profile_id=profile.profile_id,
            providers=[
                ProviderConfigResponse(
                    provider_id=provider.provider_id,
                    provider_type=provider.provider_type,
                    enabled=provider.enabled,
                    default_selected=provider.default_selected,
                    base_url=str(provider.base_url),
                    requires_api_key=provider.requires_api_key,
                    credential_reference=provider.credential_reference,
                    options=provider.options,
                    configured=(
                        not provider.requires_api_key
                        or credential_store.configured(provider.credential_reference)
                    ),
                    credential_configured=credential_store.configured(
                        provider.credential_reference
                    ),
                )
                for provider in profile.providers
            ],
        )
