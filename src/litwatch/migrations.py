from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from typing import Self
from uuid import uuid4

if os.name == "nt":
    import msvcrt
else:
    import fcntl


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


@dataclass(frozen=True, slots=True)
class _RecoveryConnectionState:
    busy_timeout: int
    connection_factory: type[sqlite3.Connection]
    foreign_keys: bool
    journal_mode: str
    row_factory: object
    text_factory: object
    isolation_level: str | None


class DatabaseProcessLock:
    """Cross-process shared/exclusive lock used by every LitWatch DB lifetime."""

    _WINDOWS_READER_SLOTS = 64

    def __init__(self, path: Path, *, shared: bool) -> None:
        self.path = path
        self.shared = shared
        self._handle = None
        self._offset = 0
        self._length = 0

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        if self.held:
            return
        try:
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            minimum_size = self._WINDOWS_READER_SLOTS if os.name == "nt" else 1
            if handle.tell() < minimum_size:
                handle.write(b"\0" * (minimum_size - handle.tell()))
                handle.flush()
            if os.name == "nt":
                if self.shared:
                    for offset in range(self._WINDOWS_READER_SLOTS):
                        handle.seek(offset)
                        try:
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        except OSError:
                            continue
                        self._offset = offset
                        self._length = 1
                        break
                    else:
                        raise OSError("no database reader lock slots available")
                else:
                    handle.seek(0)
                    msvcrt.locking(
                        handle.fileno(),
                        msvcrt.LK_NBLCK,
                        self._WINDOWS_READER_SLOTS,
                    )
                    self._offset = 0
                    self._length = self._WINDOWS_READER_SLOTS
            else:
                mode = fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX
                fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
        except OSError:
            if "handle" in locals():
                handle.close()
            raise MigrationSafetyError("database is not quiescent") from None
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                self._handle.seek(self._offset)
                msvcrt.locking(
                    self._handle.fileno(), msvcrt.LK_UNLCK, self._length
                )
            else:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
            self._offset = 0
            self._length = 0

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


class _RecoveryFileLock(DatabaseProcessLock):
    """Serialize recovery while preventing new LitWatch DB connections.

    SQLite's exclusive preflight separately rejects unmanaged clients that
    still hold an active transaction; an OS replacement conflict remains
    fail-closed.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path, shared=False)


def database_access_lock_path(database_path: Path) -> Path:
    return database_path.with_name(f".{database_path.name}.access.lock")


def database_recovery_lock_path(database_path: Path) -> Path:
    return database_path.with_name(f".{database_path.name}.recovery.lock")


@dataclass(slots=True)
class _RecoveryAccessLease:
    exclusive: DatabaseProcessLock
    shared: DatabaseProcessLock | None
    active: bool = True

    def restore_shared(self, connection: sqlite3.Connection) -> None:
        if not self.active:
            return
        self.exclusive.release()
        if self.shared is not None:
            self.shared.acquire()
            if hasattr(connection, "_litwatch_access_lock"):
                connection._litwatch_access_lock = self.shared
        self.active = False

    def finish(self) -> None:
        if self.active:
            self.exclusive.release()
            self.active = False


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
        lock_path = self.database_path.with_name(
            f".{self.database_path.name}.recovery.lock"
        )
        with _RecoveryFileLock(lock_path):
            try:
                source = backup_path.resolve(strict=True)
            except (OSError, RuntimeError):
                raise MigrationSafetyError("backup is unavailable") from None
            access_lease = self._acquire_recovery_access()
            return self._recover_locked(source, access_lease)

    def _recover_locked(
        self, source: Path, access_lease: _RecoveryAccessLease
    ) -> MigrationVerification:
        temporary_path = self.database_path.with_name(
            f".{self.database_path.name}.restore-{uuid4().hex}.tmp"
        )
        recovery_state = self._acquire_recovery_quiescence()
        temporary_connection: sqlite3.Connection | None = None
        connection_closed = False
        try:
            try:
                try:
                    copy2(source, temporary_path)
                except OSError:
                    raise MigrationSafetyError("backup copy failed") from None
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
            connection_closed = True
            # The temporary file shares the database parent directory, which
            # makes this a same-volume atomic replacement.
            try:
                temporary_path.replace(self.database_path)
            except OSError:
                self._reopen_database_connection(recovery_state)
                connection_closed = False
                raise MigrationSafetyError("database replacement failed") from None
        except Exception:
            restoration_failed = False
            if not connection_closed:
                try:
                    self._release_recovery_quiescence(recovery_state)
                except sqlite3.Error:
                    restoration_failed = True
                try:
                    access_lease.restore_shared(self.connection)
                except MigrationSafetyError:
                    restoration_failed = True
            else:
                access_lease.finish()
            if temporary_path.exists():
                temporary_path.unlink()
            if restoration_failed:
                raise MigrationSafetyError("database state restoration failed") from None
            raise
        access_lease.finish()
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
        except Exception:
            destination.close()
            backup_path.unlink(missing_ok=True)
            raise
        else:
            destination.close()
        return backup_path

    def _acquire_recovery_access(self) -> _RecoveryAccessLease:
        shared = getattr(self.connection, "_litwatch_access_lock", None)
        if shared is not None:
            shared.release()
        exclusive = DatabaseProcessLock(
            database_access_lock_path(self.database_path), shared=False
        )
        try:
            exclusive.acquire()
        except MigrationSafetyError:
            if shared is not None:
                shared.acquire()
            raise
        return _RecoveryAccessLease(exclusive=exclusive, shared=shared)

    def _acquire_recovery_quiescence(self) -> _RecoveryConnectionState:
        busy_timeout = int(self.connection.execute("PRAGMA busy_timeout").fetchone()[0])
        journal_mode = str(
            self.connection.execute("PRAGMA journal_mode").fetchone()[0]
        ).lower()
        state = _RecoveryConnectionState(
            busy_timeout=busy_timeout,
            connection_factory=type(self.connection),
            foreign_keys=bool(
                self.connection.execute("PRAGMA foreign_keys").fetchone()[0]
            ),
            journal_mode=journal_mode,
            row_factory=self.connection.row_factory,
            text_factory=self.connection.text_factory,
            isolation_level=self.connection.isolation_level,
        )
        self.connection.execute("PRAGMA busy_timeout=0")
        try:
            delete_mode = str(
                self.connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            ).lower()
            if delete_mode != "delete":
                raise MigrationSafetyError("database is not quiescent")
            self.connection.execute("BEGIN EXCLUSIVE")
        except (sqlite3.Error, MigrationSafetyError) as error:
            if self.connection.in_transaction:
                self.connection.rollback()
            self.connection.execute(f"PRAGMA busy_timeout={busy_timeout}")
            if journal_mode != "delete":
                try:
                    self.connection.execute(f"PRAGMA journal_mode={journal_mode}")
                except sqlite3.Error:
                    pass
            raise MigrationSafetyError("database is not quiescent") from error
        return state

    def _release_recovery_quiescence(self, state: _RecoveryConnectionState) -> None:
        if self.connection.in_transaction:
            self.connection.rollback()
        if state.journal_mode != "delete":
            self.connection.execute(f"PRAGMA journal_mode={state.journal_mode}")
        self.connection.execute(f"PRAGMA busy_timeout={state.busy_timeout}")
        self.connection.execute(f"PRAGMA foreign_keys={int(state.foreign_keys)}")

    def _reopen_database_connection(self, state: _RecoveryConnectionState) -> None:
        try:
            connection = sqlite3.connect(
                self.database_path,
                check_same_thread=False,
                factory=state.connection_factory,
                isolation_level=state.isolation_level,
            )
            connection.row_factory = state.row_factory
            connection.text_factory = state.text_factory
        except sqlite3.Error:
            raise MigrationSafetyError("database state restoration failed") from None
        self.connection = connection

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
