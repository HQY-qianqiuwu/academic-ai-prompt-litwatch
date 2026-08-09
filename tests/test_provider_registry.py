from __future__ import annotations

import pytest

from litwatch.config import Settings
from litwatch.provider_config import ProviderConfig, ProviderType
from litwatch.sources.openalex import OpenAlexSource
from litwatch.sources.registry import (
    InMemoryCredentialStore,
    ProviderCredentialError,
    ProviderDisabledError,
    ProviderNotRunnableError,
    ProviderRegistry,
)


def provider_config(**overrides) -> ProviderConfig:
    values = {
        "provider_id": "openalex",
        "provider_type": ProviderType.OPENALEX,
        "enabled": True,
        "base_url": "https://example.test/openalex/works",
    }
    values.update(overrides)
    return ProviderConfig(**values)


def test_registry_declares_future_capabilities_without_runnable_adapters():
    registry = ProviderRegistry.from_settings(Settings())
    capabilities = {item.provider_type: item for item in registry.capabilities()}

    assert set(capabilities) == set(ProviderType)
    assert capabilities[ProviderType.OPENALEX].runnable is True
    assert capabilities[ProviderType.OPENALEX].default_selected is True
    assert capabilities[ProviderType.OPENALEX].supports_anonymous is True
    assert "search" in capabilities[ProviderType.OPENALEX].capabilities
    assert all(
        not capability.runnable
        for provider_type, capability in capabilities.items()
        if provider_type is not ProviderType.OPENALEX
    )
    assert all(
        not capability.default_selected
        for provider_type, capability in capabilities.items()
        if provider_type is not ProviderType.OPENALEX
    )


def test_registry_builds_existing_openalex_source_with_configured_url():
    registry = ProviderRegistry.from_settings(Settings(request_timeout_seconds=17))

    source = registry.build(provider_config())

    assert isinstance(source, OpenAlexSource)
    assert source.endpoint == "https://example.test/openalex/works"
    assert source.client.timeout.connect == 17


def test_registry_rejects_disabled_provider():
    registry = ProviderRegistry.from_settings(Settings())

    with pytest.raises(ProviderDisabledError, match="disabled"):
        registry.build(provider_config(enabled=False))


def test_registry_rejects_future_provider_without_fake_search():
    registry = ProviderRegistry.from_settings(Settings())
    config = provider_config(
        provider_id="semantic_scholar",
        provider_type=ProviderType.SEMANTIC_SCHOLAR,
        base_url="https://api.semanticscholar.org/graph/v1",
    )

    with pytest.raises(ProviderNotRunnableError, match="not runnable in v1.2"):
        registry.build(config)


@pytest.mark.parametrize("credential_reference", [None, "missing_default"])
def test_registry_rejects_missing_required_credential(credential_reference: str | None):
    registry = ProviderRegistry.from_settings(
        Settings(), credential_store=InMemoryCredentialStore()
    )
    config = provider_config(
        requires_api_key=True,
        credential_reference=credential_reference,
    )

    with pytest.raises(ProviderCredentialError):
        registry.build(config)


def test_registry_accepts_required_credential_by_reference_without_exposing_it():
    store = InMemoryCredentialStore({"openalex_test": "private-test-value"})
    registry = ProviderRegistry.from_settings(Settings(), credential_store=store)

    source = registry.build(
        provider_config(requires_api_key=True, credential_reference="openalex_test")
    )

    assert isinstance(source, OpenAlexSource)
    assert "private-test-value" not in repr(source.__dict__)
