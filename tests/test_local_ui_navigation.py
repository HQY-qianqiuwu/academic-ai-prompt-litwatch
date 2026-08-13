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


def test_dynamic_pages_have_consistent_navigation_and_skip_links(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        search = client.get("/")
        settings = client.get("/provider-settings")
        radar = client.get("/radars")
        analysis = client.get("/analysis")
        jobs = client.get("/jobs")

    expected_navigation = (
        'href="/" data-i18n="nav.search"',
        'href="/analysis" data-i18n="nav.analysis"',
        'href="/jobs" data-i18n="nav.jobs"',
        'href="/radars" data-i18n="nav.radar"',
        'href="/subscriptions" data-i18n="nav.subscriptions"',
        'href="/weekly-digests" data-i18n="nav.digests"',
        'href="/provider-settings" data-i18n="nav.settings"',
    )
    for response in (search, settings, radar, analysis, jobs):
        assert response.status_code == 200
        assert "/static/local-ui.css" in response.text
        assert 'class="skip-link"' in response.text
        assert 'id="main-content"' in response.text
        assert "http://localhost" not in response.text
        for link in expected_navigation:
            assert link in response.text
    assert 'href="/provider-settings"' in radar.text
    assert "data-analysis-form" in analysis.text
    assert "/static/analysis-workspace.js" in analysis.text
    assert "data-jobs-list" in jobs.text
    assert "/static/jobs-workspace.js" in jobs.text


def test_job_workspace_lists_safe_records_created_by_the_paper_analysis_api(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        created = client.post(
            "/api/v2/jobs",
            json={
                "job_type": "paper_analysis",
                "idempotency_key": "analysis:ui:paper-1",
                "payload": {
                    "canonical_id": "doi:10.1000/ui-paper",
                    "topic_id": "ui-topic",
                    "evidence_scope": "metadata_only",
                },
            },
        )
        listed = client.get("/api/v2/jobs")

    assert created.status_code == 202
    assert listed.status_code == 200
    assert listed.json()[0]["job_id"] == created.json()["job_id"]
    assert listed.json()[0]["status_url"] == created.json()["status_url"]
    assert "payload" not in listed.json()[0]
    assert "idempotency_key" not in listed.json()[0]


def test_local_launcher_opens_new_root_search_page():
    launcher = Path("scripts/start-local.ps1").read_text(encoding="utf-8-sig")

    assert '$Url = "http://127.0.0.1:$Port/"' in launcher
    assert "Start-Process $Url" in launcher
    assert "dashboard" not in launcher.lower()
