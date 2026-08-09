from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.services.literature_search import ProviderExecutionStatus
from litwatch.subscription_runs import SubscriptionRunStatus
from litwatch.web import create_app


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def test_core_pages_default_to_simplified_chinese_and_offer_english(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        pages = {
            "/": "文献检索",
            "/provider-settings": "数据源设置",
            "/subscriptions": "研究订阅",
            "/weekly-digests": "每周文献推荐",
        }
        for path, chinese_label in pages.items():
            response = client.get(path)
            assert response.status_code == 200
            assert '<html lang="zh-CN">' in response.text
            assert chinese_label in response.text
            assert '/static/i18n.js' in response.text
            assert 'data-locale="zh-CN"' in response.text
            assert 'data-locale="en"' in response.text


def test_i18n_layer_defaults_safely_and_persists_only_locale(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.get("/static/i18n.js")

    assert response.status_code == 200
    script = response.text
    assert 'const DEFAULT_LOCALE = "zh-CN"' in script
    assert 'new Set(["zh-CN", "en"])' in script
    assert 'const STORAGE_KEY = "litwatch.locale"' in script
    assert "window.localStorage.setItem(STORAGE_KEY, locale)" in script
    assert "window.location.reload()" in script
    for key in (
        "nav.search",
        "search.topic",
        "paper.abstract",
        "settings.apiKey",
        "subscriptions.runNow",
        "runs.title",
        "digest.recommended",
        "weekday.6",
    ):
        assert f'"{key}"' in script


def test_provider_brands_are_preserved_and_opt_out_of_auto_translation(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        providers = client.get("/api/v1/providers").json()
        search_script = client.get("/static/research-search.js").text
        settings_script = client.get("/static/provider-settings.js").text
        subscription_script = client.get("/static/subscriptions.js").text

    names = {item["display_name"] for item in providers}
    assert {"OpenAlex", "Semantic Scholar", "arXiv", "Crossref"} <= names
    assert 'name.setAttribute("translate", "no")' in search_script
    assert 'providerName.setAttribute("translate", "no")' in settings_script
    assert 'translate="no"' in subscription_script


def test_paper_metadata_is_rendered_from_provider_payload_without_translation(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        search_script = client.get("/static/research-search.js").text
        digest_script = client.get("/static/weekly-digests.js").text

    for expression in (
        "link.textContent = paper.title",
        "paper.authors.join",
        "paper.year",
        "paper.venue",
        "paper.abstract",
        "paper.doi",
    ):
        assert expression in search_script
    for field in ("title", "authors", "year", "venue", "abstract", "doi"):
        assert f"paper.{field}" in digest_script


def test_localization_does_not_change_backend_status_contracts():
    assert ProviderExecutionStatus.RATE_LIMITED.value == "rate_limited"
    assert SubscriptionRunStatus.PARTIAL_SUCCESS.value == "partial_success"
    i18n = Path("src/litwatch/static/i18n.js").read_text(encoding="utf-8")
    subscriptions = Path("src/litwatch/static/subscriptions.js").read_text(encoding="utf-8")
    assert '"providerStatus.rate_limited"' in i18n
    assert '"runStatus.partial_success"' in i18n
    assert "t(`runStatus.${run.status}`)" in subscriptions


def test_secret_redaction_path_remains_write_only_after_localization():
    script = Path("src/litwatch/static/provider-settings.js").read_text(encoding="utf-8")
    assert 'apiKey.type = "password"' in script
    assert 'apiKey.autocomplete = "new-password"' in script
    assert "if (apiKey.value.trim())" in script
    assert "clear_secret: true" in script
    assert "response.text()" not in script
    assert "innerHTML" not in script
