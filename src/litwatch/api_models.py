"""HTTP API schemas for LitWatch literature search."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, Field, JsonValue, SecretStr, field_validator

from litwatch.models import Paper
from litwatch.provider_config import ProviderConfig, ProviderProfile, ProviderType
from litwatch.services import LiteratureSearchResult
from litwatch.sources.registry import InMemoryCredentialStore, ProviderCapability


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


class LiteratureSearchResponse(BaseModel):
    """Response envelope for a unified literature search."""

    query: str
    paper_count: int
    papers: list[LiteraturePaperResponse]

    @classmethod
    def from_result(cls, result: LiteratureSearchResult) -> LiteratureSearchResponse:
        """Serialize the service result through the explicit API contract."""
        return cls(
            query=result.query,
            paper_count=result.paper_count,
            papers=[LiteraturePaperResponse.from_paper(paper) for paper in result.papers],
        )


class ProviderCapabilityResponse(BaseModel):
    """Public capability declaration; runnable is false for future adapters."""

    provider_type: ProviderType
    display_name: str
    runnable: bool

    @classmethod
    def from_capability(cls, capability: ProviderCapability) -> ProviderCapabilityResponse:
        return cls(
            provider_type=capability.provider_type,
            display_name=capability.display_name,
            runnable=capability.runnable,
        )


class ProviderConfigWrite(BaseModel):
    """Write-only credential input paired with a safe provider configuration."""

    provider_id: str
    provider_type: ProviderType
    enabled: bool = False
    base_url: AnyHttpUrl
    requires_api_key: bool = False
    credential_reference: str | None = None
    options: dict[str, JsonValue] = Field(default_factory=dict)
    api_key: SecretStr | None = Field(default=None, json_schema_extra={"writeOnly": True})

    def to_config(self) -> ProviderConfig:
        return ProviderConfig.model_validate(
            self.model_dump(exclude={"api_key"}, mode="python")
        )


class ProviderProfileWrite(BaseModel):
    """Profile upsert request. Raw credentials are deliberately absent from responses."""

    profile_id: str = "default"
    providers: list[ProviderConfigWrite] = Field(min_length=1)

    def to_profile(self) -> ProviderProfile:
        return ProviderProfile(
            profile_id=self.profile_id,
            providers=[provider.to_config() for provider in self.providers],
        )


class ProviderConfigResponse(BaseModel):
    """Secret-free provider configuration and credential readiness state."""

    provider_id: str
    provider_type: ProviderType
    enabled: bool
    base_url: str
    requires_api_key: bool
    credential_reference: str | None
    options: dict[str, JsonValue]
    configured: bool


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
                    base_url=str(provider.base_url),
                    requires_api_key=provider.requires_api_key,
                    credential_reference=provider.credential_reference,
                    options=provider.options,
                    configured=(
                        not provider.requires_api_key
                        or credential_store.configured(provider.credential_reference)
                    ),
                )
                for provider in profile.providers
            ],
        )
