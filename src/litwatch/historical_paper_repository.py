from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from threading import RLock

from litwatch.db import Database
from litwatch.models import Paper
from litwatch.paper_history import ObservationResult, SubscriptionPaperHistory
from litwatch.services.deduplication import (
    merge_paper_group,
    normalize_doi,
    papers_are_duplicates,
)
from litwatch.text import normalize_title


class HistoricalPaperRepository:
    """Atomically persist global paper metadata and per-subscription observations."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._lock = RLock()

    def observe(
        self,
        subscription_id: str,
        papers: Iterable[Paper],
        observed_at: datetime,
        run_id: str | None = None,
    ) -> ObservationResult:
        observed_at = self._aware_utc(observed_at)
        incoming_papers = sorted(
            (paper.model_copy(deep=True) for paper in papers),
            key=lambda paper: paper.canonical_id.casefold(),
        )
        new_papers: list[Paper] = []
        seen_papers: list[Paper] = []
        updated_papers: list[Paper] = []

        with self._lock, self.database.connection:
            subscription = self.database.connection.execute(
                "SELECT 1 FROM subscriptions WHERE id=?", (subscription_id,)
            ).fetchone()
            if subscription is None:
                raise KeyError(subscription_id)

            stored_papers = self._load_all_papers()
            for incoming in incoming_papers:
                stored = self._find_match(incoming, stored_papers)
                if stored is None:
                    resolved = self._normalize_new_paper(incoming)
                    first_seen_at = observed_at
                    metadata_updated = False
                else:
                    resolved = self._merge_preserving_history_identity(stored, incoming)
                    first_seen_at = self._paper_first_seen(stored.canonical_id)
                    metadata_updated = self._metadata_signature(stored) != self._metadata_signature(
                        resolved
                    )

                relation = self.database.connection.execute(
                    """SELECT * FROM subscription_papers
                       WHERE subscription_id=? AND canonical_id=?""",
                    (subscription_id, resolved.canonical_id),
                ).fetchone()
                is_new_for_subscription = relation is None

                self._upsert_paper(resolved, first_seen_at, observed_at)
                self._upsert_observation(
                    subscription_id,
                    resolved,
                    observed_at,
                    relation,
                    run_id,
                )

                stored_papers = [
                    paper
                    for paper in stored_papers
                    if paper.canonical_id != resolved.canonical_id
                ]
                stored_papers.append(resolved.model_copy(deep=True))
                if is_new_for_subscription:
                    new_papers.append(resolved)
                else:
                    seen_papers.append(resolved)
                if metadata_updated:
                    updated_papers.append(resolved)

        key = lambda paper: paper.canonical_id.casefold()
        return ObservationResult(
            new_papers=sorted(new_papers, key=key),
            seen_papers=sorted(seen_papers, key=key),
            updated_papers=sorted(updated_papers, key=key),
        )

    def upsert_global_papers(
        self, papers: Iterable[Paper], observed_at: datetime
    ) -> list[Paper]:
        """Reuse global identity and enrichment without changing feature history."""
        observed_at = self._aware_utc(observed_at)
        incoming_papers = sorted(
            (paper.model_copy(deep=True) for paper in papers),
            key=lambda paper: paper.canonical_id.casefold(),
        )
        resolved_papers: list[Paper] = []
        with self._lock, self.database.connection:
            stored_papers = self._load_all_papers()
            for incoming in incoming_papers:
                stored = self._find_match(incoming, stored_papers)
                if stored is None:
                    resolved = self._normalize_new_paper(incoming)
                    first_seen_at = observed_at
                else:
                    resolved = self._merge_preserving_history_identity(stored, incoming)
                    first_seen_at = self._paper_first_seen(stored.canonical_id)
                self._upsert_paper(resolved, first_seen_at, observed_at)
                stored_papers = [
                    paper
                    for paper in stored_papers
                    if paper.canonical_id != resolved.canonical_id
                ]
                stored_papers.append(resolved.model_copy(deep=True))
                resolved_papers.append(resolved)
        return resolved_papers

    def get_paper(self, canonical_id: str) -> Paper | None:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT * FROM papers WHERE canonical_id=?", (canonical_id,)
            ).fetchone()
        return self._paper_from_row(row) if row is not None else None

    def get_subscription_paper(
        self, subscription_id: str, canonical_id: str
    ) -> SubscriptionPaperHistory | None:
        with self._lock:
            row = self.database.connection.execute(
                """SELECT * FROM subscription_papers
                   WHERE subscription_id=? AND canonical_id=?""",
                (subscription_id, canonical_id),
            ).fetchone()
        return self._history_from_row(row) if row is not None else None

    def mark_recommended(
        self,
        subscription_id: str,
        canonical_id: str,
        recommended_at: datetime,
        *,
        rank_score: float | None = None,
        relevance_score: float | None = None,
        quality_score: float | None = None,
        run_id: str | None = None,
    ) -> SubscriptionPaperHistory:
        recommended_at = self._aware_utc(recommended_at)
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE subscription_papers SET
                       status='recommended',
                       first_recommended_at=COALESCE(first_recommended_at, ?),
                       last_recommended_at=?,
                       recommendation_count=recommendation_count + 1,
                       last_rank_score=?, last_relevance_score=?, last_quality_score=?,
                       last_run_id=?
                   WHERE subscription_id=? AND canonical_id=?""",
                (
                    recommended_at.isoformat(),
                    recommended_at.isoformat(),
                    rank_score,
                    relevance_score,
                    quality_score,
                    run_id,
                    subscription_id,
                    canonical_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError((subscription_id, canonical_id))
            row = self.database.connection.execute(
                """SELECT * FROM subscription_papers
                   WHERE subscription_id=? AND canonical_id=?""",
                (subscription_id, canonical_id),
            ).fetchone()
        return self._history_from_row(row)

    def _load_all_papers(self) -> list[Paper]:
        rows = self.database.connection.execute(
            "SELECT * FROM papers ORDER BY canonical_id"
        ).fetchall()
        return [self._paper_from_row(row) for row in rows]

    @staticmethod
    def _find_match(incoming: Paper, stored_papers: list[Paper]) -> Paper | None:
        matches = [paper for paper in stored_papers if papers_are_duplicates(paper, incoming)]
        return min(matches, key=lambda paper: paper.canonical_id.casefold()) if matches else None

    @staticmethod
    def _normalize_new_paper(incoming: Paper) -> Paper:
        normalized = merge_paper_group([incoming])
        normalized.score = incoming.score
        normalized.score_detail = incoming.score_detail.copy()
        normalized.topic_id = incoming.topic_id
        normalized.topic_name = incoming.topic_name
        normalized.analysis = incoming.analysis.copy()
        return normalized

    @staticmethod
    def _merge_preserving_history_identity(stored: Paper, incoming: Paper) -> Paper:
        merged = merge_paper_group([stored, incoming])
        merged.canonical_id = stored.canonical_id
        merged.score = incoming.score
        merged.score_detail = incoming.score_detail.copy()
        merged.topic_id = incoming.topic_id
        merged.topic_name = incoming.topic_name
        merged.analysis = incoming.analysis.copy()
        return merged

    def _paper_first_seen(self, canonical_id: str) -> datetime:
        row = self.database.connection.execute(
            "SELECT first_seen_at FROM papers WHERE canonical_id=?", (canonical_id,)
        ).fetchone()
        if row is None:
            raise KeyError(canonical_id)
        return datetime.fromisoformat(row["first_seen_at"]).astimezone(UTC)

    def _upsert_paper(
        self, paper: Paper, first_seen_at: datetime, last_seen_at: datetime
    ) -> None:
        self.database.connection.execute(
            """INSERT INTO papers(
                   canonical_id,title,normalized_title,abstract,authors_json,publication_date,
                   venue,doi,url,pdf_url,is_open_access,citation_count,sources_json,
                   source_ids_json,first_seen_at,last_seen_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(canonical_id) DO UPDATE SET
                   title=excluded.title, normalized_title=excluded.normalized_title,
                   abstract=excluded.abstract, authors_json=excluded.authors_json,
                   publication_date=excluded.publication_date, venue=excluded.venue,
                   doi=excluded.doi, url=excluded.url, pdf_url=excluded.pdf_url,
                   is_open_access=excluded.is_open_access,
                   citation_count=excluded.citation_count,
                   sources_json=excluded.sources_json, source_ids_json=excluded.source_ids_json,
                   first_seen_at=min(papers.first_seen_at, excluded.first_seen_at),
                   last_seen_at=max(papers.last_seen_at, excluded.last_seen_at)""",
            (
                paper.canonical_id,
                paper.title,
                normalize_title(paper.title),
                paper.abstract,
                json.dumps([author.model_dump() for author in paper.authors], ensure_ascii=False),
                paper.publication_date.isoformat() if paper.publication_date else None,
                paper.venue,
                normalize_doi(paper.doi),
                paper.url,
                paper.pdf_url,
                int(paper.is_open_access),
                paper.citation_count,
                json.dumps(paper.sources, ensure_ascii=False),
                json.dumps(paper.source_ids, ensure_ascii=False),
                first_seen_at.isoformat(),
                last_seen_at.isoformat(),
            ),
        )

    def _upsert_observation(
        self,
        subscription_id: str,
        paper: Paper,
        observed_at: datetime,
        existing: sqlite3.Row | None,
        run_id: str | None,
    ) -> None:
        if existing is None:
            self.database.connection.execute(
                """INSERT INTO subscription_papers(
                       subscription_id,canonical_id,first_seen_at,last_seen_at,seen_count,
                       last_rank_score,last_relevance_score,last_quality_score,last_run_id
                   ) VALUES (?,?,?,?,1,?,?,?,?)""",
                (
                    subscription_id,
                    paper.canonical_id,
                    observed_at.isoformat(),
                    observed_at.isoformat(),
                    paper.score,
                    self._score(paper, "relevance"),
                    self._score(paper, "quality"),
                    run_id,
                ),
            )
            return
        self.database.connection.execute(
            """UPDATE subscription_papers SET
                   first_seen_at=min(first_seen_at, ?),
                   last_seen_at=max(last_seen_at, ?),
                   seen_count=seen_count + 1,
                   last_rank_score=?, last_relevance_score=?, last_quality_score=?,last_run_id=?
               WHERE subscription_id=? AND canonical_id=?""",
            (
                observed_at.isoformat(),
                observed_at.isoformat(),
                paper.score,
                self._score(paper, "relevance"),
                self._score(paper, "quality"),
                run_id,
                subscription_id,
                paper.canonical_id,
            ),
        )

    @staticmethod
    def _score(paper: Paper, name: str) -> float | None:
        value = paper.score_detail.get(name)
        return float(value) if isinstance(value, int | float) else None

    @staticmethod
    def _metadata_signature(paper: Paper) -> tuple[object, ...]:
        return (
            paper.title,
            paper.abstract,
            tuple(author.name for author in paper.authors),
            paper.publication_date,
            paper.venue,
            normalize_doi(paper.doi),
            paper.url,
            paper.pdf_url,
            paper.is_open_access,
            paper.citation_count,
            tuple(sorted(paper.sources)),
            tuple(sorted(paper.source_ids.items())),
        )

    @staticmethod
    def _paper_from_row(row: sqlite3.Row) -> Paper:
        return Paper.model_validate(
            {
                "canonical_id": row["canonical_id"],
                "title": row["title"],
                "abstract": row["abstract"],
                "authors": json.loads(row["authors_json"]),
                "publication_date": row["publication_date"],
                "venue": row["venue"],
                "doi": row["doi"],
                "url": row["url"],
                "pdf_url": row["pdf_url"],
                "is_open_access": bool(row["is_open_access"]),
                "citation_count": row["citation_count"],
                "sources": json.loads(row["sources_json"]),
                "source_ids": json.loads(row["source_ids_json"]),
            }
        )

    @staticmethod
    def _history_from_row(row: sqlite3.Row) -> SubscriptionPaperHistory:
        return SubscriptionPaperHistory.model_validate(dict(row))

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation timestamps must be timezone-aware")
        return value.astimezone(UTC)
