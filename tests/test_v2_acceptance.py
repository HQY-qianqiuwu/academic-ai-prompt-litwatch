from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep

import httpx
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
from litwatch.provider_config import (
    ProviderProfileStore,
    ProviderType,
    default_provider_profile,
)
from litwatch.radar_repository import RadarRepository
from litwatch.services.jobs import JobWorker
from litwatch.services.literature_search import (
    LiteratureSearchService,
)
from litwatch.services.paper_analysis import AnalysisContext, PaperAnalysisService
from litwatch.sources.registry import InMemoryCredentialStore, ProviderRegistry
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository
from litwatch.subscription_runs import SubscriptionRunTrigger
from litwatch.web import create_app

NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
PROVIDER_SECRET = "acceptance-provider-secret-must-not-leak"


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


class DeterministicPaperSource:
    """Deterministic fake at the external PaperSource boundary only."""

    def __init__(self, name: str, outcomes: list[list[Paper] | Exception]) -> None:
        self.name = name
        self.outcomes = list(outcomes)
        self.calls: list[tuple[Topic, date, date, int]] = []

    def search(
        self,
        topic: Topic,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[Paper]:
        self.calls.append((topic, start_date, end_date, limit))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return [paper.model_copy(deep=True) for paper in outcome]


def _rate_limit_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://provider.invalid/search")
    response = httpx.Response(429, request=request)
    return httpx.HTTPStatusError(
        "deterministic rate limit", request=request, response=response
    )


def _production_search_stack(
    settings: Settings,
    sources: dict[ProviderType, DeterministicPaperSource],
) -> tuple[
    LiteratureSearchService,
    ProviderRegistry,
    ProviderProfileStore,
    InMemoryCredentialStore,
    list[tuple[str, str | None]],
]:
    credentials = InMemoryCredentialStore()
    factory_calls: list[tuple[str, str | None]] = []

    def factory_for(source: DeterministicPaperSource):
        def build(config, credential):
            factory_calls.append((config.provider_id, credential))
            return source

        return build

    registry = ProviderRegistry(
        factories={
            provider_type: factory_for(source)
            for provider_type, source in sources.items()
        },
        credential_store=credentials,
    )
    profile = default_provider_profile(
        openalex_base_url=settings.openalex_base_url,
        semantic_scholar_base_url=settings.semantic_scholar_base_url,
        arxiv_base_url=settings.arxiv_base_url,
        crossref_base_url=settings.crossref_base_url,
    )
    profiles = ProviderProfileStore([profile])
    search = LiteratureSearchService(
        registry=registry,
        profile_store=profiles,
        current_date=lambda: NOW.date(),
    )
    return search, registry, profiles, credentials, factory_calls


def test_dify_free_runtime_serves_search_settings_and_bilingual_navigation(tmp_path):
    settings = _settings(tmp_path)
    duplicate_openalex = _paper("duplicate")
    duplicate_semantic = _paper("duplicate")
    duplicate_semantic.sources = ["semantic_scholar"]
    duplicate_semantic.source_ids = {"semantic_scholar": "duplicate"}
    openalex = DeterministicPaperSource(
        "openalex",
        [
            [duplicate_openalex, _paper("unique")],
            [_paper("partial")],
        ],
    )
    semantic = DeterministicPaperSource(
        "semantic_scholar",
        [[duplicate_semantic], _rate_limit_error()],
    )
    search, registry, profiles, credentials, factory_calls = _production_search_stack(
        settings,
        {
            ProviderType.OPENALEX: openalex,
            ProviderType.SEMANTIC_SCHOLAR: semantic,
        },
    )
    app = create_app(
        settings,
        literature_search_service=search,
        provider_registry=registry,
        provider_profile_store=profiles,
        credential_store=credentials,
    )

    assert isinstance(app.state.literature_search_service, LiteratureSearchService)
    assert app.state.subscription_run_service.search_service is search
    assert app.state.scheduler_service.run_service.search_service is search
    assert app.state.research_radar_service.search_service is search

    with TestClient(app) as client:
        runtime = client.get("/api/v2/runtime")
        updated_profile = client.post(
            "/api/v1/provider-profiles",
            json={
                "profile_id": "default",
                "providers": [
                    {
                        "provider_id": "semantic_scholar",
                        "requires_api_key": True,
                        "credential_reference": "semantic_scholar_default",
                        "api_key": PROVIDER_SECRET,
                    }
                ],
            },
        )
        aggregated = client.post(
            "/api/v1/literature/search",
            json={
                "topic": "underwater acoustic TDOA localization",
                "limit": 5,
                "providers": ["openalex", "semantic_scholar"],
            },
        )
        partial = client.post(
            "/api/v1/literature/search",
            json={
                "topic": "underwater acoustic TDOA localization",
                "limit": 5,
                "providers": ["openalex", "semantic_scholar"],
            },
        )
        capabilities = client.get("/api/v1/providers")
        profile_response = client.get("/api/v1/provider-profiles")
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
        provider_script = client.get("/static/provider-settings.js")

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
    assert aggregated.status_code == 200
    assert aggregated.json()["diagnostics"]["raw_count"] == 3
    assert aggregated.json()["diagnostics"]["dedup_count"] == 2
    assert aggregated.json()["diagnostics"]["duplicates_removed"] == 1
    merged = next(
        paper
        for paper in aggregated.json()["papers"]
        if paper["canonical_id"] == "doi:10.1000/duplicate"
    )
    assert merged["sources"] == ["openalex", "semantic_scholar"]
    assert len(aggregated.json()["diagnostics"]["ranking"]) == 2
    assert [paper["canonical_id"] for paper in aggregated.json()["papers"]] == [
        item["canonical_id"] for item in aggregated.json()["diagnostics"]["ranking"]
    ]
    rank_scores = [
        item["rank_score"] for item in aggregated.json()["diagnostics"]["ranking"]
    ]
    assert rank_scores == sorted(rank_scores, reverse=True)
    assert partial.status_code == 200
    assert partial.json()["papers"][0]["canonical_id"] == "doi:10.1000/partial"
    assert [item["status"] for item in partial.json()["provider_status"]] == [
        "success",
        "rate_limited",
    ]
    assert partial.json()["provider_status"][1]["error_code"] == "upstream_429"
    assert all(call[0].query == "underwater acoustic TDOA localization" for call in openalex.calls)
    assert all(call[3] == 10 for call in [*openalex.calls, *semantic.calls])
    assert factory_calls == [
        ("openalex", None),
        ("semantic_scholar", PROVIDER_SECRET),
        ("openalex", None),
        ("semantic_scholar", PROVIDER_SECRET),
    ]
    assert credentials.source("semantic_scholar_default") == "profile"
    assert credentials.resolve("semantic_scholar_default") == PROVIDER_SECRET
    stored_semantic = profiles.get("default").provider("semantic_scholar")
    assert stored_semantic.requires_api_key is True
    assert stored_semantic.credential_reference == "semantic_scholar_default"
    assert capabilities.status_code == profile_response.status_code == 200
    assert {item["provider_type"] for item in capabilities.json()} >= {
        "openalex",
        "semantic_scholar",
        "arxiv",
        "crossref",
    }
    assert profile_response.json()[0]["profile_id"] == "default"
    semantic_projection = next(
        item
        for item in profile_response.json()[0]["providers"]
        if item["provider_id"] == "semantic_scholar"
    )
    assert semantic_projection["configured"] is True
    assert semantic_projection["credential_configured"] is True
    assert all(
        "api_key" not in item
        for item in profile_response.json()[0]["providers"]
    )
    assert updated_profile.status_code == 200
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
    projected_content = [
        updated_profile.text,
        profile_response.text,
        aggregated.text,
        partial.text,
        capabilities.text,
        i18n.text,
        provider_script.text,
        *(page.text for page in pages),
    ]
    assert all(PROVIDER_SECRET not in content for content in projected_content)


def test_radar_subscription_scheduler_digest_dedup_and_restart_share_sqlite(tmp_path):
    settings = _settings(tmp_path, name="features.db")
    openalex = DeterministicPaperSource(
        "openalex",
        [
            [_paper("manual")],
            [_paper("a"), _paper("b", score=0.8)],
            [_paper("a"), _paper("b", score=0.8), _paper("c", score=0.7)],
            [
                _paper("a"),
                _paper("b", score=0.8),
                _paper("c", score=0.7),
                _paper("d", score=0.6),
            ],
            [_paper("radar", year=2026)],
        ],
    )
    search, registry, profiles, credentials, _ = _production_search_stack(
        settings, {ProviderType.OPENALEX: openalex}
    )
    app = create_app(
        settings,
        literature_search_service=search,
        provider_registry=registry,
        provider_profile_store=profiles,
        credential_store=credentials,
    )

    assert app.state.literature_search_service is search
    assert app.state.subscription_run_service.search_service is search
    assert app.state.scheduler_service.run_service.search_service is search
    assert app.state.research_radar_service.search_service is search

    with TestClient(app) as client:
        manual = client.post(
            "/api/v1/literature/search",
            json={
                "topic": "underwater acoustic TDOA localization",
                "limit": 5,
                "providers": ["openalex"],
            },
        )
        created = client.post(
            "/api/v1/subscriptions",
            json={
                "name": "TDOA Weekly",
                "topic": "underwater acoustic TDOA localization",
                "providers": ["openalex"],
                "search_limit": 10,
                "recommendation_limit": 5,
                "frequency": "weekly",
                "weekday": 4,
                "local_time": "16:00",
                "timezone": "Asia/Shanghai",
                "enabled": True,
            },
        )
        subscription_id = created.json()["id"]
        first = client.post(f"/api/v1/subscriptions/{subscription_id}/run")
        second = client.post(f"/api/v1/subscriptions/{subscription_id}/run")
        due = NOW + timedelta(days=7)
        app.state.subscription_service.repository.set_next_run_at(
            subscription_id, due
        )
        [scheduled_id] = app.state.scheduler_service.tick(due)
        scheduled = app.state.subscription_run_repository.get(scheduled_id)
        scheduled_delivery = app.state.delivery_repository.get_for_run(scheduled_id)
        radar = client.post(
            "/api/v1/radars",
            json={
                "name": "TDOA Evolution",
                "topic": "underwater acoustic TDOA localization",
                "keywords": ["TDOA"],
                "exclude_keywords": [],
                "providers": ["openalex"],
                "start_year": 2026,
                "end_year": 2026,
                "recent_window_years": 1,
                "search_limit_per_period": 10,
                "enabled": True,
            },
        )
        radar_id = radar.json()["id"]
        accepted_scan = client.post(f"/api/v1/radars/{radar_id}/scan")
        radar_scans = client.get(f"/api/v1/radars/{radar_id}/scans")
        radar_papers = client.get(f"/api/v1/radars/{radar_id}/papers")

    assert manual.status_code == 200
    assert manual.json()["papers"][0]["canonical_id"] == "doi:10.1000/manual"
    assert created.status_code == 201
    assert first.status_code == second.status_code == 200
    assert first.json()["run"]["recommended_count"] == 2
    assert second.json()["run"]["historical_duplicates_removed"] == 2
    assert [item["canonical_id"] for item in second.json()["recommendations"]] == [
        "doi:10.1000/c"
    ]
    assert scheduled is not None
    assert scheduled.trigger is SubscriptionRunTrigger.SCHEDULED
    assert scheduled.historical_duplicates_removed == 3
    assert scheduled_delivery is not None
    assert [item["canonical_id"] for item in scheduled_delivery.digest["papers"]] == [
        "doi:10.1000/d"
    ]
    assert radar.status_code == 201
    assert accepted_scan.status_code == 202
    assert radar_scans.json()[0]["status"] == "success"
    assert radar_scans.json()[0]["analysis"]["annual_counts"] == [
        {"year": 2026, "count": 1}
    ]
    assert [paper["canonical_id"] for paper in radar_papers.json()] == [
        "doi:10.1000/radar"
    ]
    assert len(openalex.calls) == 5
    assert [call[3] for call in openalex.calls] == [10, 20, 20, 20, 20]

    restarted = Database(settings.database_path)
    assert SubscriptionRepository(restarted).get(subscription_id) is not None
    assert len(SubscriptionRunRepository(restarted).list_for_subscription(subscription_id)) == 3
    # Each of the 3 runs records both a dashboard and an email delivery.
    assert len(DeliveryRepository(restarted).list(subscription_id)) == 6
    assert (
        HistoricalPaperRepository(restarted)
        .get_subscription_paper(subscription_id, "doi:10.1000/d")
        .recommendation_count
        == 1
    )
    assert RadarRepository(restarted).latest_successful_scan(radar_id) is not None
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
