from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from litwatch.models import Paper

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    fetched INTEGER NOT NULL DEFAULT 0,
    deduplicated INTEGER NOT NULL DEFAULT 0,
    accepted INTEGER NOT NULL DEFAULT 0,
    analyzed INTEGER NOT NULL DEFAULT 0,
    errors_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS papers (
    canonical_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL DEFAULT '',
    authors_json TEXT NOT NULL DEFAULT '[]',
    publication_date TEXT,
    venue TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    is_open_access INTEGER NOT NULL DEFAULT 0,
    citation_count INTEGER NOT NULL DEFAULT 0,
    sources_json TEXT NOT NULL DEFAULT '[]',
    source_ids_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_topics (
    canonical_id TEXT NOT NULL REFERENCES papers(canonical_id),
    topic_id TEXT NOT NULL,
    topic_name TEXT NOT NULL,
    score REAL NOT NULL,
    score_detail_json TEXT NOT NULL DEFAULT '{}',
    analysis_json TEXT NOT NULL DEFAULT '{}',
    run_id INTEGER NOT NULL REFERENCES runs(id),
    PRIMARY KEY (canonical_id, topic_id)
);
CREATE INDEX IF NOT EXISTS idx_paper_topics_score ON paper_topics(score DESC);
CREATE INDEX IF NOT EXISTS idx_papers_date ON papers(publication_date DESC);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def start_run(self) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs(started_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        fetched: int,
        deduplicated: int,
        accepted: int,
        analyzed: int,
        errors: list[str],
    ) -> None:
        self.connection.execute(
            """UPDATE runs SET finished_at=?, fetched=?, deduplicated=?, accepted=?, analyzed=?, errors_json=?
               WHERE id=?""",
            (
                datetime.now(UTC).isoformat(),
                fetched,
                deduplicated,
                accepted,
                analyzed,
                json.dumps(errors, ensure_ascii=False),
                run_id,
            ),
        )
        self.connection.commit()

    def upsert(self, paper: Paper, run_id: int) -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """INSERT INTO papers(
                   canonical_id,title,abstract,authors_json,publication_date,venue,doi,url,pdf_url,
                   is_open_access,citation_count,sources_json,source_ids_json,first_seen_at,last_seen_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(canonical_id) DO UPDATE SET
                   title=excluded.title,
                   abstract=CASE WHEN length(excluded.abstract)>length(papers.abstract) THEN excluded.abstract ELSE papers.abstract END,
                   authors_json=excluded.authors_json,
                   publication_date=COALESCE(excluded.publication_date,papers.publication_date),
                   venue=CASE WHEN excluded.venue<>'' THEN excluded.venue ELSE papers.venue END,
                   doi=CASE WHEN excluded.doi<>'' THEN excluded.doi ELSE papers.doi END,
                   url=CASE WHEN excluded.url<>'' THEN excluded.url ELSE papers.url END,
                   pdf_url=CASE WHEN excluded.pdf_url<>'' THEN excluded.pdf_url ELSE papers.pdf_url END,
                   is_open_access=max(papers.is_open_access,excluded.is_open_access),
                   citation_count=max(papers.citation_count,excluded.citation_count),
                   sources_json=excluded.sources_json,
                   source_ids_json=excluded.source_ids_json,
                   last_seen_at=excluded.last_seen_at""",
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
        self.connection.execute(
            """INSERT INTO paper_topics(
                   canonical_id,topic_id,topic_name,score,score_detail_json,analysis_json,run_id
               ) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(canonical_id,topic_id) DO UPDATE SET
                   topic_name=excluded.topic_name, score=excluded.score,
                   score_detail_json=excluded.score_detail_json,
                   analysis_json=excluded.analysis_json, run_id=excluded.run_id""",
            (
                paper.canonical_id,
                paper.topic_id,
                paper.topic_name,
                paper.score,
                json.dumps(paper.score_detail, ensure_ascii=False),
                json.dumps(paper.analysis, ensure_ascii=False),
                run_id,
            ),
        )
        self.connection.commit()

    def list_papers(self, *, topic_id: str = "", limit: int = 100) -> list[dict]:
        where = "WHERE pt.topic_id=?" if topic_id else ""
        params: tuple[object, ...] = (topic_id, limit) if topic_id else (limit,)
        rows = self.connection.execute(
            f"""SELECT p.*,pt.topic_id,pt.topic_name,pt.score,pt.score_detail_json,pt.analysis_json
                FROM papers p JOIN paper_topics pt USING(canonical_id)
                {where}
                ORDER BY pt.score DESC,p.publication_date DESC LIMIT ?""",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in (
                "authors_json",
                "sources_json",
                "source_ids_json",
                "score_detail_json",
                "analysis_json",
            ):
                item[key.removesuffix("_json")] = json.loads(item.pop(key))
            result.append(item)
        return result

    def latest_run(self) -> dict | None:
        row = self.connection.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        item = dict(row)
        item["errors"] = json.loads(item.pop("errors_json"))
        return item

    def list_topics(self) -> list[dict[str, str]]:
        rows = self.connection.execute(
            """SELECT topic_id AS id, topic_name AS name
               FROM paper_topics GROUP BY topic_id, topic_name ORDER BY topic_name"""
        ).fetchall()
        return [dict(row) for row in rows]
