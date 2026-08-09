from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.sources.registry import InMemoryCredentialStore
from litwatch.web import create_app


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def test_provider_settings_page_uses_existing_profile_api(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/provider-settings")

    assert response.status_code == 200
    assert "数据源设置" in response.text
    assert "data-provider-settings" in response.text
    assert "/static/provider-settings.js" in response.text
    assert "/static/provider-settings.css" in response.text
    assert "/static/i18n.js" in response.text
    assert 'href="/"' in response.text


def test_provider_settings_javascript_preserves_and_clears_secrets_safely(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/static/provider-settings.js")

    script = response.text
    assert 'fetch("/api/v1/providers"' in script
    assert 'fetch("/api/v1/provider-profiles"' in script
    assert 'apiKey.type = "password"' in script
    assert 'apiKey.autocomplete = "new-password"' in script
    assert "if (apiKey.value.trim())" in script
    assert "clear_secret: true" in script
    assert "window.confirm" in script
    assert "innerHTML" not in script
    assert "response.text()" not in script
    assert 't("settings.saving")' in script


def test_fake_secret_round_trip_is_write_only_and_can_be_cleared(tmp_path):
    marker = "v1-5-ui-fake-secret-not-real"
    credential_store = InMemoryCredentialStore()
    app = create_app(
        settings_for(tmp_path),
        credential_store=credential_store,
        provider_base_url_validator=lambda value: value,
    )

    with TestClient(app) as client:
        saved = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [
                    {
                        "provider_id": "semantic_scholar",
                        "api_key": marker,
                    }
                ],
            },
        )
        fetched = client.get("/api/v1/provider-profiles")
        cleared = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [
                    {
                        "provider_id": "semantic_scholar",
                        "clear_secret": True,
                    }
                ],
            },
        )

    assert saved.status_code == fetched.status_code == cleared.status_code == 200
    semantic_saved = next(
        item for item in saved.json()["providers"] if item["provider_id"] == "semantic_scholar"
    )
    semantic_cleared = next(
        item for item in cleared.json()["providers"] if item["provider_id"] == "semantic_scholar"
    )
    assert semantic_saved["credential_configured"] is True
    assert semantic_cleared["credential_configured"] is False
    for response in (saved, fetched, cleared):
        assert marker not in response.text
        assert '"api_key"' not in response.text
