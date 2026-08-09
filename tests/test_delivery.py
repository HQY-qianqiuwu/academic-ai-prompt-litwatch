from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.deliveries import DeliveryStatus
from litwatch.delivery_repository import DeliveryRepository
from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.models import Author, Paper
from litwatch.services.delivery import DeliveryService
from litwatch.services.historical_papers import HistoricalPaperService
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository
from litwatch.subscription_runs import (
    Recommendation,
    SubscriptionRun,
    SubscriptionRunStatus,
    SubscriptionRunTrigger,
)
from litwatch.subscriptions import Subscription
from litwatch.web import create_app

NOW = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)


def setup_delivery(tmp_path: Path):
    database = Database(tmp_path / "delivery.db")
    subscriptions = SubscriptionRepository(database)
    saved = Subscription(
        id="sub-a",
        name="TDOA Weekly",
        topic="underwater acoustic TDOA localization",
        providers=["openalex"],
        search_limit=10,
        recommendation_limit=5,
        weekday=6,
        local_time="08:00",
        timezone="Asia/Shanghai",
        created_at=NOW,
        updated_at=NOW,
    )
    subscriptions.create(saved)
    history = HistoricalPaperRepository(database)
    HistoricalPaperService(history, subscriptions).observe_papers_for_subscription(
        "sub-a",
        [
            Paper(
                canonical_id="openalex:a",
                title="Underwater Acoustic TDOA Paper",
                abstract="Provider-backed abstract.",
                authors=[Author(name="Alice")],
                publication_date=date(2026, 1, 1),
                venue="JASA",
                doi="10.1000/tdoa",
                sources=["openalex"],
            )
        ],
        NOW,
        run_id="run-a",
    )
    run = SubscriptionRun(
        id="run-a",
        subscription_id="sub-a",
        run_key="manual:a",
        trigger=SubscriptionRunTrigger.MANUAL,
        started_at=NOW,
        heartbeat_at=NOW,
        finished_at=NOW,
        status=SubscriptionRunStatus.SUCCESS,
        raw_count=2,
        dedup_count=1,
        duplicates_removed=1,
        new_count=1,
        eligible_count=1,
        recommended_count=1,
    )
    SubscriptionRunRepository(database).create(run)
    recommendation = Recommendation(
        id="rec-a",
        run_id="run-a",
        subscription_id="sub-a",
        canonical_id="doi:10.1000/tdoa",
        rank_position=1,
        rank_score=0.9,
        relevance_score=0.8,
        quality_score=0.7,
        recommended_at=NOW,
    )
    repository = DeliveryRepository(database)
    service = DeliveryService(
        repository, history, clock=lambda: NOW, id_factory=lambda: "delivery-a"
    )
    return database, saved, run, recommendation, repository, service


def test_dashboard_digest_contains_source_backed_card_and_is_idempotent(tmp_path):
    database, saved, run, recommendation, repository, service = setup_delivery(tmp_path)

    first = service.deliver_dashboard(saved, run, [recommendation])
    repeated = service.deliver_dashboard(saved, run, [recommendation])

    assert first == repeated
    assert first.status is DeliveryStatus.DELIVERED
    assert first.digest["run"]["raw_count"] == 2
    assert first.digest["papers"][0] == {
        "canonical_id": "doi:10.1000/tdoa",
        "title": "Underwater Acoustic TDOA Paper",
        "authors": ["Alice"],
        "year": 2026,
        "venue": "JASA",
        "abstract": "Provider-backed abstract.",
        "sources": ["openalex"],
        "doi": "10.1000/tdoa",
        "url": "https://doi.org/10.1000/tdoa",
        "rank_position": 1,
        "rank_score": 0.9,
        "relevance_score": 0.8,
        "quality_score": 0.7,
    }
    assert len(repository.list()) == 1
    database.connection.close()


def test_empty_digest_is_success_not_error(tmp_path):
    database, saved, run, _, _, service = setup_delivery(tmp_path)
    run.id = "run-empty"
    run.run_key = "manual:empty"
    run.new_count = 0
    run.eligible_count = 0
    run.recommended_count = 0
    SubscriptionRunRepository(database).create(run)

    delivery = service.deliver_dashboard(saved, run, [])

    assert delivery.status is DeliveryStatus.DELIVERED
    assert delivery.digest["papers"] == []
    assert delivery.digest["empty_message"] == (
        "No new papers matched this subscription this week."
    )
    database.connection.close()


def test_historical_digest_survives_restart(tmp_path):
    database, saved, run, recommendation, _, service = setup_delivery(tmp_path)
    delivery = service.deliver_dashboard(saved, run, [recommendation])
    database.connection.close()

    reopened = Database(tmp_path / "delivery.db")
    repository = DeliveryRepository(reopened)

    assert repository.get(delivery.id) == delivery
    assert repository.list("sub-a") == [delivery]
    reopened.connection.close()


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "web.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def test_weekly_digest_page_assets_and_empty_api(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        page = client.get("/weekly-digests")
        script = client.get("/static/weekly-digests.js")
        styles = client.get("/static/weekly-digests.css")
        deliveries = client.get("/api/v1/deliveries")

    assert page.status_code == script.status_code == styles.status_code == 200
    assert deliveries.status_code == 200
    assert deliveries.json() == []
    assert "Weekly Digests" in page.text
    assert "digest.empty_message" in script.text
    for field in ("authors", "year", "venue", "abstract", "sources", "doi"):
        assert f"paper.{field}" in script.text
    assert "rank_score" in script.text
    assert "relevance_score" in script.text
    assert "quality_score" in script.text
