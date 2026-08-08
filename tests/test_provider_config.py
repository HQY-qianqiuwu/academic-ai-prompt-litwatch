from __future__ import annotations

import pytest
from pydantic import ValidationError

from litwatch.provider_config import (
    ProviderConfig,
    ProviderProfile,
    ProviderProfileStore,
    ProviderType,
    default_provider_profile,
)


def test_default_profile_enables_keyless_openalex():
    profile = default_provider_profile(openalex_base_url="https://api.openalex.org/works")

    provider = profile.provider("openalex")
    assert profile.profile_id == "default"
    assert provider.provider_type is ProviderType.OPENALEX
    assert provider.enabled is True
    assert provider.requires_api_key is False
    assert provider.credential_reference is None
    assert str(provider.base_url) == "https://api.openalex.org/works"


def test_profile_rejects_duplicate_provider_ids():
    provider = ProviderConfig(
        provider_id="openalex",
        provider_type=ProviderType.OPENALEX,
        enabled=True,
        base_url="https://api.openalex.org/works",
    )

    with pytest.raises(ValidationError, match="provider_id values must be unique"):
        ProviderProfile(providers=[provider, provider])


@pytest.mark.parametrize("option_name", ["api_key", "access-token", "clientSecret"])
def test_provider_options_reject_credential_like_fields(option_name: str):
    with pytest.raises(ValidationError, match="use credential_reference"):
        ProviderConfig(
            provider_id="future",
            provider_type=ProviderType.SEMANTIC_SCHOLAR,
            base_url="https://api.semanticscholar.org/graph/v1",
            options={option_name: "must-not-be-stored-here"},
        )


def test_profile_store_returns_defensive_copies():
    original = default_provider_profile(openalex_base_url="https://api.openalex.org/works")
    store = ProviderProfileStore([original])

    retrieved = store.get("default")
    retrieved.providers[0].enabled = False

    assert store.get("default").providers[0].enabled is True
