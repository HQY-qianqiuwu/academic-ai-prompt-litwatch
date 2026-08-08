"""Safe, serializable configuration models for literature providers."""

from __future__ import annotations

import re
from enum import StrEnum

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
    """Provider capabilities known to v1.2.

    Only OpenAlex has a runnable adapter in this release. The remaining values
    reserve stable configuration identifiers without pretending they can search.
    """

    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    CROSSREF = "crossref"
    IEEE_XPLORE = "ieee_xplore"
    SCOPUS = "scopus"
    WEB_OF_SCIENCE = "web_of_science"


class ProviderConfig(BaseModel):
    """Public provider configuration containing references, never raw credentials."""

    provider_id: str = Field(pattern=PROVIDER_ID_PATTERN)
    provider_type: ProviderType
    enabled: bool = False
    base_url: AnyHttpUrl
    requires_api_key: bool = False
    credential_reference: str | None = Field(default=None, pattern=PROVIDER_ID_PATTERN)
    options: dict[str, JsonValue] = Field(default_factory=dict)

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


def default_provider_profile(*, openalex_base_url: str) -> ProviderProfile:
    """Build the backward-compatible profile used when callers specify no providers."""
    return ProviderProfile(
        providers=[
            ProviderConfig(
                provider_id="openalex",
                provider_type=ProviderType.OPENALEX,
                enabled=True,
                base_url=openalex_base_url,
                requires_api_key=False,
            )
        ]
    )
