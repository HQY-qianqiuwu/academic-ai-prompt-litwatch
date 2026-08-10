from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.models import Paper
from litwatch.provider_config import ProviderProfileStore, default_provider_profile
from litwatch.radar_repository import RadarRepository
from litwatch.radars import RadarScan, RadarScanStatus, RadarSpec
from litwatch.services.literature_search import (
    AllProvidersFailedError,
    LiteratureSearchDiagnostics,
    LiteratureSearchResult,
    ProviderErrorCode,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services.radars import ResearchRadarService
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


def paper(identifier: str, year: int, *, title: str | None = None) -> Paper:
    return Paper(
        canonical_id=f"doi:10.1000/{identifier}",
        title=title or f"Paper {identifier}",
        publication_date=date(year, 6, 1),
        sources=["openalex"],
        score=0.8,
        score_detail={
            "rank_score": 0.8,
            "relevance_score": 0.75,
            "quality_score": 0.9,
        },
    )


def result(
    papers: list[Paper],
    *,
    statuses: list[ProviderSearchStatus] | None = None,
    raw_count: int | None = None,
) -> LiteratureSearchResult:
    return LiteratureSearchResult(
        query="underwater acoustic localization",
        papers=papers,
        provider_status=statuses
        or [
            ProviderSearchStatus(
                provider="openalex",
                status=ProviderExecutionStatus.SUCCESS,
                fetched_count=len(papers),
                returned_count=len(papers),
            )
        ],
        diagnostics=LiteratureSearchDiagnostics(
            raw_count=raw_count if raw_count is not None else len(papers),
            dedup_count=len(papers),
        ),
    )


class FakeHistoricalSearch:
    def __init__(self, responses: list[LiteratureSearchResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> LiteratureSearchResult:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def radar_service(
    database: Database,
    settings: Settings,
    search: FakeHistoricalSearch,
    ids: list[str],
) -> ResearchRadarService:
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
        search_service=search,  # type: ignore[arg-type]
        clock=lambda: NOW,
        id_factory=lambda: ids.pop(0),
    )


def spec(**overrides: object) -> RadarSpec:
    payload: dict[str, object] = {
        "name": "TDOA Evolution",
        "topic": "underwater acoustic TDOA localization",
        "providers": ["openalex"],
        "start_year": 2020,
        "end_year": 2020,
        "recent_window_years": 1,
        "search_limit_per_period": 30,
    }
    payload.update(overrides)
    return RadarSpec.model_validate(payload)


def test_historical_backfill_uses_deterministic_two_year_periods(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    search = FakeHistoricalSearch([result([]) for _ in range(5)])
    service = radar_service(database, settings, search, ["radar", "scan"])
    radar = service.create(spec(start_year=2018, end_year=2026))

    completed = service.scan(radar.id)

    assert completed.scan.status is RadarScanStatus.SUCCESS
    assert [
        (call["start_date"], call["end_date"]) for call in search.calls
    ] == [
        (date(2018, 1, 1), date(2019, 12, 31)),
        (date(2020, 1, 1), date(2021, 12, 31)),
        (date(2022, 1, 1), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 12, 31)),
    ]
    assert all(call["providers"] == ["openalex"] for call in search.calls)
    assert all(call["limit"] == 30 for call in search.calls)
    database.connection.close()


def test_radar_rescan_counts_only_new_canonical_ids(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    first_papers = [paper(identifier, 2020) for identifier in "ABC"]
    second_papers = [paper(identifier, 2020) for identifier in "ABCDE"]
    search = FakeHistoricalSearch([result(first_papers), result(second_papers)])
    service = radar_service(database, settings, search, ["radar", "scan-1", "scan-2"])
    radar = service.create(spec())

    first = service.scan(radar.id)
    second = service.scan(radar.id)

    assert first.scan.new_count == 3
    assert first.new_canonical_ids == [f"doi:10.1000/{item}" for item in "abc"]
    assert second.scan.new_count == 2
    assert second.new_canonical_ids == [f"doi:10.1000/{item}" for item in "de"]
    assert second.seen_canonical_ids == [f"doi:10.1000/{item}" for item in "abc"]
    assert database.connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 5
    assert database.connection.execute("SELECT COUNT(*) FROM radar_papers").fetchone()[0] == 5
    assert database.connection.execute("SELECT COUNT(*) FROM subscription_papers").fetchone()[0] == 0
    database.connection.close()


def test_partial_provider_failure_persists_papers_and_safe_diagnostics(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    statuses = [
        ProviderSearchStatus(
            provider="openalex", status=ProviderExecutionStatus.SUCCESS, fetched_count=1
        ),
        ProviderSearchStatus(
            provider="semantic_scholar",
            status=ProviderExecutionStatus.RATE_LIMITED,
            error_code=ProviderErrorCode.UPSTREAM_429,
        ),
    ]
    search = FakeHistoricalSearch([result([paper("A", 2020)], statuses=statuses)])
    service = radar_service(database, settings, search, ["radar", "scan"])
    radar = service.create(spec(providers=["openalex", "semantic_scholar"]))

    completed = service.scan(radar.id)

    assert completed.scan.status is RadarScanStatus.PARTIAL_SUCCESS
    assert completed.scan.new_count == 1
    assert {item["filtering_mode"] for item in completed.scan.provider_status} == {
        "provider_side"
    }
    serialized = completed.scan.model_dump_json()
    assert "upstream_429" in serialized
    assert "api_key" not in serialized.casefold()
    database.connection.close()


def test_all_provider_failure_keeps_previous_success_and_creates_no_fake_data(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    failure = AllProvidersFailedError(
        [
            ProviderSearchStatus(
                provider="openalex",
                status=ProviderExecutionStatus.TIMEOUT,
                error_code=ProviderErrorCode.TIMEOUT,
            )
        ]
    )
    search = FakeHistoricalSearch([result([paper("A", 2020)]), failure])
    service = radar_service(database, settings, search, ["radar", "scan-1", "scan-2"])
    radar = service.create(spec())
    success = service.scan(radar.id)
    successful_at = service.get(radar.id).last_success_at

    failed = service.scan(radar.id)

    assert success.scan.status is RadarScanStatus.SUCCESS
    assert failed.scan.status is RadarScanStatus.FAILED
    assert failed.scan.safe_error == "all_providers_failed"
    assert failed.scan.analysis == {}
    assert service.get(radar.id).last_success_at == successful_at
    assert RadarRepository(database).latest_successful_scan(radar.id) == success.scan
    database.connection.close()


def test_stale_running_scan_is_recovered_once(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    search = FakeHistoricalSearch([])
    service = radar_service(database, settings, search, ["radar"])
    radar = service.create(spec())
    stale = RadarScan(
        id="stale",
        radar_id=radar.id,
        started_at=NOW - timedelta(hours=2),
        heartbeat_at=NOW - timedelta(hours=2),
        status=RadarScanStatus.RUNNING,
        start_year=2020,
        end_year=2020,
    )
    repository = RadarRepository(database)
    repository.create_scan(stale)

    assert service.recover_stale_scans(timeout_seconds=900) == 1
    assert service.recover_stale_scans(timeout_seconds=900) == 0
    recovered = repository.get_scan(stale.id)
    assert recovered is not None
    assert recovered.status is RadarScanStatus.INTERRUPTED
    assert recovered.safe_error == "interrupted"
    database.connection.close()


def test_successful_scan_persists_annual_and_keyword_analysis(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    search = FakeHistoricalSearch(
        [result([paper("A", 2020, title="GCC-PHAT TDOA localization")])]
    )
    service = radar_service(database, settings, search, ["radar", "scan"])
    radar = service.create(spec())

    completed = service.scan(radar.id)
    persisted = RadarRepository(database).get_scan(completed.scan.id)

    assert persisted is not None
    assert persisted.analysis["annual_counts"] == [{"year": 2020, "count": 1}]
    assert {item["phrase"] for item in persisted.analysis["keywords"]} >= {
        "GCC-PHAT",
        "TDOA",
    }
    database.connection.close()


def test_exclude_keywords_filter_papers_before_radar_history(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    search = FakeHistoricalSearch(
        [
            result(
                [
                    paper("A", 2020, title="Underwater TDOA localization"),
                    paper("B", 2020, title="Terrestrial TDOA localization"),
                ]
            )
        ]
    )
    service = radar_service(database, settings, search, ["radar", "scan"])
    radar = service.create(spec(exclude_keywords=["terrestrial"]))

    completed = service.scan(radar.id)

    assert completed.scan.dedup_count == 1
    assert completed.scan.new_count == 1
    assert completed.new_canonical_ids == ["doi:10.1000/a"]
    database.connection.close()


def test_scan_persists_representative_scores_on_radar_relations(tmp_path):
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    representative = paper("A", 2020, title="GCC-PHAT TDOA receiver geometry")
    search = FakeHistoricalSearch([result([representative])])
    service = radar_service(database, settings, search, ["radar", "scan"])
    radar = service.create(spec())

    completed = service.scan(radar.id)
    relations = RadarRepository(database).list_paper_relations(radar.id)

    assert completed.scan.analysis["representative_papers"]
    assert len(relations) == 1
    assert relations[0].representative_score > 0
    database.connection.close()
