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


def valid_payload() -> dict[str, object]:
    return {
        "name": "Underwater TDOA Evolution",
        "topic": "underwater acoustic TDOA localization",
        "keywords": ["TDOA", "GCC-PHAT"],
        "exclude_keywords": [],
        "providers": ["openalex"],
        "start_year": 2018,
        "end_year": 2026,
        "recent_window_years": 2,
        "search_limit_per_period": 30,
        "enabled": True,
    }


def test_radar_crud_read_apis_and_persisted_empty_analysis(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        created = client.post("/api/v1/radars", json=valid_payload())
        radar_id = created.json()["id"]
        listed = client.get("/api/v1/radars")
        detail = client.get(f"/api/v1/radars/{radar_id}")
        papers = client.get(f"/api/v1/radars/{radar_id}/papers")
        timeline = client.get(f"/api/v1/radars/{radar_id}/timeline")
        trends = client.get(f"/api/v1/radars/{radar_id}/trends")
        updated = client.patch(
            f"/api/v1/radars/{radar_id}", json={"enabled": False}
        )

    assert created.status_code == 201
    assert listed.status_code == detail.status_code == 200
    assert listed.json()[0]["paper_count"] == 0
    assert detail.json()["analysis"] == {}
    assert papers.json() == timeline.json() == trends.json() == []
    assert updated.json()["enabled"] is False


def test_radar_pages_are_bilingual_registry_driven_and_dashboard_compatible(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        home = client.get("/radars")
        create = client.get("/radars/new")
        legacy = client.get("/dashboard", follow_redirects=False)
        script = client.get("/static/radars.js")
        detail_script = client.get("/static/radar-detail.js")

    assert home.status_code == create.status_code == 200
    assert 'class="active" href="/radars"' in home.text
    assert "新建科研雷达" in home.text
    assert "data-locale=\"en\"" in home.text
    assert 'request("/api/v1/providers")' in script.text
    assert "api.openalex.org" not in script.text
    assert "analysis.annual_counts" in detail_script.text
    assert "analysis.timeline" in detail_script.text
    assert "analysis.trends" in detail_script.text
    assert legacy.status_code == 307
    assert legacy.headers["location"] == "/radars"


def test_radar_openapi_exposes_complete_read_and_scan_contract(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/radars" in paths
    assert "/api/v1/radars/{radar_id}" in paths
    assert "/api/v1/radars/{radar_id}/scan" in paths
    assert "/api/v1/radars/{radar_id}/scans" in paths
    assert "/api/v1/radars/{radar_id}/papers" in paths
    assert "/api/v1/radars/{radar_id}/timeline" in paths
    assert "/api/v1/radars/{radar_id}/trends" in paths
