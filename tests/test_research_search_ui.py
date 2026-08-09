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
    assert '/static/research-results.css' in response.text
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


def test_result_cards_preserve_backend_ranking_and_metadata(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/static/research-search.js")

    script = response.text
    assert "payload.papers.map" in script
    assert ".sort(" not in script
    assert "paper.canonical_id" in script
    assert "paper.authors.join" in script
    assert "paper.year" in script
    assert "paper.venue" in script
    assert "paper.abstract" in script
    assert "paper.sources" in script
    assert "paper.doi" in script


def test_result_cards_show_backend_scores_without_recomputing_them(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/static/research-search.js")

    script = response.text
    assert "payload.diagnostics?.ranking" in script
    assert "ranking?.rank_score" in script
    assert "ranking?.relevance_score" in script
    assert "ranking?.quality_score" in script
    assert "Metadata completeness and multi-source evidence" in script


def test_result_rendering_uses_safe_dom_and_external_links(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/static/research-search.js")

    script = response.text
    assert "innerHTML" not in script
    assert 'target = "_blank"' in script
    assert 'rel = "noopener noreferrer"' in script
    assert '["http:", "https:"]' in script
