from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from itertools import count
from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from litwatch.analysis import PaperAnalyzer
from litwatch.analysis_models import EvidenceScope
from litwatch.analysis_repository import AnalysisRepository
from litwatch.config import Settings, Topic
from litwatch.db import MIGRATION_REGISTRY, Database
from litwatch.delivery_repository import DeliveryRepository
from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.job_repository import JobRepository
from litwatch.jobs import JobStatus
from litwatch.llm import LLMBudget, LLMGateway, LLMResponse, LLMUsage
from litwatch.llm.security import CostGuard, DataEgressPolicy, LLMUsageLedger
from litwatch.migrations import Migration, MigrationCoordinator, MigrationSafetyError
from litwatch.models import Author, Paper
from litwatch.provider_config import ProviderProfileStore, default_provider_profile
from litwatch.radar_repository import RadarRepository
from litwatch.radars import RadarSpec
from litwatch.services.delivery import DeliveryService
from litwatch.services.jobs import JobWorker
from litwatch.services.literature_search import (
    LiteratureSearchDiagnostics,
    LiteratureSearchResult,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services.paper_analysis import AnalysisContext, PaperAnalysisService
from litwatch.services.radars import ResearchRadarService
from litwatch.services.scheduler import SchedulerService
from litwatch.services.subscription_runs import SubscriptionRunService
from litwatch.services.subscriptions import SubscriptionService
from litwatch.sources.registry import ProviderRegistry
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository
from litwatch.subscription_runs import SubscriptionRunTrigger
from litwatch.subscriptions import SubscriptionSpec
from litwatch.web import create_app

NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _settings(tmp_path: Path, *, name: str = "acceptance.db") -> Settings:
    topics = tmp_path / f"{name}.topics.yaml"
    topics.write_text(
        """topics:
  - id: underwater
    name: Underwater acoustics
    query: underwater acoustic localization
    include: [TDOA, localization]
""",
        encoding="utf-8",
    )
    return Settings(
        _env_file=None,
        runtime_mode="dify_free",
        database_path=tmp_path / name,
        database_backup_path=tmp_path / "backups",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
        scheduler_poll_seconds=3600,
        job_poll_seconds=3600,
    )


def _paper(identifier: str, *, year: int = 2026, score: float = 0.9) -> Paper:
    return Paper(
        canonical_id=f"doi:10.1000/{identifier}",
        title=f"Grounded TDOA paper {identifier.upper()}",
        abstract="We propose a TDOA method. Results show lower localization error.",
        authors=[Author(name="Acceptance Researcher")],
        publication_date=date(year, 6, 1),
        venue="Deterministic Proceedings",
        doi=f"10.1000/{identifier}",
        url=f"https://doi.org/10.1000/{identifier}",
        sources=["openalex"],
        source_ids={"openalex": identifier},
        score=score,
        score_detail={
            "rank_score": score,
            "relevance_score": max(0.0, score - 0.05),
            "quality_score": max(0.0, score - 0.1),
        },
    )


def _search_result(papers: list[Paper]) -> LiteratureSearchResult:
    return LiteratureSearchResult(
        query="underwater acoustic TDOA localization",
        papers=papers,
        provider_status=[
            ProviderSearchStatus(
                provider="openalex",
                status=ProviderExecutionStatus.SUCCESS,
                fetched_count=len(papers),
                returned_count=len(papers),
            )
        ],
        diagnostics=LiteratureSearchDiagnostics(
            raw_count=len(papers),
            dedup_count=len(papers),
            duplicates_removed=0,
        ),
    )


class ScriptedSearch:
    """Replace only external provider nondeterminism, not LitWatch services."""

    def __init__(self, outcomes: list[LiteratureSearchResult]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def search(
        self,
        *,
        topic: str,
        limit: int,
        providers: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> LiteratureSearchResult:
        self.calls.append(
            {
                "topic": topic,
                "limit": limit,
                "providers": providers,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return self.outcomes.pop(0)


def _provider_components(
    settings: Settings,
) -> tuple[ProviderRegistry, ProviderProfileStore]:
    profile = default_provider_profile(
        openalex_base_url=settings.openalex_base_url,
        semantic_scholar_base_url=settings.semantic_scholar_base_url,
        arxiv_base_url=settings.arxiv_base_url,
        crossref_base_url=settings.crossref_base_url,
    )
    return ProviderRegistry.from_settings(settings), ProviderProfileStore([profile])


def test_dify_free_runtime_serves_search_settings_and_bilingual_navigation(tmp_path):
    search = ScriptedSearch([_search_result([_paper("manual")])])
    app = create_app(_settings(tmp_path), literature_search_service=search)

    with TestClient(app) as client:
        runtime = client.get("/api/v2/runtime")
        result = client.post(
            "/api/v1/literature/search",
            json={
                "topic": "underwater acoustic TDOA localization",
                "limit": 5,
                "providers": ["openalex"],
            },
        )
        capabilities = client.get("/api/v1/providers")
        profiles = client.get("/api/v1/provider-profiles")
        updated_profile = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [{"provider_id": "openalex", "enabled": True}],
            },
        )
        pages = [
            client.get(path)
            for path in (
                "/",
                "/provider-settings",
                "/subscriptions",
                "/weekly-digests",
                "/radars",
                "/analysis",
                "/jobs",
            )
        ]
        i18n = client.get("/static/i18n.js")

    assert runtime.status_code == 200
    assert runtime.json() == {
        "mode": "dify_free",
        "python_primary": True,
        "requires_dify": False,
        "requires_docker": False,
        "requires_ssrf_proxy": False,
        "migration_verified": True,
        "runtime_started": True,
        "job_worker_running": True,
        "job_worker_active": 0,
        "scheduler_running": True,
        "scheduler_last_error": None,
    }
    assert result.status_code == 200
    assert result.json()["papers"][0]["canonical_id"] == "doi:10.1000/manual"
    assert result.json()["provider_status"][0]["status"] == "success"
    assert search.calls[0]["providers"] == ["openalex"]
    assert capabilities.status_code == profiles.status_code == 200
    assert {item["provider_type"] for item in capabilities.json()} >= {
        "openalex",
        "semantic_scholar",
        "arxiv",
        "crossref",
    }
    assert profiles.json()[0]["profile_id"] == "default"
    assert all("api_key" not in item for item in profiles.json()[0]["providers"])
    assert updated_profile.status_code == 200
    assert updated_profile.json()["providers"][0]["enabled"] is True
    assert all(
        "api_key" not in item for item in updated_profile.json()["providers"]
    )
    assert all(page.status_code == 200 for page in pages)
    assert all('<html lang="zh-CN">' in page.text for page in pages)
    assert all('data-locale="en"' in page.text for page in pages)
    for path in ("/provider-settings", "/subscriptions", "/radars", "/analysis", "/jobs"):
        assert f'href="{path}"' in pages[0].text
    assert "\u6587\u732e\u68c0\u7d22" in pages[0].text
    assert "Python Analysis" in i18n.text
    assert "Provider Settings" in i18n.text


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_radar_subscription_scheduler_digest_dedup_and_restart_share_sqlite(tmp_path):
    settings = _settings(tmp_path, name="features.db")
    database = Database(settings.database_path)
    registry, profiles = _provider_components(settings)
    subscriptions = SubscriptionRepository(database)
    runs = SubscriptionRunRepository(database)
    history = HistoricalPaperRepository(database)
    deliveries = DeliveryRepository(database)
    clock = MutableClock(NOW)
    subscription_service = SubscriptionService(
        subscriptions,
        registry,
        profiles,
        clock=clock,
        id_factory=lambda: "subscription-acceptance",
    )
    search = ScriptedSearch(
        [
            _search_result([_paper("a"), _paper("b", score=0.8)]),
            _search_result(
                [_paper("a"), _paper("b", score=0.8), _paper("c", score=0.7)]
            ),
            _search_result(
                [
                    _paper("a"),
                    _paper("b", score=0.8),
                    _paper("c", score=0.7),
                    _paper("d", score=0.6),
                ]
            ),
        ]
    )
    run_ids = count(1)
    delivery_ids = count(1)
    delivery_service = DeliveryService(
        deliveries,
        history,
        clock=clock,
        id_factory=lambda: f"delivery-{next(delivery_ids)}",
    )
    run_service = SubscriptionRunService(
        search,
        subscriptions,
        runs,
        history,
        delivery_service,
        clock=clock,
        id_factory=lambda: f"run-object-{next(run_ids)}",
    )
    subscription = subscription_service.create(
        SubscriptionSpec(
            name="TDOA Weekly",
            topic="underwater acoustic TDOA localization",
            providers=["openalex"],
            search_limit=10,
            recommendation_limit=5,
            weekday=4,
            local_time="16:00",
            timezone="Asia/Shanghai",
        )
    )

    first = run_service.run_now(subscription.id)
    second = run_service.run_now(subscription.id)
    due = NOW + timedelta(days=7)
    clock.value = due
    subscriptions.set_next_run_at(subscription.id, due)
    scheduler = SchedulerService(
        subscriptions,
        runs,
        run_service,
        clock=clock,
        owner="acceptance-scheduler",
    )
    [scheduled_id] = scheduler.tick(due)
    scheduled = runs.get(scheduled_id)
    scheduled_delivery = deliveries.get_for_run(scheduled_id)

    radar_search = ScriptedSearch(
        [_search_result([_paper("radar", year=2026)])]
    )
    radar_ids = iter(("radar-acceptance", "radar-scan-acceptance"))
    radar_service = ResearchRadarService(
        RadarRepository(database),
        registry,
        profiles,
        search_service=radar_search,
        clock=clock,
        id_factory=lambda: next(radar_ids),
    )
    radar = radar_service.create(
        RadarSpec(
            name="TDOA Evolution",
            topic="underwater acoustic TDOA localization",
            keywords=["TDOA"],
            providers=["openalex"],
            start_year=2026,
            end_year=2026,
            recent_window_years=1,
            search_limit_per_period=10,
        )
    )
    radar_scan = radar_service.scan(radar.id)

    assert first.run.recommended_count == 2
    assert second.run.historical_duplicates_removed == 2
    assert [item.canonical_id for item in second.recommendations] == [
        "doi:10.1000/c"
    ]
    assert scheduled is not None
    assert scheduled.trigger is SubscriptionRunTrigger.SCHEDULED
    assert scheduled.historical_duplicates_removed == 3
    assert scheduled_delivery is not None
    assert [item["canonical_id"] for item in scheduled_delivery.digest["papers"]] == [
        "doi:10.1000/d"
    ]
    assert radar_scan.scan.status.value == "success"
    assert radar_scan.new_canonical_ids == ["doi:10.1000/radar"]
    assert radar_scan.scan.analysis["annual_counts"] == [{"year": 2026, "count": 1}]
    database.connection.close()

    restarted = Database(settings.database_path)
    assert SubscriptionRepository(restarted).get(subscription.id) is not None
    assert len(SubscriptionRunRepository(restarted).list_for_subscription(subscription.id)) == 3
    assert len(DeliveryRepository(restarted).list(subscription.id)) == 3
    assert (
        HistoricalPaperRepository(restarted)
        .get_subscription_paper(subscription.id, "doi:10.1000/d")
        .recommendation_count
        == 1
    )
    assert RadarRepository(restarted).latest_successful_scan(radar.id) is not None
    restarted.connection.close()


class StructuredAnalysisProvider:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content=json.dumps(
                {
                    "one_liner": "A grounded localization result.",
                    "motivation": "Reduce underwater localization error.",
                    "methods": ["TDOA"],
                    "results": ["Lower localization error"],
                    "limitations": ["Abstract evidence only"],
                    "relevance": "Directly relevant to underwater localization.",
                    "paper_type": "method",
                    "research_gap": "Broader field validation is needed.",
                    "reading_priority": 5,
                    "workflow_output": {"decision": "read"},
                    "evidence_level": "abstract",
                    "confidence": 0.9,
                }
            ),
            usage=LLMUsage(input_tokens=100, output_tokens=40, total_tokens=140),
            provider_request_id="acceptance-request",
            model="acceptance-model",
        )


def test_structured_paper_analysis_flows_through_gateway_service_and_repository(tmp_path):
    settings = _settings(tmp_path, name="analysis.db").model_copy(
        update={
            "llm_api_key": "configured-for-deterministic-local-provider",
            "llm_provider_kind": "local",
            "llm_model": "acceptance-model",
        }
    )
    database = Database(settings.database_path)
    paper = _paper("analysis")
    paper.topic_id = "underwater"
    paper.topic_name = "Underwater acoustics"
    database.upsert(paper, database.start_run())
    provider = StructuredAnalysisProvider()
    gateway = LLMGateway(
        provider,
        provider_kind="local",
        data_egress_policy=DataEgressPolicy(
            cloud_egress_consent=False,
            fulltext_egress_consent=False,
            max_payload_chars=50_000,
        ),
        usage_ledger=LLMUsageLedger(
            database,
            CostGuard(
                max_tokens_per_job=20_000,
                max_cost_per_job=1.0,
                max_daily_cost=5.0,
                max_concurrent_llm_jobs=2,
            ),
            now=lambda: NOW,
        ),
    )
    analyzer = PaperAnalyzer(
        settings,
        gateway=gateway,
        budget_factory=lambda _request: LLMBudget(
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
            estimated_tokens=500,
            estimated_cost=0.0,
        ),
    )
    service = PaperAnalysisService(
        analyzer=analyzer,
        repository=AnalysisRepository(database),
    )
    topic = Topic(
        id="underwater",
        name="Underwater acoustics",
        query="underwater acoustic localization",
        include=["TDOA", "localization"],
    )
    context = AnalysisContext(
        paper=paper,
        topic=topic,
        evidence=paper.abstract,
        evidence_scope=EvidenceScope.ABSTRACT,
    )

    analysis = service.analyze(context)
    repeated = service.analyze(
        AnalysisContext(
            paper=paper,
            topic=topic,
            evidence=paper.abstract,
            evidence_scope=EvidenceScope.ABSTRACT,
        )
    )

    assert analysis is not None
    assert analysis.status.value == "completed"
    assert analysis.methods == ["TDOA"]
    assert analysis.main_results == ["Lower localization error"]
    assert repeated == analysis
    assert len(provider.requests) == 1
    assert provider.requests[0].untrusted_evidence == paper.abstract
    assert [entry.step for entry in context.trace][-2:] == [
        "validate_paper_analysis",
        "persist_paper_analysis",
    ]
    assert database.connection.execute("SELECT COUNT(*) FROM paper_analyses").fetchone()[0] == 1
    assert (
        database.connection.execute("SELECT COUNT(*) FROM llm_usage_reservations").fetchone()[0]
        == 0
    )
    database.connection.close()


def _wait_for_job(
    repository: JobRepository,
    job_id: str,
    statuses: set[JobStatus],
    *,
    timeout: float = 2.0,
):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        record = repository.get(job_id)
        if record is not None and record.status in statuses:
            return record
        sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def test_durable_jobs_cover_idempotency_cancel_timeout_and_restart(tmp_path):
    path = tmp_path / "jobs.db"
    database = Database(path)
    repository = JobRepository(database)
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=1, concurrency=1)

    def handler(_context, record):
        if record.payload.get("mode") == "timeout":
            raise TimeoutError("deterministic timeout")
        return f"analysis:{record.payload['paper_id']}"

    worker.register("analysis", handler)
    completed_job = repository.enqueue(
        job_type="analysis",
        idempotency_key="acceptance:complete",
        input_hash="hash:complete",
        payload={"paper_id": "doi:10.1000/complete"},
        max_attempts=1,
        timeout_seconds=30,
        now=NOW,
    )
    repeated = repository.enqueue(
        job_type="analysis",
        idempotency_key="acceptance:complete",
        input_hash="hash:must-not-replace",
        payload={"paper_id": "must-not-replace"},
        max_attempts=1,
        timeout_seconds=30,
        now=NOW,
    )
    worker.run_once()
    completed = _wait_for_job(repository, completed_job.job_id, {JobStatus.COMPLETED})

    cancelled = repository.enqueue(
        job_type="analysis",
        idempotency_key="acceptance:cancel",
        input_hash="hash:cancel",
        payload={"paper_id": "doi:10.1000/cancel"},
        max_attempts=1,
        timeout_seconds=30,
        now=NOW,
    )
    repository.request_cancel(cancelled.job_id, now=NOW)
    timeout_job = repository.enqueue(
        job_type="analysis",
        idempotency_key="acceptance:timeout",
        input_hash="hash:timeout",
        payload={"paper_id": "doi:10.1000/timeout", "mode": "timeout"},
        max_attempts=1,
        timeout_seconds=30,
        now=NOW,
    )
    worker.run_once()
    timed_out = _wait_for_job(repository, timeout_job.job_id, {JobStatus.FAILED})

    restart_job = repository.enqueue(
        job_type="analysis",
        idempotency_key="acceptance:restart",
        input_hash="hash:restart",
        payload={"paper_id": "doi:10.1000/restart"},
        max_attempts=2,
        timeout_seconds=30,
        now=NOW,
    )
    claimed = repository.claim_next("stale-worker", lease_seconds=1, now=NOW)
    assert claimed is not None and claimed.job_id == restart_job.job_id
    worker.stop()
    database.connection.close()

    restarted_database = Database(path)
    restarted_repository = JobRepository(restarted_database)
    recovered = restarted_repository.recover_stale(NOW + timedelta(seconds=2))

    assert repeated.job_id == completed.job_id
    assert repeated.payload == {"paper_id": "doi:10.1000/complete"}
    assert completed.result_reference == "analysis:doi:10.1000/complete"
    assert restarted_repository.get(cancelled.job_id).status is JobStatus.CANCELLED
    assert timed_out.safe_error_code == "timeout"
    assert [record.job_id for record in recovered] == [restart_job.job_id]
    assert recovered[0].status is JobStatus.QUEUED
    restarted_database.connection.close()


def test_migration_verification_backup_and_recovery_fail_closed(tmp_path):
    path = tmp_path / "migration.db"
    database = Database(path)
    database.connection.execute("INSERT INTO runs(started_at) VALUES ('before-backup')")
    database.connection.commit()
    next_version = len(MIGRATION_REGISTRY) + 1
    probe = Migration.from_sql(
        next_version,
        "acceptance_recovery_probe",
        "CREATE TABLE acceptance_recovery_probe(id INTEGER PRIMARY KEY);",
    )
    coordinator = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, probe),
        backup_directory=tmp_path / "backups",
    )

    report = coordinator.migrate()
    assert report.backup_path is not None
    database.connection.execute("INSERT INTO runs(started_at) VALUES ('after-backup')")
    database.connection.commit()
    recovered = coordinator.recover(report.backup_path)

    assert report.verification.ok is True
    assert report.applied_versions == (next_version,)
    assert report.backup_path.is_file()
    assert recovered.ok is True
    restored = sqlite3.connect(path)
    assert restored.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='before-backup'"
    ).fetchone()[0] == 1
    assert restored.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='after-backup'"
    ).fetchone()[0] == 0
    assert restored.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?", (next_version,)
    ).fetchone()[0] == 0
    restored.close()

    guarded = Database(tmp_path / "guarded.db")
    guarded.connection.execute("INSERT INTO runs(started_at) VALUES ('keep-me')")
    guarded.connection.commit()
    invalid_backup = tmp_path / "not-a-database.db"
    invalid_backup.write_text("not a SQLite database", encoding="utf-8")
    guarded_coordinator = MigrationCoordinator(guarded.connection, MIGRATION_REGISTRY)

    with pytest.raises(MigrationSafetyError, match="backup verification failed"):
        guarded_coordinator.recover(invalid_backup)

    assert guarded.connection.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='keep-me'"
    ).fetchone()[0] == 1
    assert list(tmp_path.glob(".guarded.db.restore-*.tmp")) == []
    guarded.connection.close()
