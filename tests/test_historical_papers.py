from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from litwatch.db import MIGRATIONS, SCHEMA, Database
from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.models import Author, Paper
from litwatch.paper_history import SubscriptionPaperStatus
from litwatch.services.historical_papers import HistoricalPaperService
from litwatch.services.subscriptions import SubscriptionNotFoundError
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscriptions import Subscription

NOW = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)


def paper(
    canonical_id: str,
    title: str,
    *,
    doi: str = "",
    source: str = "openalex",
    abstract: str = "",
    authors: list[str] | None = None,
    citation_count: int = 0,
) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title=title,
        doi=doi,
        sources=[source],
        source_ids={source: canonical_id},
        abstract=abstract,
        authors=[Author(name=name) for name in authors or []],
        publication_date=date(2025, 1, 1),
        citation_count=citation_count,
        score=0.8,
        score_detail={"relevance": 0.7, "quality": 0.6},
    )


def subscription(subscription_id: str) -> Subscription:
    return Subscription(
        id=subscription_id,
        name=f"Subscription {subscription_id}",
        topic="underwater acoustic localization",
        providers=["openalex"],
        search_limit=10,
        recommendation_limit=5,
        weekday=6,
        local_time="08:00",
        timezone="Asia/Shanghai",
        created_at=NOW,
        updated_at=NOW,
    )


def stack(tmp_path: Path, *subscription_ids: str):
    database = Database(tmp_path / "litwatch.db")
    subscriptions = SubscriptionRepository(database)
    for subscription_id in subscription_ids:
        subscriptions.create(subscription(subscription_id))
    repository = HistoricalPaperRepository(database)
    service = HistoricalPaperService(repository, subscriptions)
    return database, repository, service


def test_first_observation_is_new_and_second_is_seen(tmp_path):
    database, repository, service = stack(tmp_path, "sub-a")
    candidate = paper("doi:10.1000/tdoa", "Underwater Acoustic TDOA Localization")

    first = service.observe_papers_for_subscription("sub-a", [candidate], NOW)
    second = service.observe_papers_for_subscription(
        "sub-a", [candidate], NOW + timedelta(days=7)
    )
    history = repository.get_subscription_paper("sub-a", candidate.canonical_id)
    global_history = database.connection.execute(
        "SELECT first_seen_at,last_seen_at FROM papers WHERE canonical_id=?",
        (candidate.canonical_id,),
    ).fetchone()

    assert first.new_count == 1
    assert first.new_papers[0].canonical_id == candidate.canonical_id
    assert first.new_papers[0].score == candidate.score
    assert first.seen_papers == []
    assert second.new_papers == []
    assert [item.canonical_id for item in second.seen_papers] == [candidate.canonical_id]
    assert history is not None
    assert history.first_seen_at == NOW
    assert history.last_seen_at == NOW + timedelta(days=7)
    assert history.seen_count == 2
    assert datetime.fromisoformat(global_history["first_seen_at"]) == NOW
    assert datetime.fromisoformat(global_history["last_seen_at"]) == NOW + timedelta(days=7)
    database.connection.close()


def test_mixed_observation_is_deterministically_sorted(tmp_path):
    database, _, service = stack(tmp_path, "sub-a")
    alpha = paper("openalex:a", "Acoustic Localization Alpha")
    beta = paper("openalex:b", "Acoustic Localization Beta")
    gamma = paper("openalex:c", "Acoustic Localization Gamma")
    service.observe_papers_for_subscription("sub-a", [beta], NOW)

    result = service.observe_papers_for_subscription(
        "sub-a", [gamma, beta, alpha], NOW + timedelta(days=7)
    )

    assert [item.canonical_id for item in result.new_papers] == ["openalex:a", "openalex:c"]
    assert [item.canonical_id for item in result.seen_papers] == ["openalex:b"]
    database.connection.close()


def test_newness_is_isolated_per_subscription(tmp_path):
    database, repository, service = stack(tmp_path, "sub-a", "sub-b")
    candidate = paper("openalex:shared", "Shared Underwater Acoustic Paper")

    first = service.observe_papers_for_subscription("sub-a", [candidate], NOW)
    other = service.observe_papers_for_subscription("sub-b", [candidate], NOW)

    assert first.new_count == other.new_count == 1
    assert repository.get_subscription_paper("sub-a", candidate.canonical_id) is not None
    assert repository.get_subscription_paper("sub-b", candidate.canonical_id) is not None
    count = database.connection.execute("SELECT count(*) FROM papers").fetchone()[0]
    assert count == 1
    database.connection.close()


def test_metadata_enrichment_reuses_existing_identity(tmp_path):
    database, repository, service = stack(tmp_path, "sub-a")
    sparse = paper(
        "crossref:work-1",
        "TDOA Localization in Underwater Acoustic Sensor Networks",
        doi="10.1000/TDOA.1",
        source="crossref",
        citation_count=2,
    )
    enriched = paper(
        "doi:10.1000/tdoa.1",
        "TDOA Localization in Underwater Acoustic Sensor Networks",
        doi="https://doi.org/10.1000/tdoa.1",
        source="openalex",
        abstract="A source-backed abstract with substantially richer metadata.",
        authors=["Alice", "Bob"],
        citation_count=9,
    )

    service.observe_papers_for_subscription("sub-a", [sparse], NOW)
    result = service.observe_papers_for_subscription(
        "sub-a", [enriched], NOW + timedelta(days=1)
    )
    stored = repository.get_paper("doi:10.1000/tdoa.1")

    assert [item.canonical_id for item in result.seen_papers] == ["doi:10.1000/tdoa.1"]
    assert [item.canonical_id for item in result.updated_papers] == ["doi:10.1000/tdoa.1"]
    assert stored is not None
    assert stored.abstract == enriched.abstract
    assert [author.name for author in stored.authors] == ["Alice", "Bob"]
    assert stored.citation_count == 9
    assert stored.doi == "10.1000/tdoa.1"
    assert stored.sources == ["crossref", "openalex"]
    assert database.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 1
    database.connection.close()


def test_same_title_with_different_dois_never_merges(tmp_path):
    database, _, service = stack(tmp_path, "sub-a")
    title = "Underwater Acoustic Communication with OFDM"
    first = paper("doi:10.1000/one", title, doi="10.1000/one")
    second = paper("doi:10.1000/two", title, doi="10.1000/two")

    result = service.observe_papers_for_subscription("sub-a", [first, second], NOW)

    assert result.new_count == 2
    assert database.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 2
    database.connection.close()


def test_same_provider_canonical_id_cannot_override_conflicting_doi(tmp_path):
    database, repository, _ = stack(tmp_path, "sub-a")
    title = "Underwater Acoustic Array Processing"
    first = paper("openalex:shared-id", title, doi="10.1000/first")
    conflicting = paper("openalex:shared-id", title, doi="10.1000/second")

    repository.observe("sub-a", [first], NOW)
    result = repository.observe(
        "sub-a", [conflicting], NOW + timedelta(days=1)
    )

    assert result.new_count == 1
    assert database.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 2
    dois = {
        row[0]
        for row in database.connection.execute("SELECT doi FROM papers").fetchall()
    }
    assert dois == {"10.1000/first", "10.1000/second"}
    database.connection.close()


def test_later_doi_enriches_without_changing_historical_canonical_id(tmp_path):
    database, repository, service = stack(tmp_path, "sub-a")
    title = "Passive Localization for Underwater Acoustic Sensor Networks"
    initial = paper("openalex:without-doi", title)
    enriched = paper(
        "crossref:with-doi",
        title,
        doi="10.1000/later-doi",
        source="crossref",
    )

    service.observe_papers_for_subscription("sub-a", [initial], NOW)
    result = service.observe_papers_for_subscription(
        "sub-a", [enriched], NOW + timedelta(days=1)
    )
    stored = repository.get_paper("openalex:without-doi")

    assert result.seen_papers[0].canonical_id == "openalex:without-doi"
    assert stored is not None
    assert stored.doi == "10.1000/later-doi"
    assert stored.sources == ["crossref", "openalex"]
    assert database.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 1
    database.connection.close()


def test_no_doi_repeat_is_seen_but_technical_titles_remain_distinct(tmp_path):
    database, _, service = stack(tmp_path, "sub-a")
    tdoa = paper("openalex:tdoa", "Robust TDOA Localization for Underwater Acoustic Networks")
    ofdm = paper("arxiv:ofdm", "Robust OFDM Localization for Underwater Acoustic Networks")
    repeated = paper("crossref:tdoa", tdoa.title, source="crossref")

    first = service.observe_papers_for_subscription("sub-a", [tdoa, ofdm], NOW)
    second = service.observe_papers_for_subscription(
        "sub-a", [repeated], NOW + timedelta(days=1)
    )

    assert first.new_count == 2
    assert second.seen_count == 1
    assert second.seen_papers[0].canonical_id == "openalex:tdoa"
    assert database.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 2
    database.connection.close()


def test_observation_rolls_back_paper_when_relationship_write_fails(tmp_path, monkeypatch):
    database, repository, service = stack(tmp_path, "sub-a")
    candidate = paper("openalex:rollback", "Transactional Historical Acoustic Paper")

    def fail_relationship(*_args, **_kwargs):
        raise RuntimeError("relationship write failed")

    monkeypatch.setattr(repository, "_upsert_observation", fail_relationship)
    with pytest.raises(RuntimeError, match="relationship write failed"):
        service.observe_papers_for_subscription("sub-a", [candidate], NOW)

    assert database.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 0
    assert database.connection.execute(
        "SELECT count(*) FROM subscription_papers"
    ).fetchone()[0] == 0
    database.connection.close()


def test_history_and_recommendation_state_survive_restart(tmp_path):
    path = tmp_path / "litwatch.db"
    database, repository, service = stack(tmp_path, "sub-a")
    candidate = paper("openalex:restart", "Persistent Acoustic Paper")
    service.observe_papers_for_subscription("sub-a", [candidate], NOW)
    repository.mark_recommended(
        "sub-a",
        candidate.canonical_id,
        NOW + timedelta(hours=1),
        rank_score=0.9,
        relevance_score=0.8,
        quality_score=0.7,
        run_id="run-12",
    )
    database.connection.close()

    reopened = Database(path)
    reopened_repository = HistoricalPaperRepository(reopened)
    history = reopened_repository.get_subscription_paper("sub-a", candidate.canonical_id)

    assert reopened_repository.get_paper(candidate.canonical_id) is not None
    assert history is not None
    assert history.status is SubscriptionPaperStatus.RECOMMENDED
    assert history.first_recommended_at == NOW + timedelta(hours=1)
    assert history.last_recommended_at == NOW + timedelta(hours=1)
    assert history.recommendation_count == 1
    assert history.last_rank_score == 0.9
    assert history.last_relevance_score == 0.8
    assert history.last_quality_score == 0.7
    assert history.last_run_id == "run-12"
    reopened.connection.close()


def test_duplicate_input_is_idempotent_within_observation(tmp_path):
    database, repository, service = stack(tmp_path, "sub-a")
    candidate = paper("openalex:duplicate", "One Historical Acoustic Paper")

    result = service.observe_papers_for_subscription(
        "sub-a", [candidate, candidate.model_copy(deep=True)], NOW
    )
    history = repository.get_subscription_paper("sub-a", candidate.canonical_id)

    assert result.new_count == 1
    assert history is not None
    assert history.seen_count == 1
    database.connection.close()


def test_observation_requires_existing_subscription_and_aware_timestamp(tmp_path):
    database, _, service = stack(tmp_path, "sub-a")
    candidate = paper("openalex:validation", "Validated Historical Acoustic Paper")

    with pytest.raises(SubscriptionNotFoundError):
        service.observe_papers_for_subscription("missing", [candidate], NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        service.observe_papers_for_subscription(
            "sub-a", [candidate], NOW.replace(tzinfo=None)
        )

    assert database.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 0
    database.connection.close()


def test_stage_three_migration_preserves_stage_two_rows(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    version, name, migration = MIGRATIONS[0]
    connection.executescript(migration)
    connection.execute(
        "INSERT INTO schema_migrations(version,name) VALUES (?,?)", (version, name)
    )
    connection.execute(
        """INSERT INTO papers(
               canonical_id,title,first_seen_at,last_seen_at
           ) VALUES (?,?,?,?)""",
        ("openalex:legacy", "Legacy Paper", NOW.isoformat(), NOW.isoformat()),
    )
    connection.execute(
        """INSERT INTO subscriptions(
               id,name,topic,providers_json,search_limit,recommendation_limit,
               frequency,weekday,local_time,timezone,created_at,updated_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "legacy-sub",
            "Legacy",
            "legacy topic",
            '["openalex"]',
            10,
            5,
            "weekly",
            6,
            "08:00",
            "Asia/Shanghai",
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    connection.commit()
    connection.close()

    migrated = Database(path)

    assert migrated.connection.execute("SELECT count(*) FROM papers").fetchone()[0] == 1
    assert migrated.connection.execute("SELECT count(*) FROM subscriptions").fetchone()[0] == 1
    assert migrated.connection.execute(
        "SELECT normalized_title FROM papers WHERE canonical_id='openalex:legacy'"
    ).fetchone()[0] == ""
    assert [row[0] for row in migrated.connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()] == [1, 2, 3, 4, 5]
    migrated.connection.close()
