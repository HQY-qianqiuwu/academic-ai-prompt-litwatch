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
        dashboard = client.get("/dashboard")

    for response in (search, settings, dashboard):
        assert response.status_code == 200
        assert "/static/local-ui.css" in response.text
        assert 'class="skip-link"' in response.text
        assert 'id="main-content"' in response.text
    assert 'href="/provider-settings"' in dashboard.text
    assert '<a href="/">Search</a>' in dashboard.text


def test_local_launcher_opens_new_root_search_page():
    launcher = Path("scripts/start-local.ps1").read_text(encoding="utf-8-sig")

    assert '$Url = "http://127.0.0.1:$Port/"' in launcher
    assert "Start-Process $Url" in launcher
    assert "dashboard" not in launcher.lower()
