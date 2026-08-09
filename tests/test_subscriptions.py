from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.provider_config import ProviderProfileStore, default_provider_profile
from litwatch.sources.registry import ProviderRegistry
from litwatch.web import create_app


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "TDOA Weekly",
        "topic": "underwater acoustic TDOA localization",
        "keywords": ["TDOA", "underwater acoustics"],
        "providers": ["openalex", "arxiv"],
        "search_limit": 20,
        "recommendation_limit": 5,
        "frequency": "weekly",
        "weekday": 6,
        "local_time": "08:00",
        "timezone": "Asia/Shanghai",
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def test_create_list_get_patch_and_disable_subscription(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        created_response = client.post(
            "/api/v1/subscriptions",
            json=valid_payload(name="  TDOA Weekly  ", topic="  acoustic TDOA  "),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["id"]
        assert created["name"] == "TDOA Weekly"
        assert created["topic"] == "acoustic TDOA"
        assert created["keywords"] == ["TDOA", "underwater acoustics"]
        assert created["providers"] == ["openalex", "arxiv"]
        assert created["weekday"] == 6  # Monday=0 through Sunday=6.
        assert created["last_run_at"] is None
        assert created["last_success_at"] is None
        assert created["next_run_at"] is None
        assert datetime.fromisoformat(created["created_at"]).tzinfo

        listed = client.get("/api/v1/subscriptions")
        detail = client.get(f"/api/v1/subscriptions/{created['id']}")
        patched = client.patch(
            f"/api/v1/subscriptions/{created['id']}",
            json={"recommendation_limit": 3},
        )
        disabled = client.patch(
            f"/api/v1/subscriptions/{created['id']}", json={"enabled": False}
        )

    assert listed.status_code == detail.status_code == patched.status_code == 200
    assert listed.json() == [created]
    assert detail.json() == created
    patched_payload = patched.json()
    assert patched_payload["recommendation_limit"] == 3
    for field in (
        "id",
        "name",
        "topic",
        "keywords",
        "providers",
        "search_limit",
        "frequency",
        "weekday",
        "local_time",
        "timezone",
        "created_at",
    ):
        assert patched_payload[field] == created[field]
    assert patched_payload["updated_at"] >= created["updated_at"]
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_missing_subscription_returns_404(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        get_response = client.get("/api/v1/subscriptions/not-real")
        patch_response = client.patch(
            "/api/v1/subscriptions/not-real", json={"enabled": False}
        )

    assert get_response.status_code == patch_response.status_code == 404
    assert get_response.json() == {"detail": "Subscription not found"}


@pytest.mark.parametrize(
    ("changes", "expected_fragment"),
    [
        ({"name": "   "}, "name"),
        ({"topic": "   "}, "topic"),
        ({"search_limit": 0}, "search_limit"),
        ({"search_limit": 51}, "search_limit"),
        ({"recommendation_limit": 0}, "recommendation_limit"),
        (
            {"search_limit": 5, "recommendation_limit": 6},
            "recommendation_limit",
        ),
        ({"frequency": "daily"}, "frequency"),
        ({"weekday": -1}, "weekday"),
        ({"weekday": 7}, "weekday"),
        ({"local_time": "8:00"}, "local_time"),
        ({"local_time": "24:00"}, "local_time"),
        ({"timezone": "UTC+8"}, "timezone"),
        ({"providers": []}, "providers"),
        ({"providers": ["openalex", "openalex"]}, "providers"),
    ],
)
def test_create_rejects_invalid_subscription_fields(
    tmp_path, changes: dict[str, object], expected_fragment: str
):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.post(
            "/api/v1/subscriptions", json=valid_payload(**changes)
        )

    assert response.status_code == 422
    assert expected_fragment in response.text


def test_patch_revalidates_combined_limits_and_preserves_other_fields(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        created = client.post(
            "/api/v1/subscriptions",
            json=valid_payload(search_limit=10, recommendation_limit=8),
        ).json()
        response = client.patch(
            f"/api/v1/subscriptions/{created['id']}", json={"search_limit": 5}
        )
        after = client.get(f"/api/v1/subscriptions/{created['id']}").json()

    assert response.status_code == 422
    assert "recommendation_limit" in response.text
    assert after == created


@pytest.mark.parametrize("provider", ["not_real", "ieee_xplore"])
def test_create_rejects_unknown_or_non_runnable_provider(tmp_path, provider: str):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.post(
            "/api/v1/subscriptions", json=valid_payload(providers=[provider])
        )

    assert response.status_code == 422
    assert provider in response.json()["detail"]
    assert "traceback" not in response.text.lower()


def test_create_rejects_disabled_provider(tmp_path):
    settings = settings_for(tmp_path)
    profile = default_provider_profile(
        openalex_base_url=settings.openalex_base_url,
        semantic_scholar_base_url=settings.semantic_scholar_base_url,
        arxiv_base_url=settings.arxiv_base_url,
        crossref_base_url=settings.crossref_base_url,
    )
    arxiv = profile.provider("arxiv")
    disabled_arxiv = arxiv.model_copy(
        update={"enabled": False, "default_selected": False}
    )
    profile = profile.model_copy(
        update={
            "providers": [
                disabled_arxiv if item.provider_id == "arxiv" else item
                for item in profile.providers
            ]
        }
    )
    profile_store = ProviderProfileStore([profile])
    registry = ProviderRegistry.from_settings(settings)
    app = create_app(
        settings,
        provider_registry=registry,
        provider_profile_store=profile_store,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/subscriptions", json=valid_payload(providers=["arxiv"])
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Provider 'arxiv' is disabled"}


def test_restart_persistence_and_multiple_subscriptions_may_share_topic(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/v1/subscriptions", json=valid_payload(name="TDOA Weekly")
        ).json()
        second = client.post(
            "/api/v1/subscriptions", json=valid_payload(name="TDOA Important Papers")
        ).json()

    assert first["id"] != second["id"]
    assert first["topic"] == second["topic"]

    with TestClient(create_app(settings)) as restarted_client:
        first_after_restart = restarted_client.get(
            f"/api/v1/subscriptions/{first['id']}"
        )
        listed_once = restarted_client.get("/api/v1/subscriptions").json()
        listed_twice = restarted_client.get("/api/v1/subscriptions").json()

    assert first_after_restart.status_code == 200
    assert first_after_restart.json() == first
    assert listed_once == listed_twice
    assert {item["id"] for item in listed_once} == {first["id"], second["id"]}
    assert listed_once == sorted(
        listed_once, key=lambda item: (item["created_at"], item["id"])
    )


def test_existing_database_data_survives_idempotent_subscription_migration(tmp_path):
    database_path = tmp_path / "existing.db"
    legacy = sqlite3.connect(database_path)
    legacy.executescript(
        """
        CREATE TABLE papers (
            canonical_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            abstract TEXT NOT NULL DEFAULT '',
            authors_json TEXT NOT NULL DEFAULT '[]',
            publication_date TEXT,
            venue TEXT NOT NULL DEFAULT '',
            doi TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            pdf_url TEXT NOT NULL DEFAULT '',
            is_open_access INTEGER NOT NULL DEFAULT 0,
            citation_count INTEGER NOT NULL DEFAULT 0,
            sources_json TEXT NOT NULL DEFAULT '[]',
            source_ids_json TEXT NOT NULL DEFAULT '{}',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );
        INSERT INTO papers(
            canonical_id,title,first_seen_at,last_seen_at
        ) VALUES(
            'doi:10.1000/existing','Existing paper','2026-01-01T00:00:00+00:00',
            '2026-01-01T00:00:00+00:00'
        );
        """
    )
    legacy.close()

    first = Database(database_path)
    assert first.connection.execute(
        "SELECT title FROM papers WHERE canonical_id='doi:10.1000/existing'"
    ).fetchone()["title"] == "Existing paper"
    assert first.connection.execute(
        "SELECT name FROM schema_migrations WHERE version=1"
    ).fetchone()["name"] == "subscriptions"
    first.connection.close()

    second = Database(database_path)
    assert second.connection.execute(
        "SELECT COUNT(*) AS count FROM subscriptions"
    ).fetchone()["count"] == 0
    assert second.connection.execute(
        "SELECT COUNT(*) AS count FROM schema_migrations WHERE version=1"
    ).fetchone()["count"] == 1
    assert second.connection.execute(
        "SELECT COUNT(*) AS count FROM papers"
    ).fetchone()["count"] == 1
    second.connection.close()


def test_subscription_rejects_secret_fields_and_stores_only_provider_identifiers(tmp_path):
    settings = settings_for(tmp_path)
    marker = "stage-two-fake-secret-not-real"
    with TestClient(create_app(settings)) as client:
        rejected = client.post(
            "/api/v1/subscriptions",
            json={**valid_payload(), "api_key": marker},
        )
        created = client.post(
            "/api/v1/subscriptions", json=valid_payload(providers=["openalex"])
        )

    assert rejected.status_code == 422
    assert created.status_code == 201
    raw_database = settings.database_path.read_bytes()
    assert marker.encode() not in raw_database
    assert b"OpenAlex" not in raw_database
    assert b"openalex" in raw_database


def test_openapi_contains_crud_foundation_but_no_run_or_delete_endpoint(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/subscriptions"]) == {"get", "post"}
    assert set(paths["/api/v1/subscriptions/{subscription_id}"]) == {
        "get",
        "patch",
    }
    assert set(paths["/api/v1/subscriptions/{subscription_id}/run"]) == {"post"}
