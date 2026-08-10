from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from threading import RLock

from litwatch.db import Database
from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.models import Paper
from litwatch.radars import RadarObservationResult, RadarPaper, RadarScan, ResearchRadar


class RadarRepository:
    """SQLite persistence for Radar configuration and scan history."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._lock = RLock()

    def create(self, radar: ResearchRadar) -> ResearchRadar:
        with self._lock, self.database.connection:
            self.database.connection.execute(
                """INSERT INTO research_radars(
                       id,name,topic,keywords_json,exclude_keywords_json,providers_json,
                       start_year,end_year,recent_window_years,search_limit_per_period,
                       enabled,created_at,updated_at,last_scan_at,last_success_at
                   ) VALUES (
                       :id,:name,:topic,:keywords_json,:exclude_keywords_json,:providers_json,
                       :start_year,:end_year,:recent_window_years,:search_limit_per_period,
                       :enabled,:created_at,:updated_at,:last_scan_at,:last_success_at
                   )""",
                self._radar_values(radar),
            )
        return radar.model_copy(deep=True)

    def list(self) -> list[ResearchRadar]:
        with self._lock:
            rows = self.database.connection.execute(
                "SELECT * FROM research_radars ORDER BY created_at ASC,id ASC"
            ).fetchall()
        return [self._radar_from_row(row) for row in rows]

    def get(self, radar_id: str) -> ResearchRadar | None:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT * FROM research_radars WHERE id=?", (radar_id,)
            ).fetchone()
        return self._radar_from_row(row) if row is not None else None

    def exists(self, radar_id: str) -> bool:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT 1 FROM research_radars WHERE id=?", (radar_id,)
            ).fetchone()
        return row is not None

    def update(self, radar: ResearchRadar) -> ResearchRadar:
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE research_radars SET
                       name=:name,topic=:topic,keywords_json=:keywords_json,
                       exclude_keywords_json=:exclude_keywords_json,
                       providers_json=:providers_json,start_year=:start_year,
                       end_year=:end_year,recent_window_years=:recent_window_years,
                       search_limit_per_period=:search_limit_per_period,enabled=:enabled,
                       updated_at=:updated_at,last_scan_at=:last_scan_at,
                       last_success_at=:last_success_at
                   WHERE id=:id""",
                self._radar_values(radar),
            )
        if cursor.rowcount != 1:
            raise KeyError(radar.id)
        return radar.model_copy(deep=True)

    def create_scan(self, scan: RadarScan) -> RadarScan:
        with self._lock, self.database.connection:
            self.database.connection.execute(
                """INSERT INTO radar_scans(
                       id,radar_id,started_at,heartbeat_at,finished_at,status,
                       start_year,end_year,raw_count,dedup_count,new_count,
                       provider_status_json,analysis_json,safe_error
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                self._scan_values(scan),
            )
        return scan.model_copy(deep=True)

    def update_scan(self, scan: RadarScan) -> RadarScan:
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE radar_scans SET
                       heartbeat_at=?,finished_at=?,status=?,raw_count=?,dedup_count=?,
                       new_count=?,provider_status_json=?,analysis_json=?,safe_error=?
                   WHERE id=?""",
                (
                    scan.heartbeat_at.isoformat(),
                    self._serialize_datetime(scan.finished_at),
                    scan.status.value,
                    scan.raw_count,
                    scan.dedup_count,
                    scan.new_count,
                    json.dumps(scan.provider_status, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(scan.analysis, ensure_ascii=False, separators=(",", ":")),
                    scan.safe_error,
                    scan.id,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(scan.id)
        return scan.model_copy(deep=True)

    def get_scan(self, scan_id: str) -> RadarScan | None:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT * FROM radar_scans WHERE id=?", (scan_id,)
            ).fetchone()
        return self._scan_from_row(row) if row is not None else None

    def list_scans(self, radar_id: str) -> list[RadarScan]:
        with self._lock:
            rows = self.database.connection.execute(
                """SELECT * FROM radar_scans
                   WHERE radar_id=? ORDER BY started_at DESC,id DESC""",
                (radar_id,),
            ).fetchall()
        return [self._scan_from_row(row) for row in rows]

    def latest_scan(self, radar_id: str) -> RadarScan | None:
        with self._lock:
            row = self.database.connection.execute(
                """SELECT * FROM radar_scans WHERE radar_id=?
                   ORDER BY started_at DESC,id DESC LIMIT 1""",
                (radar_id,),
            ).fetchone()
        return self._scan_from_row(row) if row is not None else None

    def latest_successful_scan(self, radar_id: str) -> RadarScan | None:
        with self._lock:
            row = self.database.connection.execute(
                """SELECT * FROM radar_scans WHERE radar_id=?
                   AND status IN ('success','partial_success')
                   ORDER BY finished_at DESC,id DESC LIMIT 1""",
                (radar_id,),
            ).fetchone()
        return self._scan_from_row(row) if row is not None else None

    def observe_papers(
        self,
        radar_id: str,
        scan_id: str,
        papers: Iterable[Paper],
        observed_at: datetime,
    ) -> RadarObservationResult:
        observed_at = self._aware_utc(observed_at)
        resolved_papers = HistoricalPaperRepository(
            self.database
        ).upsert_global_papers(papers, observed_at)
        new_papers: list[Paper] = []
        seen_papers: list[Paper] = []
        updated_papers: list[Paper] = []
        with self._lock, self.database.connection:
            if not self.exists(radar_id):
                raise KeyError(radar_id)
            if self.get_scan(scan_id) is None:
                raise KeyError(scan_id)
            for paper in resolved_papers:
                relation = self.database.connection.execute(
                    """SELECT * FROM radar_papers
                       WHERE radar_id=? AND canonical_id=?""",
                    (radar_id, paper.canonical_id),
                ).fetchone()
                relevance = self._score(paper, "relevance_score", paper.score)
                publication_year = (
                    paper.publication_date.year if paper.publication_date else None
                )
                if relation is None:
                    self.database.connection.execute(
                        """INSERT INTO radar_papers(
                               radar_id,canonical_id,first_seen_at,last_seen_at,
                               first_scan_id,last_scan_id,publication_year,relevance_score,
                               representative_score
                           ) VALUES (?,?,?,?,?,?,?,?,0)""",
                        (
                            radar_id,
                            paper.canonical_id,
                            observed_at.isoformat(),
                            observed_at.isoformat(),
                            scan_id,
                            scan_id,
                            publication_year,
                            relevance,
                        ),
                    )
                    new_papers.append(paper)
                    continue
                old_signature = (
                    relation["publication_year"],
                    float(relation["relevance_score"]),
                )
                new_signature = (publication_year, relevance)
                self.database.connection.execute(
                    """UPDATE radar_papers SET
                           last_seen_at=?,last_scan_id=?,publication_year=?,relevance_score=?
                       WHERE radar_id=? AND canonical_id=?""",
                    (
                        observed_at.isoformat(),
                        scan_id,
                        publication_year,
                        relevance,
                        radar_id,
                        paper.canonical_id,
                    ),
                )
                seen_papers.append(paper)
                if old_signature != new_signature:
                    updated_papers.append(paper)
        key = lambda paper: paper.canonical_id.casefold()
        return RadarObservationResult(
            new_papers=sorted(new_papers, key=key),
            seen_papers=sorted(seen_papers, key=key),
            updated_papers=sorted(updated_papers, key=key),
        )

    def list_papers(self, radar_id: str) -> list[Paper]:
        with self._lock:
            rows = self.database.connection.execute(
                """SELECT p.* FROM radar_papers rp
                   JOIN papers p USING(canonical_id)
                   WHERE rp.radar_id=?
                   ORDER BY rp.publication_year ASC,p.canonical_id ASC""",
                (radar_id,),
            ).fetchall()
        return [HistoricalPaperRepository._paper_from_row(row) for row in rows]

    def list_paper_relations(self, radar_id: str) -> list[RadarPaper]:
        with self._lock:
            rows = self.database.connection.execute(
                """SELECT * FROM radar_papers WHERE radar_id=?
                   ORDER BY publication_year ASC,canonical_id ASC""",
                (radar_id,),
            ).fetchall()
        return [RadarPaper.model_validate(dict(row)) for row in rows]

    def record_scan_attempt(
        self, radar_id: str, *, scan_at: datetime, successful: bool
    ) -> None:
        scan_at = self._aware_utc(scan_at)
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE research_radars SET
                       last_scan_at=?,
                       last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END
                   WHERE id=?""",
                (scan_at.isoformat(), int(successful), scan_at.isoformat(), radar_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(radar_id)

    def update_representative_scores(
        self, radar_id: str, scores: Mapping[str, float]
    ) -> None:
        with self._lock, self.database.connection:
            self.database.connection.execute(
                "UPDATE radar_papers SET representative_score=0 WHERE radar_id=?",
                (radar_id,),
            )
            for canonical_id, score in sorted(scores.items()):
                self.database.connection.execute(
                    """UPDATE radar_papers SET representative_score=?
                       WHERE radar_id=? AND canonical_id=?""",
                    (min(1.0, max(0.0, float(score))), radar_id, canonical_id),
                )

    def recover_stale_scans(
        self, *, stale_before: datetime, recovered_at: datetime
    ) -> int:
        stale_before = self._aware_utc(stale_before)
        recovered_at = self._aware_utc(recovered_at)
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE radar_scans SET
                       status='interrupted',finished_at=?,heartbeat_at=?,
                       safe_error='interrupted'
                   WHERE status='running' AND heartbeat_at < ?""",
                (
                    recovered_at.isoformat(),
                    recovered_at.isoformat(),
                    stale_before.isoformat(),
                ),
            )
        return cursor.rowcount

    @staticmethod
    def _radar_values(radar: ResearchRadar) -> Mapping[str, object]:
        return {
            "id": radar.id,
            "name": radar.name,
            "topic": radar.topic,
            "keywords_json": json.dumps(radar.keywords, ensure_ascii=False, separators=(",", ":")),
            "exclude_keywords_json": json.dumps(
                radar.exclude_keywords, ensure_ascii=False, separators=(",", ":")
            ),
            "providers_json": json.dumps(
                radar.providers, ensure_ascii=False, separators=(",", ":")
            ),
            "start_year": radar.start_year,
            "end_year": radar.end_year,
            "recent_window_years": radar.recent_window_years,
            "search_limit_per_period": radar.search_limit_per_period,
            "enabled": int(radar.enabled),
            "created_at": radar.created_at.isoformat(),
            "updated_at": radar.updated_at.isoformat(),
            "last_scan_at": RadarRepository._serialize_datetime(radar.last_scan_at),
            "last_success_at": RadarRepository._serialize_datetime(radar.last_success_at),
        }

    @staticmethod
    def _scan_values(scan: RadarScan) -> tuple[object, ...]:
        return (
            scan.id,
            scan.radar_id,
            scan.started_at.isoformat(),
            scan.heartbeat_at.isoformat(),
            RadarRepository._serialize_datetime(scan.finished_at),
            scan.status.value,
            scan.start_year,
            scan.end_year,
            scan.raw_count,
            scan.dedup_count,
            scan.new_count,
            json.dumps(scan.provider_status, ensure_ascii=False, separators=(",", ":")),
            json.dumps(scan.analysis, ensure_ascii=False, separators=(",", ":")),
            scan.safe_error,
        )

    @staticmethod
    def _radar_from_row(row: sqlite3.Row) -> ResearchRadar:
        return ResearchRadar.model_validate(
            {
                "id": row["id"],
                "name": row["name"],
                "topic": row["topic"],
                "keywords": json.loads(row["keywords_json"]),
                "exclude_keywords": json.loads(row["exclude_keywords_json"]),
                "providers": json.loads(row["providers_json"]),
                "start_year": row["start_year"],
                "end_year": row["end_year"],
                "recent_window_years": row["recent_window_years"],
                "search_limit_per_period": row["search_limit_per_period"],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_scan_at": row["last_scan_at"],
                "last_success_at": row["last_success_at"],
            }
        )

    @staticmethod
    def _scan_from_row(row: sqlite3.Row) -> RadarScan:
        return RadarScan.model_validate(
            {
                "id": row["id"],
                "radar_id": row["radar_id"],
                "started_at": row["started_at"],
                "heartbeat_at": row["heartbeat_at"],
                "finished_at": row["finished_at"],
                "status": row["status"],
                "start_year": row["start_year"],
                "end_year": row["end_year"],
                "raw_count": row["raw_count"],
                "dedup_count": row["dedup_count"],
                "new_count": row["new_count"],
                "provider_status": json.loads(row["provider_status_json"]),
                "analysis": json.loads(row["analysis_json"]),
                "safe_error": row["safe_error"],
            }
        )

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _score(paper: Paper, name: str, fallback: float) -> float:
        value = paper.score_detail.get(name)
        score = float(value) if isinstance(value, int | float) else float(fallback)
        return min(1.0, max(0.0, score))

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Radar timestamps must be timezone-aware")
        return value.astimezone(UTC)
