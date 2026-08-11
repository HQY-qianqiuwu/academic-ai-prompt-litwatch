from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime


class MigrationSafetyError(RuntimeError):
    """Raised when migration metadata cannot be trusted."""


class MigrationChecksumError(MigrationSafetyError):
    """Raised when an applied migration differs from the immutable registry."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str

    @classmethod
    def from_sql(cls, version: int, name: str, sql: str) -> Migration:
        return cls(
            version=version,
            name=name,
            sql=sql,
            checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class MigrationState:
    current_version: int
    target_version: int
    pending: tuple[Migration, ...]


@dataclass(frozen=True, slots=True)
class MigrationVerification:
    ok: bool
    integrity: str
    foreign_key_errors: tuple[str, ...]
    current_version: int


MIGRATION_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS migration_audit (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('running', 'success', 'failed'))
);
"""


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class MigrationCoordinator:
    """Applies and verifies one immutable, ordered SQLite migration registry."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        migrations: Iterable[Migration],
    ) -> None:
        self.connection = connection
        self.migrations = tuple(migrations)
        self._by_version = {migration.version: migration for migration in self.migrations}
        if len(self._by_version) != len(self.migrations):
            raise MigrationSafetyError("duplicate migration version")
        expected = tuple(range(1, len(self.migrations) + 1))
        actual = tuple(migration.version for migration in self.migrations)
        if actual != expected:
            raise MigrationSafetyError("migration registry is not contiguous and ordered")
        for migration in self.migrations:
            expected_checksum = hashlib.sha256(migration.sql.encode("utf-8")).hexdigest()
            if migration.checksum != expected_checksum:
                raise MigrationChecksumError(
                    f"migration registry checksum mismatch at version {migration.version}"
                )

    def inspect(self) -> MigrationState:
        self._ensure_audit_table()
        applied = self._applied_rows()
        self._validate_applied(applied)
        self._backfill_legacy_audit(applied)
        self._validate_audit()
        applied_versions = {version for version, _ in applied}
        pending = tuple(
            migration
            for migration in self.migrations
            if migration.version not in applied_versions
        )
        current = max(applied_versions, default=0)
        target = self.migrations[-1].version if self.migrations else 0
        return MigrationState(current_version=current, target_version=target, pending=pending)

    def migrate(self) -> MigrationVerification:
        state = self.inspect()
        for migration in state.pending:
            self._apply(migration)
        return self.verify()

    def verify(self) -> MigrationVerification:
        state = self.inspect()
        integrity_rows = self.connection.execute("PRAGMA integrity_check").fetchall()
        integrity_values = tuple(str(row[0]) for row in integrity_rows)
        integrity = "\n".join(integrity_values)
        foreign_key_rows = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        foreign_key_errors = tuple(
            ":".join(str(value) for value in row) for row in foreign_key_rows
        )
        return MigrationVerification(
            ok=(
                integrity_values == ("ok",)
                and not foreign_key_errors
                and not state.pending
            ),
            integrity=integrity,
            foreign_key_errors=foreign_key_errors,
            current_version=state.current_version,
        )

    def _ensure_audit_table(self) -> None:
        self.connection.executescript(MIGRATION_AUDIT_SCHEMA)

    def _applied_rows(self) -> tuple[tuple[int, str], ...]:
        rows = self.connection.execute(
            "SELECT version,name FROM schema_migrations ORDER BY version"
        ).fetchall()
        return tuple((int(row[0]), str(row[1])) for row in rows)

    def _validate_applied(self, applied: tuple[tuple[int, str], ...]) -> None:
        applied_versions = tuple(version for version, _ in applied)
        if applied_versions != tuple(range(1, len(applied_versions) + 1)):
            raise MigrationSafetyError("applied migration history is not contiguous")
        for version, name in applied:
            migration = self._by_version.get(version)
            if migration is None:
                raise MigrationSafetyError(f"unknown applied migration version {version}")
            if migration.name != name:
                raise MigrationChecksumError(f"migration name mismatch at version {version}")

    def _backfill_legacy_audit(self, applied: tuple[tuple[int, str], ...]) -> None:
        now = datetime.now(UTC).isoformat()
        for version, _ in applied:
            migration = self._by_version[version]
            self.connection.execute(
                """INSERT OR IGNORE INTO migration_audit(
                       version,name,checksum,started_at,finished_at,status
                   ) VALUES (?,?,?,?,?,'success')""",
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    now,
                    now,
                ),
            )
        self.connection.commit()

    def _validate_audit(self) -> None:
        rows = self.connection.execute(
            "SELECT version,name,checksum,status FROM migration_audit ORDER BY version"
        ).fetchall()
        for row in rows:
            version = int(row[0])
            migration = self._by_version.get(version)
            if migration is None:
                raise MigrationSafetyError(f"unknown migration audit version {version}")
            if str(row[1]) != migration.name or str(row[2]) != migration.checksum:
                raise MigrationChecksumError(f"migration checksum mismatch at version {version}")
            if str(row[3]) != "success":
                raise MigrationSafetyError(f"migration version {version} is not successful")

    def _apply(self, migration: Migration) -> None:
        now = datetime.now(UTC).isoformat()
        version = migration.version
        name = _sql_literal(migration.name)
        checksum = _sql_literal(migration.checksum)
        timestamp = _sql_literal(now)
        try:
            self.connection.executescript(
                f"""BEGIN IMMEDIATE;
                {migration.sql}
                INSERT INTO schema_migrations(version,name)
                VALUES ({version},{name});
                INSERT INTO migration_audit(
                    version,name,checksum,started_at,finished_at,status
                ) VALUES (
                    {version},{name},{checksum},{timestamp},{timestamp},'success'
                );
                COMMIT;"""
            )
        except sqlite3.Error:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
