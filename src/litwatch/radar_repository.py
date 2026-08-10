from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from threading import RLock

from litwatch.db import Database
from litwatch.radars import RadarScan, ResearchRadar


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

    def latest_successful_scan(self, radar_id: str) -> RadarScan | None:
        with self._lock:
            row = self.database.connection.execute(
                """SELECT * FROM radar_scans WHERE radar_id=?
                   AND status IN ('success','partial_success')
                   ORDER BY finished_at DESC,id DESC LIMIT 1""",
                (radar_id,),
            ).fetchone()
        return self._scan_from_row(row) if row is not None else None

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
