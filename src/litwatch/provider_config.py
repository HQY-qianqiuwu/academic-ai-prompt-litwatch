"""Safe, serializable configuration models for literature providers."""

from __future__ import annotations

import re
from enum import StrEnum
from threading import RLock

from pydantic import AnyHttpUrl, BaseModel, Field, JsonValue, field_validator, model_validator

PROVIDER_ID_PATTERN = r"[a-z0-9][a-z0-9_-]*"
SECRET_OPTION_TERMS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
)


class ProviderType(StrEnum):
    """Provider capabilities known to the configuration layer.

    The first four values have v1.3 adapters. Remaining values reserve stable
    configuration identifiers without pretending they can search.
    """

    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    CROSSREF = "crossref"
    IEEE_XPLORE = "ieee_xplore"
    SCOPUS = "scopus"
    WEB_OF_SCIENCE = "web_of_science"


DEFAULT_CREDENTIAL_REFERENCES = {
    ProviderType.SEMANTIC_SCHOLAR: "semantic_scholar_default",
    ProviderType.IEEE_XPLORE: "ieee_xplore_default",
}


class ProviderConfig(BaseModel):
    """Public provider configuration containing references, never raw credentials."""

    provider_id: str = Field(pattern=PROVIDER_ID_PATTERN)
    provider_type: ProviderType
    enabled: bool = False
    default_selected: bool = False
    base_url: AnyHttpUrl
    requires_api_key: bool = False
    credential_reference: str | None = Field(default=None, pattern=PROVIDER_ID_PATTERN)
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_default_selection(cls, value):
        """Treat an omitted v1.3 field exactly like the v1.2 enabled flag."""
        if isinstance(value, dict) and "default_selected" not in value:
            value = {**value, "default_selected": bool(value.get("enabled", False))}
        return value

    @field_validator("options")
    @classmethod
    def reject_secret_options(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Keep credentials out of serializable provider options."""
        for key in value:
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if any(term in normalized_key for term in SECRET_OPTION_TERMS):
                raise ValueError(
                    f"provider option {key!r} may contain a secret; use credential_reference"
                )
        return value

    @model_validator(mode="after")
    def default_provider_must_be_enabled(self) -> ProviderConfig:
        if self.default_selected and not self.enabled:
            raise ValueError("default-selected provider must be enabled")
        return self


class ProviderProfile(BaseModel):
    """Named collection of provider configurations selected as one search profile."""

    profile_id: str = Field(default="default", pattern=PROVIDER_ID_PATTERN)
    providers: list[ProviderConfig]

    @model_validator(mode="after")
    def provider_ids_are_unique(self) -> ProviderProfile:
        provider_ids = [provider.provider_id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider_id values must be unique within a profile")
        return self

    def provider(self, provider_id: str) -> ProviderConfig:
        """Return one configured provider or raise a precise lookup error."""
        for provider in self.providers:
            if provider.provider_id == provider_id:
                return provider
        raise KeyError(provider_id)


def default_provider_profile(
    *,
    openalex_base_url: str,
    semantic_scholar_base_url: str = (
        "https://api.semanticscholar.org"
    ),
    arxiv_base_url: str = "https://export.arxiv.org/api/query",
    crossref_base_url: str = "https://api.crossref.org/v1/works",
) -> ProviderProfile:
    """Build the backward-compatible profile used when callers specify no providers."""
    return ProviderProfile(
        providers=[
            ProviderConfig(
                provider_id="openalex",
                provider_type=ProviderType.OPENALEX,
                enabled=True,
                default_selected=True,
                base_url=openalex_base_url,
                requires_api_key=False,
            ),
            ProviderConfig(
                provider_id="semantic_scholar",
                provider_type=ProviderType.SEMANTIC_SCHOLAR,
                enabled=True,
                default_selected=False,
                base_url=semantic_scholar_base_url,
                requires_api_key=False,
                credential_reference="semantic_scholar_default",
            ),
            ProviderConfig(
                provider_id="arxiv",
                provider_type=ProviderType.ARXIV,
                enabled=True,
                default_selected=False,
                base_url=arxiv_base_url,
                requires_api_key=False,
            ),
            ProviderConfig(
                provider_id="crossref",
                provider_type=ProviderType.CROSSREF,
                enabled=True,
                default_selected=False,
                base_url=crossref_base_url,
                requires_api_key=False,
            ),
        ]
    )


class ProviderProfileStore:
    """Thread-safe, process-local storage for non-secret provider profiles."""

    def __init__(self, profiles: list[ProviderProfile]) -> None:
        if not profiles:
            raise ValueError("at least one provider profile is required")
        self._lock = RLock()
        self._profiles: dict[str, ProviderProfile] = {}
        for profile in profiles:
            self.upsert(profile)

    def list(self) -> list[ProviderProfile]:
        with self._lock:
            return [profile.model_copy(deep=True) for profile in self._profiles.values()]

    def get(self, profile_id: str) -> ProviderProfile:
        with self._lock:
            try:
                return self._profiles[profile_id].model_copy(deep=True)
            except KeyError:
                raise KeyError(profile_id) from None

    def upsert(self, profile: ProviderProfile) -> ProviderProfile:
        safe_copy = profile.model_copy(deep=True)
        with self._lock:
            self._profiles[profile.profile_id] = safe_copy
        return safe_copy.model_copy(deep=True)
