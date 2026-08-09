from __future__ import annotations

import json
import sqlite3
from threading import RLock

from litwatch.db import Database
from litwatch.deliveries import Delivery, DeliveryChannel


class DeliveryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._lock = RLock()

    def create(self, delivery: Delivery) -> tuple[Delivery, bool]:
        with self._lock, self.database.connection:
            existing = self.database.connection.execute(
                "SELECT * FROM deliveries WHERE run_id=? AND channel=?",
                (delivery.run_id, delivery.channel.value),
            ).fetchone()
            if existing is not None:
                return self._from_row(existing), False
            self.database.connection.execute(
                """INSERT INTO deliveries(
                       id,run_id,subscription_id,channel,status,digest_json,
                       attempted_at,delivered_at,safe_error
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    delivery.id,
                    delivery.run_id,
                    delivery.subscription_id,
                    delivery.channel.value,
                    delivery.status.value,
                    json.dumps(delivery.digest, ensure_ascii=False, separators=(",", ":")),
                    delivery.attempted_at.isoformat(),
                    delivery.delivered_at.isoformat() if delivery.delivered_at else None,
                    delivery.safe_error,
                ),
            )
        return delivery.model_copy(deep=True), True

    def get(self, delivery_id: str) -> Delivery | None:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT * FROM deliveries WHERE id=?", (delivery_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_for_run(
        self, run_id: str, channel: DeliveryChannel = DeliveryChannel.DASHBOARD
    ) -> Delivery | None:
        with self._lock:
            row = self.database.connection.execute(
                "SELECT * FROM deliveries WHERE run_id=? AND channel=?",
                (run_id, channel.value),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list(self, subscription_id: str | None = None) -> list[Delivery]:
        query = "SELECT * FROM deliveries"
        values: tuple[object, ...] = ()
        if subscription_id is not None:
            query += " WHERE subscription_id=?"
            values = (subscription_id,)
        query += " ORDER BY attempted_at DESC,id DESC"
        with self._lock:
            rows = self.database.connection.execute(query, values).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Delivery:
        values = dict(row)
        values["digest"] = json.loads(values.pop("digest_json"))
        return Delivery.model_validate(values)
