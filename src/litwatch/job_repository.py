from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from litwatch.db import Database
from litwatch.jobs import JobPayload, JobRecord


class JobTransitionError(RuntimeError):
    """Raised when a guarded job state transition no longer applies."""


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def enqueue(
        self,
        *,
        job_type: str,
        idempotency_key: str,
        input_hash: str,
        payload: dict[str, object],
        max_attempts: int,
        timeout_seconds: int,
        now: datetime | None = None,
    ) -> JobRecord:
        job_type = self._required(job_type, "job_type")
        idempotency_key = self._required(idempotency_key, "idempotency_key")
        input_hash = self._required(input_hash, "input_hash")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        normalized_payload = JobPayload.model_validate(payload).root
        created_at = self._utc(now)
        job_id = uuid4().hex
        payload_json = json.dumps(
            normalized_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO jobs(
                       job_id,job_type,idempotency_key,status,created_at,attempt,
                       max_attempts,timeout_seconds,input_hash,payload_json
                   ) VALUES (?,?,?,'queued',?,0,?,?,?,?)""",
                (
                    job_id,
                    job_type,
                    idempotency_key,
                    created_at.isoformat(),
                    max_attempts,
                    timeout_seconds,
                    input_hash,
                    payload_json,
                ),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_type=? AND idempotency_key=?",
                (job_type, idempotency_key),
            ).fetchone()
        if row is None:  # pragma: no cover - SQLite must return the inserted row
            raise RuntimeError("job enqueue did not persist a row")
        return self._from_row(row)

    def get(self, job_id: str) -> JobRecord | None:
        with self.database.transaction_lock:
            row = self.database.connection.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def claim_next(
        self,
        lease_owner: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> JobRecord | None:
        lease_owner = self._required(lease_owner, "lease_owner")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        claimed_at = self._utc(now)
        lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                """UPDATE jobs SET
                       status='running',
                       started_at=COALESCE(started_at, ?),
                       heartbeat_at=?, attempt=attempt+1,
                       lease_owner=?, lease_expires_at=?
                   WHERE job_id=(
                       SELECT job_id FROM jobs
                       WHERE status='queued'
                         AND cancellation_requested_at IS NULL
                         AND attempt < max_attempts
                       ORDER BY created_at ASC,job_id ASC
                       LIMIT 1
                   )
                   RETURNING *""",
                (
                    claimed_at.isoformat(),
                    claimed_at.isoformat(),
                    lease_owner,
                    lease_expires_at.isoformat(),
                ),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def heartbeat(
        self,
        job_id: str,
        lease_owner: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> JobRecord:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        heartbeat_at = self._utc(now)
        lease_expires_at = heartbeat_at + timedelta(seconds=lease_seconds)
        return self._guarded_update(
            job_id,
            lease_owner,
            """UPDATE jobs SET heartbeat_at=?,lease_expires_at=?
               WHERE job_id=? AND status='running' AND lease_owner=?
                 AND lease_expires_at > ?
               RETURNING *""",
            (
                heartbeat_at.isoformat(),
                lease_expires_at.isoformat(),
                job_id,
                lease_owner,
                heartbeat_at.isoformat(),
            ),
        )

    def complete(
        self,
        job_id: str,
        lease_owner: str,
        *,
        result_reference: str | None,
        now: datetime | None = None,
    ) -> JobRecord:
        finished_at = self._utc(now).isoformat()
        return self._guarded_update(
            job_id,
            lease_owner,
            """UPDATE jobs SET
                   status=CASE WHEN cancellation_requested_at IS NULL
                               THEN 'completed' ELSE 'cancelled' END,
                   finished_at=?,heartbeat_at=?,
                   result_reference=CASE WHEN cancellation_requested_at IS NULL
                                         THEN ? ELSE NULL END,
                   lease_owner=NULL,lease_expires_at=NULL
               WHERE job_id=? AND status='running' AND lease_owner=?
                 AND lease_expires_at > ?
               RETURNING *""",
            (
                finished_at,
                finished_at,
                result_reference,
                job_id,
                lease_owner,
                finished_at,
            ),
        )

    def fail(
        self,
        job_id: str,
        lease_owner: str,
        *,
        safe_error_code: str,
        safe_error_message: str,
        retryable: bool = False,
        now: datetime | None = None,
    ) -> JobRecord:
        failed_at = self._utc(now).isoformat()
        retry = int(retryable)
        return self._guarded_update(
            job_id,
            lease_owner,
            """UPDATE jobs SET
                   status=CASE
                       WHEN cancellation_requested_at IS NOT NULL THEN 'cancelled'
                       WHEN ?=1 AND attempt < max_attempts THEN 'queued'
                       ELSE 'failed'
                   END,
                   finished_at=CASE
                       WHEN cancellation_requested_at IS NULL
                            AND ?=1 AND attempt < max_attempts THEN NULL
                       ELSE ?
                   END,
                   heartbeat_at=?,safe_error_code=?,safe_error_message=?,
                   lease_owner=NULL,lease_expires_at=NULL
               WHERE job_id=? AND status='running' AND lease_owner=?
                 AND lease_expires_at > ?
               RETURNING *""",
            (
                retry,
                retry,
                failed_at,
                failed_at,
                safe_error_code,
                safe_error_message,
                job_id,
                lease_owner,
                failed_at,
            ),
        )

    def request_cancel(
        self, job_id: str, *, now: datetime | None = None
    ) -> JobRecord:
        requested_at = self._utc(now).isoformat()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                """UPDATE jobs SET
                       cancellation_requested_at=CASE
                           WHEN status IN ('queued','running')
                           THEN COALESCE(cancellation_requested_at, ?)
                           ELSE cancellation_requested_at
                       END,
                       status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
                       finished_at=CASE WHEN status='queued' THEN ? ELSE finished_at END,
                       lease_owner=CASE WHEN status='queued' THEN NULL ELSE lease_owner END,
                       lease_expires_at=CASE WHEN status='queued' THEN NULL ELSE lease_expires_at END
                   WHERE job_id=?
                   RETURNING *""",
                (requested_at, requested_at, job_id),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._from_row(row)

    def recover_stale(
        self,
        now: datetime | None = None,
        *,
        exclude_job_ids: tuple[str, ...] = (),
    ) -> list[JobRecord]:
        recovered_at = self._utc(now).isoformat()
        excluded = tuple(sorted({job_id for job_id in exclude_job_ids if job_id}))
        exclusion_sql = ""
        values: list[object] = [recovered_at, recovered_at, recovered_at, recovered_at]
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            exclusion_sql = f" AND job_id NOT IN ({placeholders})"
            values.extend(excluded)
        with self.database.transaction(immediate=True) as connection:
            rows = connection.execute(
                f"""UPDATE jobs SET
                       status=CASE
                           WHEN cancellation_requested_at IS NOT NULL THEN 'cancelled'
                           WHEN attempt < max_attempts THEN 'queued'
                           ELSE 'failed'
                       END,
                       finished_at=CASE
                           WHEN cancellation_requested_at IS NOT NULL THEN ?
                           WHEN attempt < max_attempts THEN NULL
                           ELSE ?
                       END,
                       heartbeat_at=?,
                       safe_error_code=CASE WHEN attempt < max_attempts
                                            THEN safe_error_code
                                            ELSE 'restart_recovery_exhausted' END,
                       safe_error_message=CASE WHEN attempt < max_attempts
                                               THEN safe_error_message
                                               ELSE 'stale job exhausted retries' END,
                       lease_owner=NULL,lease_expires_at=NULL
                   WHERE status='running' AND lease_expires_at IS NOT NULL
                     AND lease_expires_at <= ?{exclusion_sql}
                   RETURNING *""",
                tuple(values),
            ).fetchall()
        return sorted((self._from_row(row) for row in rows), key=lambda job: job.job_id)

    def abandon_active_attempt(
        self,
        job_id: str,
        lease_owner: str,
        *,
        safe_error_code: str,
        safe_error_message: str,
        now: datetime | None = None,
    ) -> JobRecord:
        """Seal a locally active attempt that cannot drain during worker shutdown."""

        finished_at = self._utc(now).isoformat()
        return self._guarded_update(
            job_id,
            lease_owner,
            """UPDATE jobs SET
                   status='failed',finished_at=?,heartbeat_at=?,
                   safe_error_code=?,safe_error_message=?,
                   lease_owner=NULL,lease_expires_at=NULL
               WHERE job_id=? AND status='running' AND lease_owner=?
               RETURNING *""",
            (
                finished_at,
                finished_at,
                safe_error_code,
                safe_error_message,
                job_id,
                lease_owner,
            ),
        )

    def mark_active_timeout(
        self,
        job_id: str,
        lease_owner: str,
        *,
        lease_seconds: int,
        safe_error_message: str,
        now: datetime | None = None,
    ) -> JobRecord:
        """Persist timeout evidence without making an active attempt claimable."""

        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        marked_at = self._utc(now)
        lease_expires_at = marked_at + timedelta(seconds=lease_seconds)
        return self._guarded_update(
            job_id,
            lease_owner,
            """UPDATE jobs SET
                   heartbeat_at=?,lease_expires_at=?,
                   safe_error_code='timeout',safe_error_message=?
               WHERE job_id=? AND status='running' AND lease_owner=?
                 AND cancellation_requested_at IS NULL
               RETURNING *""",
            (
                marked_at.isoformat(),
                lease_expires_at.isoformat(),
                safe_error_message,
                job_id,
                lease_owner,
            ),
        )

    def _guarded_update(
        self,
        job_id: str,
        lease_owner: str,
        statement: str,
        values: tuple[object, ...],
    ) -> JobRecord:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(statement, values).fetchone()
        if row is None:
            raise JobTransitionError("job state transition rejected")
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JobRecord:
        values = dict(row)
        values["payload"] = json.loads(values.pop("payload_json"))
        return JobRecord.model_validate(values)

    @staticmethod
    def _required(value: str, name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} must not be blank")
        return normalized

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        value = value or datetime.now(UTC)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("job timestamps must be timezone-aware")
        return value.astimezone(UTC)
