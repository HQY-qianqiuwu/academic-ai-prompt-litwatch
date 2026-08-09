from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.web import create_app


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def test_research_search_page_reuses_fastapi_static_stack(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'data-search-form' in response.text
    assert 'data-provider-picker' in response.text
    assert 'data-search-results' in response.text
    assert '/static/research-search.js' in response.text
    assert 'type="module"' not in response.text
    assert 'From Year' not in response.text
    assert 'To Year' not in response.text


def test_legacy_dashboard_remains_available(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'action="/quick-search"' in response.text
    assert 'data-search-form' not in response.text


def test_research_search_javascript_uses_only_litwatch_apis(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/static/research-search.js")

    assert response.status_code == 200
    assert 'fetch("/api/v1/providers"' in response.text
    assert 'fetch("/api/v1/literature/search"' in response.text
    for direct_provider in (
        "api.openalex.org",
        "api.semanticscholar.org",
        "export.arxiv.org",
        "api.crossref.org",
    ):
        assert direct_provider not in response.text


def test_search_page_contains_accessible_labels_and_navigation(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/")

    html = response.text
    assert 'for="research-topic"' in html
    assert 'for="research-limit"' in html
    assert 'aria-live="polite"' in html
    assert 'href="/provider-settings"' in html
    assert 'href="/dashboard"' in html
