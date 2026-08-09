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


def test_subscription_page_and_assets_are_served(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        page = client.get("/subscriptions")
        script = client.get("/static/subscriptions.js")
        styles = client.get("/static/subscriptions.css")

    assert page.status_code == script.status_code == styles.status_code == 200
    assert "研究订阅" in page.text
    assert "新建订阅" in page.text
    assert "/static/i18n.js" in page.text
    assert 't("subscriptions.runNow")' in script.text
    assert "/api/v1/providers" in script.text
    assert "/api/v1/subscriptions" in script.text
    assert 'button.textContent = t("subscriptions.running")' in script.text
    assert "historical_duplicates_removed" in script.text
    assert "@media (max-width:900px)" in styles.text
    assert "@media (max-width:620px)" in styles.text


def test_all_local_pages_link_to_subscriptions(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        responses = [
            client.get("/"),
            client.get("/dashboard"),
            client.get("/provider-settings"),
            client.get("/subscriptions"),
        ]

    assert all(response.status_code == 200 for response in responses)
    assert all('href="/subscriptions"' in response.text for response in responses)


def test_subscription_script_uses_safe_errors_and_prevents_duplicate_submit():
    script = Path("src/litwatch/static/subscriptions.js").read_text(encoding="utf-8")

    assert "raw traceback" not in script.lower()
    assert 't("subscriptions.unavailable")' in script
    assert 't("subscriptions.partial")' in script
    assert 't("subscriptions.runFailed")' in script
    assert 't("subscriptions.invalidSchedule")' in script
    assert "button.disabled = true" in script
    assert "button.disabled = false" in script
