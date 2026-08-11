from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from litwatch.migrations import Migration, MigrationCoordinator
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
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_MIGRATION_SQL = (
    (
        1,
        "subscriptions",
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL CHECK(length(trim(name)) > 0),
            topic TEXT NOT NULL CHECK(length(trim(topic)) > 0),
            keywords_json TEXT NOT NULL DEFAULT '[]'
                CHECK(json_valid(keywords_json) AND json_type(keywords_json) = 'array'),
            providers_json TEXT NOT NULL
                CHECK(json_valid(providers_json) AND json_type(providers_json) = 'array'),
            search_limit INTEGER NOT NULL CHECK(search_limit BETWEEN 1 AND 50),
            recommendation_limit INTEGER NOT NULL CHECK(
                recommendation_limit BETWEEN 1 AND search_limit
            ),
            frequency TEXT NOT NULL CHECK(frequency = 'weekly'),
            weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
            local_time TEXT NOT NULL CHECK(
                length(local_time) = 5
                AND substr(local_time, 3, 1) = ':'
                AND local_time GLOB '[0-2][0-9]:[0-5][0-9]'
                AND CAST(substr(local_time, 1, 2) AS INTEGER) BETWEEN 0 AND 23
                AND CAST(substr(local_time, 4, 2) AS INTEGER) BETWEEN 0 AND 59
            ),
            timezone TEXT NOT NULL CHECK(length(trim(timezone)) > 0),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run_at TEXT,
            last_success_at TEXT,
            next_run_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_subscriptions_created
            ON subscriptions(created_at ASC, id ASC);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_enabled
            ON subscriptions(enabled, next_run_at);
        """,
    ),
    (
        2,
        "historical_paper_tracking",
        """
        ALTER TABLE papers
            ADD COLUMN normalized_title TEXT NOT NULL DEFAULT '';

        CREATE INDEX IF NOT EXISTS idx_papers_normalized_title
            ON papers(normalized_title);

        CREATE TABLE IF NOT EXISTS subscription_papers (
            subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE RESTRICT,
            canonical_id TEXT NOT NULL REFERENCES papers(canonical_id) ON DELETE RESTRICT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1 CHECK(seen_count >= 1),
            status TEXT NOT NULL DEFAULT 'seen' CHECK(status IN ('seen', 'recommended')),
            first_recommended_at TEXT,
            last_recommended_at TEXT,
            recommendation_count INTEGER NOT NULL DEFAULT 0
                CHECK(recommendation_count >= 0),
            last_rank_score REAL,
            last_relevance_score REAL,
            last_quality_score REAL,
            last_run_id INTEGER,
            PRIMARY KEY (subscription_id, canonical_id)
        );
        CREATE INDEX IF NOT EXISTS idx_subscription_papers_canonical
            ON subscription_papers(canonical_id);
        CREATE INDEX IF NOT EXISTS idx_subscription_papers_status
            ON subscription_papers(subscription_id, status, last_seen_at DESC);
        """,
    ),
    (
        3,
        "subscription_runs_and_recommendations",
        """
        CREATE TABLE IF NOT EXISTS subscription_runs (
            id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE RESTRICT,
            run_key TEXT NOT NULL UNIQUE,
            trigger TEXT NOT NULL CHECK(trigger IN ('manual', 'scheduled', 'catch_up')),
            scheduled_for_at TEXT,
            period_key TEXT,
            started_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'running', 'success', 'partial_success', 'failed', 'interrupted'
            )),
            attempt_count INTEGER NOT NULL DEFAULT 1 CHECK(attempt_count >= 1),
            lease_owner TEXT,
            lease_expires_at TEXT,
            raw_count INTEGER NOT NULL DEFAULT 0,
            dedup_count INTEGER NOT NULL DEFAULT 0,
            duplicates_removed INTEGER NOT NULL DEFAULT 0,
            historical_duplicates_removed INTEGER NOT NULL DEFAULT 0,
            new_count INTEGER NOT NULL DEFAULT 0,
            eligible_count INTEGER NOT NULL DEFAULT 0,
            recommended_count INTEGER NOT NULL DEFAULT 0,
            provider_status_json TEXT NOT NULL DEFAULT '[]'
                CHECK(json_valid(provider_status_json)),
            safe_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_subscription_runs_history
            ON subscription_runs(subscription_id, started_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_subscription_runs_active
            ON subscription_runs(subscription_id, status, lease_expires_at);

        CREATE TABLE IF NOT EXISTS recommendations (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES subscription_runs(id) ON DELETE RESTRICT,
            subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE RESTRICT,
            canonical_id TEXT NOT NULL REFERENCES papers(canonical_id) ON DELETE RESTRICT,
            rank_position INTEGER NOT NULL CHECK(rank_position >= 1),
            rank_score REAL NOT NULL,
            relevance_score REAL NOT NULL,
            quality_score REAL NOT NULL,
            score_detail_json TEXT NOT NULL DEFAULT '{}'
                CHECK(json_valid(score_detail_json)),
            recommended_at TEXT NOT NULL,
            UNIQUE(run_id, canonical_id),
            UNIQUE(subscription_id, canonical_id)
        );
        CREATE INDEX IF NOT EXISTS idx_recommendations_run
            ON recommendations(run_id, rank_position ASC);
        """,
    ),
    (
        4,
        "subscription_run_concurrency",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_subscription_runs_one_active
            ON subscription_runs(subscription_id) WHERE status = 'running';
        """,
    ),
    (
        5,
        "dashboard_deliveries",
        """
        CREATE TABLE IF NOT EXISTS deliveries (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES subscription_runs(id) ON DELETE RESTRICT,
            subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE RESTRICT,
            channel TEXT NOT NULL CHECK(channel IN ('dashboard', 'email')),
            status TEXT NOT NULL CHECK(status IN ('pending', 'delivered', 'failed')),
            digest_json TEXT NOT NULL CHECK(json_valid(digest_json)),
            attempted_at TEXT NOT NULL,
            delivered_at TEXT,
            safe_error TEXT,
            UNIQUE(run_id, channel)
        );
        CREATE INDEX IF NOT EXISTS idx_deliveries_history
            ON deliveries(subscription_id, attempted_at DESC, id DESC);
        """,
    ),
    (
        6,
        "research_radars",
        """
        CREATE TABLE IF NOT EXISTS research_radars (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL CHECK(length(trim(name)) > 0),
            topic TEXT NOT NULL CHECK(length(trim(topic)) > 0),
            keywords_json TEXT NOT NULL DEFAULT '[]'
                CHECK(json_valid(keywords_json) AND json_type(keywords_json) = 'array'),
            exclude_keywords_json TEXT NOT NULL DEFAULT '[]'
                CHECK(json_valid(exclude_keywords_json)
                      AND json_type(exclude_keywords_json) = 'array'),
            providers_json TEXT NOT NULL
                CHECK(json_valid(providers_json) AND json_type(providers_json) = 'array'),
            start_year INTEGER NOT NULL CHECK(start_year BETWEEN 1900 AND 2100),
            end_year INTEGER NOT NULL CHECK(end_year BETWEEN start_year AND 2100),
            recent_window_years INTEGER NOT NULL CHECK(recent_window_years BETWEEN 1 AND 5),
            search_limit_per_period INTEGER NOT NULL
                CHECK(search_limit_per_period BETWEEN 1 AND 50),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_scan_at TEXT,
            last_success_at TEXT,
            CHECK(end_year - start_year + 1 BETWEEN 1 AND 20),
            CHECK(recent_window_years <= end_year - start_year + 1)
        );
        CREATE INDEX IF NOT EXISTS idx_research_radars_created
            ON research_radars(created_at ASC,id ASC);
        CREATE INDEX IF NOT EXISTS idx_research_radars_enabled
            ON research_radars(enabled,updated_at DESC);

        CREATE TABLE IF NOT EXISTS radar_scans (
            id TEXT PRIMARY KEY,
            radar_id TEXT NOT NULL REFERENCES research_radars(id) ON DELETE RESTRICT,
            started_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN (
                'pending','running','success','partial_success','failed','interrupted'
            )),
            start_year INTEGER NOT NULL,
            end_year INTEGER NOT NULL,
            raw_count INTEGER NOT NULL DEFAULT 0 CHECK(raw_count >= 0),
            dedup_count INTEGER NOT NULL DEFAULT 0 CHECK(dedup_count >= 0),
            new_count INTEGER NOT NULL DEFAULT 0 CHECK(new_count >= 0),
            provider_status_json TEXT NOT NULL DEFAULT '[]'
                CHECK(json_valid(provider_status_json)),
            analysis_json TEXT NOT NULL DEFAULT '{}'
                CHECK(json_valid(analysis_json)),
            safe_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_radar_scans_history
            ON radar_scans(radar_id,started_at DESC,id DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_scans_one_active
            ON radar_scans(radar_id) WHERE status = 'running';

        CREATE TABLE IF NOT EXISTS radar_papers (
            radar_id TEXT NOT NULL REFERENCES research_radars(id) ON DELETE RESTRICT,
            canonical_id TEXT NOT NULL REFERENCES papers(canonical_id) ON DELETE RESTRICT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            first_scan_id TEXT NOT NULL REFERENCES radar_scans(id) ON DELETE RESTRICT,
            last_scan_id TEXT NOT NULL REFERENCES radar_scans(id) ON DELETE RESTRICT,
            publication_year INTEGER,
            relevance_score REAL NOT NULL DEFAULT 0 CHECK(
                relevance_score BETWEEN 0 AND 1
            ),
            representative_score REAL NOT NULL DEFAULT 0 CHECK(
                representative_score BETWEEN 0 AND 1
            ),
            PRIMARY KEY (radar_id,canonical_id)
        );
        CREATE INDEX IF NOT EXISTS idx_radar_papers_year
            ON radar_papers(radar_id,publication_year,canonical_id);
        CREATE INDEX IF NOT EXISTS idx_radar_papers_canonical
            ON radar_papers(canonical_id);
        """,
    ),
)

MIGRATION_REGISTRY = tuple(
    Migration.from_sql(version, name, sql) for version, name, sql in _MIGRATION_SQL
)
# Compatibility view for v1.7 callers and tests that unpack the historical tuple format.
MIGRATIONS = tuple(
    (migration.version, migration.name, migration.sql)
    for migration in MIGRATION_REGISTRY
)


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        MigrationCoordinator(self.connection, MIGRATION_REGISTRY).migrate()

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
                   analysis_json=CASE
                       WHEN json_extract(excluded.analysis_json, '$.status') = 'error'
                            AND json_extract(paper_topics.analysis_json, '$.status') IN ('ok', 'extractive')
                       THEN paper_topics.analysis_json
                       ELSE excluded.analysis_json
                   END,
                   run_id=excluded.run_id""",
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

    def list_papers(
        self, *, topic_id: str = "", run_id: int | None = None, limit: int = 100
    ) -> list[dict]:
        filters: list[str] = []
        values: list[object] = []
        if topic_id:
            filters.append("topic_id=?")
            values.append(topic_id)
        if run_id is not None:
            filters.append("run_id=?")
            values.append(run_id)
        where = "WHERE " + " AND ".join(filters) if filters else ""
        values.append(limit)
        rows = self.connection.execute(
            f"""SELECT p.*,pt.topic_id,pt.topic_name,pt.score,pt.score_detail_json,
                       pt.analysis_json,pt.run_id
                FROM papers p JOIN (
                    SELECT canonical_id, topic_id, topic_name, score, score_detail_json,
                           analysis_json, run_id,
                           ROW_NUMBER() OVER (PARTITION BY canonical_id ORDER BY score DESC) AS rn
                    FROM paper_topics
                    {where}
                ) pt USING(canonical_id)
                WHERE pt.rn = 1
                ORDER BY pt.score DESC,p.publication_date DESC LIMIT ?""",
            tuple(values),
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

    def paper_analysis(self, canonical_id: str, topic_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT analysis_json FROM paper_topics WHERE canonical_id=? AND topic_id=?",
            (canonical_id, topic_id),
        ).fetchone()
        if not row:
            return None
        return json.loads(row["analysis_json"])

    def list_topics(self) -> list[dict[str, str]]:
        rows = self.connection.execute(
            """SELECT topic_id AS id, topic_name AS name
               FROM paper_topics GROUP BY topic_id, topic_name ORDER BY topic_name"""
        ).fetchall()
        return [dict(row) for row in rows]
