from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from threading import RLock

from litwatch.db import Database
from litwatch.subscription_runs import Recommendation, SubscriptionRun


class SubscriptionRunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._lock = RLock()

    def create(self, run: SubscriptionRun) -> tuple[SubscriptionRun, bool]:
        with self._lock, self.database.connection:
            existing = self.database.connection.execute(
                "SELECT * FROM subscription_runs WHERE run_key=?", (run.run_key,)
            ).fetchone()
            if existing is not None:
                return self._run_from_row(existing), False
            self.database.connection.execute(
                """INSERT INTO subscription_runs(
                       id,subscription_id,run_key,trigger,scheduled_for_at,period_key,
                       started_at,heartbeat_at,finished_at,status,attempt_count,
                       lease_owner,lease_expires_at,raw_count,dedup_count,
                       duplicates_removed,historical_duplicates_removed,new_count,
                       eligible_count,recommended_count,provider_status_json,safe_error
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                self._run_values(run),
            )
        return run.model_copy(deep=True), True

    def finish(self, run: SubscriptionRun) -> SubscriptionRun:
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE subscription_runs SET
                       heartbeat_at=?,finished_at=?,status=?,attempt_count=?,lease_owner=?,
                       lease_expires_at=?,raw_count=?,dedup_count=?,duplicates_removed=?,
                       historical_duplicates_removed=?,new_count=?,eligible_count=?,
                       recommended_count=?,provider_status_json=?,safe_error=?
                   WHERE id=?""",
                (
                    run.heartbeat_at.isoformat(),
                    self._datetime(run.finished_at),
                    run.status.value,
                    run.attempt_count,
                    run.lease_owner,
                    self._datetime(run.lease_expires_at),
                    run.raw_count,
                    run.dedup_count,
                    run.duplicates_removed,
                    run.historical_duplicates_removed,
                    run.new_count,
                    run.eligible_count,
                    run.recommended_count,
                    json.dumps(run.provider_status, ensure_ascii=False, separators=(",", ":")),
                    run.safe_error,
                    run.id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(run.id)
        return run.model_copy(deep=True)

    def get(self, run_id: str) -> SubscriptionRun | None:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT * FROM subscription_runs WHERE id=?", (run_id,)
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def list_for_subscription(self, subscription_id: str) -> list[SubscriptionRun]:
        with self._lock:
            rows = self.database.connection.execute(
                """SELECT * FROM subscription_runs WHERE subscription_id=?
                   ORDER BY started_at DESC,id DESC""",
                (subscription_id,),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def add_recommendation(self, recommendation: Recommendation) -> bool:
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """INSERT OR IGNORE INTO recommendations(
                       id,run_id,subscription_id,canonical_id,rank_position,rank_score,
                       relevance_score,quality_score,score_detail_json,recommended_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    recommendation.id,
                    recommendation.run_id,
                    recommendation.subscription_id,
                    recommendation.canonical_id,
                    recommendation.rank_position,
                    recommendation.rank_score,
                    recommendation.relevance_score,
                    recommendation.quality_score,
                    json.dumps(
                        recommendation.score_detail,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    recommendation.recommended_at.isoformat(),
                ),
            )
        return cursor.rowcount == 1

    def list_recommendations(self, run_id: str) -> list[Recommendation]:
        with self._lock:
            rows = self.database.connection.execute(
                """SELECT * FROM recommendations WHERE run_id=?
                   ORDER BY rank_position ASC,id ASC""",
                (run_id,),
            ).fetchall()
        return [self._recommendation_from_row(row) for row in rows]

    @staticmethod
    def _run_values(run: SubscriptionRun) -> tuple[object, ...]:
        return (
            run.id,
            run.subscription_id,
            run.run_key,
            run.trigger.value,
            SubscriptionRunRepository._datetime(run.scheduled_for_at),
            run.period_key,
            run.started_at.isoformat(),
            run.heartbeat_at.isoformat(),
            SubscriptionRunRepository._datetime(run.finished_at),
            run.status.value,
            run.attempt_count,
            run.lease_owner,
            SubscriptionRunRepository._datetime(run.lease_expires_at),
            run.raw_count,
            run.dedup_count,
            run.duplicates_removed,
            run.historical_duplicates_removed,
            run.new_count,
            run.eligible_count,
            run.recommended_count,
            json.dumps(run.provider_status, ensure_ascii=False, separators=(",", ":")),
            run.safe_error,
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> SubscriptionRun:
        values = dict(row)
        values["provider_status"] = json.loads(values.pop("provider_status_json"))
        return SubscriptionRun.model_validate(values)

    @staticmethod
    def _recommendation_from_row(row: sqlite3.Row) -> Recommendation:
        values = dict(row)
        values["score_detail"] = json.loads(values.pop("score_detail_json"))
        return Recommendation.model_validate(values)

    @staticmethod
    def _datetime(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
