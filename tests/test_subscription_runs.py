from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.delivery_repository import DeliveryRepository
from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.models import Author, Paper
from litwatch.services.delivery import DeliveryService
from litwatch.services.literature_search import (
    AllProvidersFailedError,
    LiteratureSearchDiagnostics,
    LiteratureSearchResult,
    ProviderErrorCode,
    ProviderExecutionStatus,
    ProviderSearchStatus,
)
from litwatch.services.subscription_runs import SubscriptionRunService
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository
from litwatch.subscription_runs import SubscriptionRunStatus, SubscriptionRunTrigger
from litwatch.subscriptions import Subscription
from litwatch.web import create_app

NOW = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)


def candidate(canonical_id: str, title: str, score: float) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title=title,
        authors=[Author(name="Researcher")],
        publication_date=date(2026, 1, 1),
        sources=["openalex"],
        source_ids={"openalex": canonical_id},
        score=score,
        score_detail={
            "rank_score": score,
            "relevance_score": score - 0.1,
            "quality_score": score - 0.2,
        },
    )


def result(
    papers: list[Paper],
    statuses: list[ProviderSearchStatus] | None = None,
    *,
    raw_count: int | None = None,
) -> LiteratureSearchResult:
    statuses = statuses or [
        ProviderSearchStatus(
            provider="openalex",
            status=ProviderExecutionStatus.SUCCESS,
            fetched_count=len(papers),
            returned_count=len(papers),
        )
    ]
    raw = len(papers) if raw_count is None else raw_count
    return LiteratureSearchResult(
        query="underwater acoustic localization",
        papers=papers,
        provider_status=statuses,
        diagnostics=LiteratureSearchDiagnostics(
            raw_count=raw,
            dedup_count=len(papers),
            duplicates_removed=raw - len(papers),
        ),
    )


class FakeSearchService:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TickingClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


def saved_subscription(subscription_id: str = "sub-a", recommendation_limit: int = 2):
    return Subscription(
        id=subscription_id,
        name="TDOA Weekly",
        topic="underwater acoustic TDOA localization",
        providers=["openalex"],
        search_limit=10,
        recommendation_limit=recommendation_limit,
        weekday=6,
        local_time="08:00",
        timezone="Asia/Shanghai",
        created_at=NOW,
        updated_at=NOW,
    )


def build_service(tmp_path: Path, search, *, recommendation_limit: int = 2):
    database = Database(tmp_path / "litwatch.db")
    subscriptions = SubscriptionRepository(database)
    subscriptions.create(saved_subscription(recommendation_limit=recommendation_limit))
    runs = SubscriptionRunRepository(database)
    history = HistoricalPaperRepository(database)
    delivery = DeliveryService(DeliveryRepository(database), history)
    ids = iter(f"id-{index}" for index in range(100))
    service = SubscriptionRunService(
        search,
        subscriptions,
        runs,
        history,
        delivery,
        clock=TickingClock(),
        id_factory=lambda: next(ids),
    )
    return database, subscriptions, runs, history, service


def test_successful_run_persists_counts_and_recommendation_limit(tmp_path):
    papers = [
        candidate("openalex:a", "Paper A", 0.9),
        candidate("openalex:b", "Paper B", 0.8),
        candidate("openalex:c", "Paper C", 0.7),
    ]
    search = FakeSearchService([result(papers, raw_count=4)])
    database, subscriptions, runs, _, service = build_service(
        tmp_path, search, recommendation_limit=2
    )

    execution = service.run_now("sub-a")

    assert execution.run.status is SubscriptionRunStatus.SUCCESS
    assert execution.run.raw_count == 4
    assert execution.run.dedup_count == 3
    assert execution.run.duplicates_removed == 1
    assert execution.run.new_count == execution.run.eligible_count == 3
    assert execution.run.recommended_count == 2
    assert execution.delivery is not None
    assert execution.delivery.digest["run"]["recommended_count"] == 2
    assert [item.canonical_id for item in execution.recommendations] == [
        "openalex:a",
        "openalex:b",
    ]
    assert len(runs.list_for_subscription("sub-a")) == 1
    assert subscriptions.get("sub-a").last_success_at is not None
    assert search.calls == [
        {
            "topic": "underwater acoustic TDOA localization",
            "limit": 10,
            "providers": ["openalex"],
        }
    ]
    database.connection.close()


def test_second_run_recommends_only_new_papers(tmp_path):
    first = [candidate(f"openalex:{name}", f"Paper {name}", 0.9) for name in "ABC"]
    second = first + [
        candidate("openalex:d", "Paper D", 0.8),
        candidate("openalex:e", "Paper E", 0.7),
    ]
    search = FakeSearchService([result(first), result(second)])
    database, _, _, _, service = build_service(tmp_path, search, recommendation_limit=5)

    initial = service.run_now("sub-a")
    repeated = service.run_now("sub-a")

    assert initial.run.recommended_count == 3
    assert repeated.run.historical_duplicates_removed == 3
    assert repeated.run.new_count == 2
    assert [item.canonical_id for item in repeated.recommendations] == [
        "openalex:d",
        "openalex:e",
    ]
    database.connection.close()


def test_partial_success_persists_recommendations_and_safe_status(tmp_path):
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
    search = FakeSearchService(
        [result([candidate("openalex:a", "Paper A", 0.9)], statuses)]
    )
    database, subscriptions, _, _, service = build_service(tmp_path, search)

    execution = service.run_now("sub-a")

    assert execution.run.status is SubscriptionRunStatus.PARTIAL_SUCCESS
    assert execution.run.recommended_count == 1
    assert execution.run.provider_status[1]["error_code"] == "upstream_429"
    assert subscriptions.get("sub-a").last_success_at is not None
    database.connection.close()


def test_all_provider_failure_is_persisted_without_success_or_recommendations(tmp_path):
    failure = AllProvidersFailedError(
        [
            ProviderSearchStatus(
                provider="openalex",
                status=ProviderExecutionStatus.TIMEOUT,
                error_code=ProviderErrorCode.TIMEOUT,
            )
        ]
    )
    database, subscriptions, runs, _, service = build_service(
        tmp_path, FakeSearchService([failure])
    )

    execution = service.run_now("sub-a")

    assert execution.run.status is SubscriptionRunStatus.FAILED
    assert execution.run.safe_error == "all_providers_failed"
    assert execution.recommendations == []
    assert runs.list_recommendations(execution.run.id) == []
    stored = subscriptions.get("sub-a")
    assert stored.last_run_at is not None
    assert stored.last_success_at is None
    database.connection.close()


def test_explicit_run_key_is_idempotent(tmp_path):
    search = FakeSearchService(
        [result([candidate("openalex:a", "Paper A", 0.9)])]
    )
    database, _, runs, _, service = build_service(tmp_path, search)

    first = service.run(
        "sub-a", trigger=SubscriptionRunTrigger.SCHEDULED, run_key="scheduled:one"
    )
    same = service.run(
        "sub-a", trigger=SubscriptionRunTrigger.SCHEDULED, run_key="scheduled:one"
    )

    assert first.run.id == same.run.id
    assert first.recommendations == same.recommendations
    assert len(search.calls) == 1
    assert len(runs.list_for_subscription("sub-a")) == 1
    database.connection.close()


def test_run_and_recommendations_survive_restart(tmp_path):
    database, _, _, _, service = build_service(
        tmp_path,
        FakeSearchService([result([candidate("openalex:a", "Paper A", 0.9)])]),
    )
    execution = service.run_now("sub-a")
    database.connection.close()

    reopened = Database(tmp_path / "litwatch.db")
    repository = SubscriptionRunRepository(reopened)

    assert repository.get(execution.run.id) == execution.run
    assert repository.list_recommendations(execution.run.id) == execution.recommendations
    reopened.connection.close()


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "api.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def test_run_now_api_uses_run_engine_and_exposes_safe_result(tmp_path):
    search = FakeSearchService(
        [result([candidate("openalex:a", "Paper A", 0.9)])]
    )
    with TestClient(create_app(settings_for(tmp_path), search)) as client:
        created = client.post(
            "/api/v1/subscriptions",
            json={
                "name": "TDOA Weekly",
                "topic": "underwater acoustic TDOA localization",
                "providers": ["openalex"],
                "search_limit": 10,
                "recommendation_limit": 5,
                "frequency": "weekly",
                "weekday": 6,
                "local_time": "08:00",
                "timezone": "Asia/Shanghai",
                "enabled": True,
            },
        ).json()
        response = client.post(f"/api/v1/subscriptions/{created['id']}/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["status"] == "success"
    assert payload["run"]["recommended_count"] == 1
    assert payload["recommendations"][0]["canonical_id"] == "openalex:a"
    assert payload["delivery"]["channel"] == "dashboard"
