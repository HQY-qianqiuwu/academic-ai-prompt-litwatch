"""Durable, immutable scan snapshots and stable paper identities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from litwatch.db import Database
from litwatch.models import Paper
from litwatch.services.scan import ScanResult


@dataclass(frozen=True, slots=True)
class SavedScan:
    scan_id: str
    paper_ids: dict[str, str]


@dataclass(frozen=True, slots=True)
class SavedPaper:
    scan_id: str
    paper_id: str
    query: str
    paper: Paper


class SearchScanRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, result: ScanResult) -> SavedScan:
        scan_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        paper_ids: dict[str, str] = {}
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO search_scans(scan_id,query,status,result_json,created_at)
                   VALUES (?,?,?,?,?)""",
                (scan_id, result.query, result.status.value, result.model_dump_json(), now),
            )
            for position, paper in enumerate(result.papers):
                connection.execute(
                    """INSERT OR IGNORE INTO papers(
                           canonical_id,title,abstract,authors_json,publication_date,
                           venue,doi,url,pdf_url,is_open_access,citation_count,
                           sources_json,source_ids_json,first_seen_at,last_seen_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        paper.canonical_id,
                        paper.title,
                        paper.abstract,
                        json.dumps([author.model_dump() for author in paper.authors], ensure_ascii=False),
                        paper.publication_date.isoformat() if paper.publication_date else None,
                        paper.venue,
                        paper.doi,
                        paper.url,
                        paper.pdf_url,
                        int(paper.is_open_access),
                        paper.citation_count,
                        json.dumps(paper.sources, ensure_ascii=False),
                        json.dumps(paper.source_ids, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """INSERT INTO paper_identities(paper_id,canonical_id)
                       VALUES (?,?) ON CONFLICT(canonical_id) DO NOTHING""",
                    (uuid4().hex, paper.canonical_id),
                )
                row = connection.execute(
                    "SELECT paper_id FROM paper_identities WHERE canonical_id=?",
                    (paper.canonical_id,),
                ).fetchone()
                if row is None:  # pragma: no cover - insert and read share a transaction
                    raise RuntimeError("paper identity was not persisted")
                paper_id = str(row[0])
                connection.execute(
                    """INSERT INTO search_scan_papers(scan_id,paper_id,position,paper_json)
                       VALUES (?,?,?,?)""",
                    (scan_id, paper_id, position, paper.model_dump_json()),
                )
                paper_ids[paper.canonical_id] = paper_id
        return SavedScan(scan_id=scan_id, paper_ids=paper_ids)

    def get_scan(self, scan_id: str) -> ScanResult | None:
        with self.database.transaction_lock:
            row = self.database.connection.execute(
                "SELECT result_json FROM search_scans WHERE scan_id=?", (scan_id,)
            ).fetchone()
        return ScanResult.model_validate_json(str(row[0])) if row is not None else None

    def get_paper(self, scan_id: str, paper_id: str) -> SavedPaper | None:
        with self.database.transaction_lock:
            row = self.database.connection.execute(
                """SELECT s.query,sp.paper_json FROM search_scan_papers sp
                   JOIN search_scans s USING(scan_id)
                   WHERE sp.scan_id=? AND sp.paper_id=?""",
                (scan_id, paper_id),
            ).fetchone()
        if row is None:
            return None
        return SavedPaper(
            scan_id=scan_id,
            paper_id=paper_id,
            query=str(row[0]),
            paper=Paper.model_validate_json(str(row[1])),
        )
