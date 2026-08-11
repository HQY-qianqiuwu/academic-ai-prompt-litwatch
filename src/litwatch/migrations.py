from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from uuid import uuid4


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


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """The durable outcome of one migration attempt."""

    backup_path: Path | None
    applied_versions: tuple[int, ...]
    verification: MigrationVerification


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
        *,
        backup_directory: Path | None = None,
    ) -> None:
        self.connection = connection
        self.migrations = tuple(migrations)
        self.database_path = self._database_path()
        self.backup_directory = backup_directory or self.database_path.parent / "backups"
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
        if self.connection.in_transaction:
            raise MigrationSafetyError(
                "cannot inspect migrations during an active transaction"
            )
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

    def migrate(self) -> MigrationReport:
        state = self.inspect()
        if not state.pending:
            return MigrationReport(
                backup_path=None,
                applied_versions=(),
                verification=self.verify(),
            )

        backup_path = self._backup_database(state)
        applied_versions: list[int] = []
        for migration in state.pending:
            self._apply(migration)
            applied_versions.append(migration.version)
        return MigrationReport(
            backup_path=backup_path,
            applied_versions=tuple(applied_versions),
            verification=self.verify(),
        )

    def recover(self, backup_path: Path) -> MigrationVerification:
        """Restore a verified backup by replacing the database from a sibling temp file.

        The caller must discard this coordinator after recovery: the connection is
        closed immediately before replacement so Windows can safely replace the
        database file.
        """

        if self.connection.in_transaction:
            raise MigrationSafetyError(
                "cannot recover migrations during an active transaction"
            )
        source = backup_path.resolve(strict=True)
        temporary_path = self.database_path.with_name(
            f".{self.database_path.name}.restore-{uuid4().hex}.tmp"
        )
        temporary_connection: sqlite3.Connection | None = None
        try:
            try:
                copy2(source, temporary_path)
                temporary_connection = sqlite3.connect(temporary_path)
                temporary_connection.execute("PRAGMA foreign_keys=ON")
                source_state = MigrationCoordinator(
                    temporary_connection,
                    self.migrations,
                    backup_directory=self.backup_directory,
                ).inspect()
                verification = MigrationCoordinator(
                    temporary_connection,
                    self.migrations[: source_state.current_version],
                    backup_directory=self.backup_directory,
                ).verify()
                if not verification.ok:
                    raise MigrationSafetyError("backup verification failed")
            except sqlite3.Error as error:
                raise MigrationSafetyError("backup verification failed") from error
            finally:
                if temporary_connection is not None:
                    temporary_connection.close()

            self.connection.close()
            # The temporary file shares the database parent directory, which
            # makes this a same-volume atomic replacement.
            temporary_path.replace(self.database_path)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        return verification

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
        self.connection.execute(MIGRATION_AUDIT_SCHEMA)
        if self.connection.in_transaction:
            self.connection.commit()

    def _database_path(self) -> Path:
        rows = self.connection.execute("PRAGMA database_list").fetchall()
        for row in rows:
            if str(row[1]) == "main" and str(row[2]):
                return Path(str(row[2])).resolve()
        raise MigrationSafetyError("migration backup requires a file-backed database")

    def _backup_database(self, state: MigrationState) -> Path:
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.backup_directory / (
            f"{self.database_path.stem}.v{state.current_version}-"
            f"to-v{state.target_version}.{timestamp}.db"
        )
        destination = sqlite3.connect(backup_path)
        try:
            self.connection.backup(destination)
        finally:
            destination.close()
        return backup_path

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
        audited_versions = {
            int(row[0])
            for row in self.connection.execute(
                "SELECT version FROM migration_audit"
            ).fetchall()
        }
        missing = tuple(
            version for version, _ in applied if version not in audited_versions
        )
        if not missing:
            return
        now = datetime.now(UTC).isoformat()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            for version in missing:
                migration = self._by_version[version]
                self.connection.execute(
                    """INSERT INTO migration_audit(
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
        except sqlite3.Error:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise

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
