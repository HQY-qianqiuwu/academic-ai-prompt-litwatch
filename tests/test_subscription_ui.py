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


def valid_subscription() -> dict[str, object]:
    return {
        "name": "TDOA Weekly",
        "topic": "underwater acoustic TDOA localization",
        "keywords": ["TDOA"],
        "providers": ["openalex"],
        "search_limit": 10,
        "recommendation_limit": 5,
        "frequency": "weekly",
        "weekday": 6,
        "local_time": "08:00",
        "timezone": "Asia/Shanghai",
        "enabled": True,
    }


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


def test_subscription_form_accepts_radar_prefill_but_requires_manual_submit():
    script = Path("src/litwatch/static/subscriptions.js").read_text(encoding="utf-8")

    assert "prefillFromRadar" in script
    assert "new URLSearchParams(window.location.search)" in script
    assert "form.elements.topic.value = topic" in script
    assert "prefillFromRadar();" in script
    assert 'form.addEventListener("submit"' in script


def test_subscription_run_history_route_is_not_legacy_dashboard(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/v1/subscriptions", json=valid_subscription()).json()
        page = client.get(f"/subscriptions/{created['id']}/runs")
        missing = client.get("/subscriptions/not-real/runs")

    assert page.status_code == 200
    assert missing.status_code == 404
    assert f'data-subscription-id="{created["id"]}"' in page.text
    assert "TDOA Weekly" in page.text
    assert "运行历史" in page.text
    assert "/static/subscription-run-history.js" in page.text
    assert "Quick discovery" not in page.text
    assert "把新论文变成" not in page.text
    assert 'action="/quick-search"' not in page.text
    route = next(
        route
        for route in app.routes
        if route.path == "/subscriptions/{subscription_id}/runs"
    )
    assert route.name == "subscription_run_history_page"


def test_run_history_and_weekly_digest_links_have_distinct_routes():
    script = Path("src/litwatch/static/subscriptions.js").read_text(encoding="utf-8")

    assert 'href="/subscriptions/${encodeURIComponent(item.id)}/runs"' in script
    assert 'href="/weekly-digests?subscription_id=${encodeURIComponent(item.id)}"' in script
    assert 'href="/dashboard"' not in script


def test_run_history_page_uses_existing_run_api_and_safe_fields():
    script = Path("src/litwatch/static/subscription-run-history.js").read_text(
        encoding="utf-8"
    )

    assert "/api/v1/subscriptions/${encodeURIComponent(subscriptionId)}/runs" in script
    assert "/api/v1/deliveries?subscription_id=" in script
    for field in (
        "started_at",
        "finished_at",
        "status",
        "raw_count",
        "dedup_count",
        "historical_duplicates_removed",
        "new_count",
        "recommended_count",
        "provider_status",
    ):
        assert f"run.{field}" in script
    assert "safe_error" not in script
    assert "traceback" not in script.lower()


def test_legacy_dashboard_redirects_to_radars_and_is_not_run_history(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        legacy = client.get("/dashboard", follow_redirects=False)
        subscriptions = client.get("/subscriptions")

    assert legacy.status_code == 307
    assert legacy.headers["location"] == "/radars"
    assert subscriptions.status_code == 200
    assert 'href="/radars" data-i18n="nav.radar"' in subscriptions.text
    assert 'href="/dashboard" data-i18n="nav.history"' not in subscriptions.text


def test_email_settings_page_renders(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/email-settings")
    assert response.status_code == 200
    assert "email" in response.text.lower()


def test_email_settings_api_never_returns_secret(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        settings_response = client.put(
            "/api/v1/email-settings",
            json={
                "recipient_email": "me@qq.com",
                "enabled": True,
                "smtp_auth_code": "write-only-code",
            },
        )
        get_body = client.get("/api/v1/email-settings").json()
    assert settings_response.status_code == 200
    body = settings_response.json()
    assert body["recipient_email"] == "me@qq.com"
    assert body["has_auth_code"] is True
    assert "write-only-code" not in settings_response.text
    assert "write-only-code" not in str(get_body)


def test_subscription_form_has_email_toggle_and_monday_default(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        page = client.get("/subscriptions").text
    assert 'name="email_enabled"' in page
    assert 'value="0" selected' in page
    assert 'value="09:00"' in page
