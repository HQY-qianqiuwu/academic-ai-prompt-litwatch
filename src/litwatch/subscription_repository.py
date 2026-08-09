from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from threading import RLock

from litwatch.db import Database
from litwatch.subscriptions import Subscription


class SubscriptionRepository:
    """SQLite storage for subscription configuration only."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._lock = RLock()

    def create(self, subscription: Subscription) -> Subscription:
        values = self._database_values(subscription)
        with self._lock, self.database.connection:
            self.database.connection.execute(
                """INSERT INTO subscriptions(
                       id,name,topic,keywords_json,providers_json,search_limit,
                       recommendation_limit,frequency,weekday,local_time,timezone,enabled,
                       created_at,updated_at,last_run_at,last_success_at,next_run_at
                   ) VALUES (
                       :id,:name,:topic,:keywords_json,:providers_json,:search_limit,
                       :recommendation_limit,:frequency,:weekday,:local_time,:timezone,:enabled,
                       :created_at,:updated_at,:last_run_at,:last_success_at,:next_run_at
                   )""",
                values,
            )
        return subscription.model_copy(deep=True)

    def list(self) -> list[Subscription]:
        with self._lock:
            rows = self.database.connection.execute(
                "SELECT * FROM subscriptions ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, subscription_id: str) -> Subscription | None:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT * FROM subscriptions WHERE id=?", (subscription_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def exists(self, subscription_id: str) -> bool:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT 1 FROM subscriptions WHERE id=?", (subscription_id,)
            ).fetchone()
        return row is not None

    def update(self, subscription: Subscription) -> Subscription:
        values = self._database_values(subscription)
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE subscriptions SET
                       name=:name, topic=:topic, keywords_json=:keywords_json,
                       providers_json=:providers_json, search_limit=:search_limit,
                       recommendation_limit=:recommendation_limit, frequency=:frequency,
                       weekday=:weekday, local_time=:local_time, timezone=:timezone,
                       enabled=:enabled, updated_at=:updated_at, last_run_at=:last_run_at,
                       last_success_at=:last_success_at, next_run_at=:next_run_at
                   WHERE id=:id""",
                values,
            )
        if cursor.rowcount != 1:
            raise KeyError(subscription.id)
        return subscription.model_copy(deep=True)

    def record_execution(
        self,
        subscription_id: str,
        *,
        run_at: datetime,
        successful: bool,
    ) -> None:
        with self._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """UPDATE subscriptions SET
                       last_run_at=?,
                       last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END
                   WHERE id=?""",
                (
                    run_at.isoformat(),
                    int(successful),
                    run_at.isoformat(),
                    subscription_id,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(subscription_id)

    @staticmethod
    def _database_values(subscription: Subscription) -> Mapping[str, object]:
        return {
            "id": subscription.id,
            "name": subscription.name,
            "topic": subscription.topic,
            "keywords_json": json.dumps(
                subscription.keywords, ensure_ascii=False, separators=(",", ":")
            ),
            "providers_json": json.dumps(
                subscription.providers, ensure_ascii=False, separators=(",", ":")
            ),
            "search_limit": subscription.search_limit,
            "recommendation_limit": subscription.recommendation_limit,
            "frequency": subscription.frequency.value,
            "weekday": subscription.weekday,
            "local_time": subscription.local_time,
            "timezone": subscription.timezone,
            "enabled": int(subscription.enabled),
            "created_at": subscription.created_at.isoformat(),
            "updated_at": subscription.updated_at.isoformat(),
            "last_run_at": SubscriptionRepository._serialize_datetime(
                subscription.last_run_at
            ),
            "last_success_at": SubscriptionRepository._serialize_datetime(
                subscription.last_success_at
            ),
            "next_run_at": SubscriptionRepository._serialize_datetime(
                subscription.next_run_at
            ),
        }

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Subscription:
        return Subscription.model_validate(
            {
                "id": row["id"],
                "name": row["name"],
                "topic": row["topic"],
                "keywords": json.loads(row["keywords_json"]),
                "providers": json.loads(row["providers_json"]),
                "search_limit": row["search_limit"],
                "recommendation_limit": row["recommendation_limit"],
                "frequency": row["frequency"],
                "weekday": row["weekday"],
                "local_time": row["local_time"],
                "timezone": row["timezone"],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_run_at": row["last_run_at"],
                "last_success_at": row["last_success_at"],
                "next_run_at": row["next_run_at"],
            }
        )
