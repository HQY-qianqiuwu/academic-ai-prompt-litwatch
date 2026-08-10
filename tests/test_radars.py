from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.provider_config import ProviderProfileStore, default_provider_profile
from litwatch.radar_repository import RadarRepository
from litwatch.radars import RadarScan, RadarScanStatus, RadarSpec
from litwatch.services.radars import (
    RadarNotFoundError,
    RadarProviderError,
    RadarYearRangeError,
    ResearchRadarService,
)
from litwatch.sources.registry import ProviderRegistry

NOW = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def service_for(database: Database, settings: Settings, ids: list[str]) -> ResearchRadarService:
    profile = default_provider_profile(
        openalex_base_url=settings.openalex_base_url,
        semantic_scholar_base_url=settings.semantic_scholar_base_url,
        arxiv_base_url=settings.arxiv_base_url,
        crossref_base_url=settings.crossref_base_url,
    )
    return ResearchRadarService(
        RadarRepository(database),
        ProviderRegistry.from_settings(settings),
        ProviderProfileStore([profile]),
        clock=lambda: NOW,
        id_factory=lambda: ids.pop(0),
    )


def valid_spec(**overrides: object) -> RadarSpec:
    payload: dict[str, object] = {
        "name": "Underwater TDOA Evolution",
        "topic": "underwater acoustic TDOA localization",
        "keywords": ["TDOA", "GCC-PHAT"],
        "exclude_keywords": ["terrestrial"],
        "providers": ["openalex", "arxiv", "crossref"],
        "start_year": 2018,
        "end_year": 2026,
        "recent_window_years": 2,
        "search_limit_per_period": 30,
        "enabled": True,
    }
    payload.update(overrides)
    return RadarSpec.model_validate(payload)


def test_radar_crud_disable_and_multiple_names_may_share_topic(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    service = service_for(database, settings, ["radar-a", "radar-b"])

    first = service.create(valid_spec(name="  TDOA Evolution  "))
    second = service.create(valid_spec(name="TDOA Methods"))
    updated = service.update(first.id, {"recent_window_years": 3})
    disabled = service.update(first.id, {"enabled": False})

    assert first.name == "TDOA Evolution"
    assert first.id != second.id
    assert first.topic == second.topic
    assert updated.recent_window_years == 3
    assert disabled.enabled is False
    assert service.get(first.id) == disabled
    assert {item.id for item in service.list()} == {first.id, second.id}
    database.connection.close()


def test_radar_restart_persistence_and_scan_history(tmp_path):
    settings = settings_for(tmp_path)
    first_database = Database(settings.database_path)
    service = service_for(first_database, settings, ["radar-a"])
    radar = service.create(valid_spec())
    repository = RadarRepository(first_database)
    scan = RadarScan(
        id="scan-a",
        radar_id=radar.id,
        started_at=NOW,
        heartbeat_at=NOW,
        status=RadarScanStatus.RUNNING,
        start_year=2018,
        end_year=2026,
    )
    repository.create_scan(scan)
    scan.status = RadarScanStatus.SUCCESS
    scan.finished_at = NOW
    scan.raw_count = 12
    scan.dedup_count = 10
    scan.new_count = 10
    scan.provider_status = [{"provider": "openalex", "status": "success"}]
    scan.analysis = {"annual_counts": [{"year": 2026, "count": 10}]}
    repository.update_scan(scan)
    first_database.connection.close()

    restarted = Database(settings.database_path)
    restarted_repository = RadarRepository(restarted)
    assert restarted_repository.get(radar.id) == radar
    assert restarted_repository.list_scans(radar.id) == [scan]
    assert restarted_repository.latest_successful_scan(radar.id) == scan
    restarted.connection.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_year": 2027, "end_year": 2026},
        {"start_year": 2000, "end_year": 2026},
        {"start_year": 2025, "end_year": 2026, "recent_window_years": 3},
        {"providers": []},
        {"providers": ["openalex", "openalex"]},
        {"keywords": ["TDOA", "tdoa"]},
        {"keywords": ["TDOA"], "exclude_keywords": ["tdoa"]},
        {"search_limit_per_period": 51},
    ],
)
def test_radar_spec_rejects_invalid_configuration(overrides: dict[str, object]):
    with pytest.raises(ValidationError):
        valid_spec(**overrides)


def test_radar_service_rejects_future_year_unknown_provider_and_missing_id(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    service = service_for(database, settings, ["radar-a"])

    with pytest.raises(RadarYearRangeError):
        service.create(valid_spec(start_year=2026, end_year=2027))
    with pytest.raises(RadarProviderError):
        service.create(valid_spec(providers=["not_real"]))
    with pytest.raises(RadarNotFoundError):
        service.get("missing")
    database.connection.close()


def test_radar_migration_is_idempotent_and_preserves_existing_papers(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    database.connection.execute(
        """INSERT INTO papers(
               canonical_id,title,first_seen_at,last_seen_at,normalized_title
           ) VALUES (?,?,?,?,?)""",
        ("doi:10.1000/existing", "Existing", NOW.isoformat(), NOW.isoformat(), "existing"),
    )
    database.connection.commit()
    database.connection.close()

    restarted = Database(settings.database_path)
    assert restarted.connection.execute(
        "SELECT name FROM schema_migrations WHERE version=6"
    ).fetchone()["name"] == "research_radars"
    assert restarted.connection.execute(
        "SELECT title FROM papers WHERE canonical_id='doi:10.1000/existing'"
    ).fetchone()["title"] == "Existing"
    assert restarted.connection.execute(
        "SELECT COUNT(*) AS count FROM schema_migrations WHERE version=6"
    ).fetchone()["count"] == 1
    restarted.connection.close()


def test_radar_models_forbid_secret_fields(tmp_path):
    marker = "not-a-real-radar-secret"
    payload = valid_spec().model_dump()
    payload["api_key"] = marker
    with pytest.raises(ValidationError):
        RadarSpec.model_validate(payload)

    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    service = service_for(database, settings, ["radar-a"])
    service.create(valid_spec(providers=["openalex"]))
    database.connection.close()
    assert marker.encode() not in settings.database_path.read_bytes()

