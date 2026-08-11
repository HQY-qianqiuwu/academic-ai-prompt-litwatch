from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from litwatch.db import MIGRATION_REGISTRY, MIGRATIONS, SCHEMA, Database
from litwatch.migrations import (
    DatabaseProcessLock,
    Migration,
    MigrationChecksumError,
    MigrationCoordinator,
    MigrationReport,
    MigrationSafetyError,
    database_access_lock_path,
)


def _create_v1_7_database(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    for version, name, sql in MIGRATIONS:
        connection.executescript(sql)
        connection.execute(
            "INSERT INTO schema_migrations(version,name) VALUES (?,?)",
            (version, name),
        )
    connection.commit()
    connection.close()


def test_fresh_database_applies_immutable_registry_and_records_audit(tmp_path):
    database = Database(tmp_path / "fresh.db")

    coordinator = MigrationCoordinator(database.connection, MIGRATION_REGISTRY)
    state = coordinator.inspect()
    verification = coordinator.verify()
    audit = database.connection.execute(
        """SELECT version,name,checksum,status,started_at,finished_at
           FROM migration_audit ORDER BY version"""
    ).fetchall()

    assert state.current_version == 6
    assert state.target_version == 6
    assert state.pending == ()
    assert verification.ok is True
    assert verification.integrity == "ok"
    assert verification.foreign_key_errors == ()
    assert verification.current_version == 6
    assert [(row["version"], row["name"]) for row in audit] == [
        (migration.version, migration.name) for migration in MIGRATION_REGISTRY
    ]
    assert all(row["checksum"] for row in audit)
    assert all(row["status"] == "success" for row in audit)
    assert all(row["started_at"] and row["finished_at"] for row in audit)
    database.connection.close()


def test_copied_v1_7_version_six_database_is_backfilled_without_reapplying(tmp_path):
    path = tmp_path / "v1_7.db"
    _create_v1_7_database(path)

    database = Database(path)
    coordinator = MigrationCoordinator(database.connection, MIGRATION_REGISTRY)

    assert coordinator.inspect().pending == ()
    assert database.connection.execute(
        "SELECT COUNT(*) FROM schema_migrations"
    ).fetchone()[0] == 6
    assert database.connection.execute(
        "SELECT COUNT(*) FROM migration_audit WHERE status='success'"
    ).fetchone()[0] == 6
    database.connection.close()


def test_database_connection_releases_shared_access_lock_on_close(tmp_path):
    path = tmp_path / "lifetime-lock.db"
    database = Database(path)
    exclusive = DatabaseProcessLock(
        database_access_lock_path(path.resolve()), shared=False
    )

    with pytest.raises(MigrationSafetyError, match="database is not quiescent"):
        exclusive.acquire()

    database.connection.close()
    exclusive.acquire()
    exclusive.release()


def test_applied_migration_checksum_mismatch_fails_closed(tmp_path):
    path = tmp_path / "checksum.db"
    database = Database(path)
    database.connection.execute(
        "UPDATE migration_audit SET checksum='tampered' WHERE version=1"
    )
    database.connection.commit()
    database.connection.close()

    with pytest.raises(MigrationChecksumError, match="version 1"):
        Database(path)


def test_verify_reports_integrity_and_foreign_key_errors(tmp_path):
    database = Database(tmp_path / "foreign-key.db")
    database.connection.execute("PRAGMA foreign_keys=OFF")
    database.connection.execute(
        """INSERT INTO subscription_papers(
               subscription_id,canonical_id,first_seen_at,last_seen_at
           ) VALUES ('missing-subscription','missing-paper','now','now')"""
    )
    database.connection.commit()
    database.connection.execute("PRAGMA foreign_keys=ON")

    verification = MigrationCoordinator(
        database.connection, MIGRATION_REGISTRY
    ).verify()

    assert verification.ok is False
    assert verification.integrity == "ok"
    assert verification.foreign_key_errors
    assert verification.current_version == 6
    database.connection.close()


@pytest.mark.parametrize("operation", ["inspect", "verify"])
def test_read_operation_rejects_active_transaction_without_committing_it(
    tmp_path, operation
):
    path = tmp_path / f"active-{operation}.db"
    database = Database(path)
    database.connection.execute("INSERT INTO runs(started_at) VALUES ('uncommitted')")
    coordinator = MigrationCoordinator(database.connection, MIGRATION_REGISTRY)

    with pytest.raises(MigrationSafetyError, match="active transaction"):
        getattr(coordinator, operation)()

    assert database.connection.in_transaction is True
    database.connection.rollback()
    database.connection.close()

    reopened = sqlite3.connect(path)
    assert reopened.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='uncommitted'"
    ).fetchone()[0] == 0
    reopened.close()


def test_invalid_migration_rolls_back_schema_version_and_audit(tmp_path):
    database = Database(tmp_path / "invalid-migration.db")
    invalid = Migration.from_sql(
        7,
        "intentionally_invalid",
        "CREATE TABLE partial_table(id INTEGER); THIS IS NOT VALID SQL;",
    )

    with pytest.raises(sqlite3.Error):
        MigrationCoordinator(
            database.connection, (*MIGRATION_REGISTRY, invalid)
        ).migrate()

    assert database.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='partial_table'"
    ).fetchone()[0] == 0
    assert database.connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=7"
    ).fetchone()[0] == 0
    assert database.connection.execute(
        "SELECT COUNT(*) FROM migration_audit WHERE version=7"
    ).fetchone()[0] == 0
    database.connection.close()


def test_pending_migration_creates_sqlite_backup_and_reports_it(tmp_path):
    database = Database(tmp_path / "pending.db")
    migration = Migration.from_sql(
        7,
        "backup_probe",
        "CREATE TABLE backup_probe(id INTEGER PRIMARY KEY);",
    )
    backup_directory = tmp_path / "backups"

    report = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, migration),
        backup_directory=backup_directory,
    ).migrate()

    assert isinstance(report, MigrationReport)
    assert report.applied_versions == (7,)
    assert report.backup_path is not None
    assert report.backup_path.parent == backup_directory
    assert report.backup_path.is_file()
    assert report.verification.ok is True
    database.connection.close()


def test_failed_sqlite_backup_removes_partial_destination_artifact(tmp_path):
    class FailingBackupConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def backup(self, destination):
            destination.execute("CREATE TABLE incomplete_backup(id INTEGER)")
            destination.commit()
            raise sqlite3.OperationalError("injected backup failure")

    database = Database(tmp_path / "backup-failure.db")
    migration = Migration.from_sql(
        7,
        "backup_failure_probe",
        "CREATE TABLE backup_failure_probe(id INTEGER PRIMARY KEY);",
    )
    backup_directory = tmp_path / "failed-backups"

    with pytest.raises(sqlite3.OperationalError, match="injected backup failure"):
        MigrationCoordinator(
            FailingBackupConnection(database.connection),
            (*MIGRATION_REGISTRY, migration),
            backup_directory=backup_directory,
        ).migrate()

    assert list(backup_directory.glob("*.db")) == []
    assert database.connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=7"
    ).fetchone()[0] == 0
    database.connection.close()


def test_invalid_pending_migration_keeps_existing_data_and_version_unchanged(tmp_path):
    database = Database(tmp_path / "invalid-backup.db")
    database.connection.execute("INSERT INTO runs(started_at) VALUES ('before-failure')")
    database.connection.commit()
    invalid = Migration.from_sql(
        7,
        "invalid_after_backup",
        "CREATE TABLE should_not_exist(id INTEGER); THIS IS NOT VALID SQL;",
    )

    with pytest.raises(sqlite3.Error):
        MigrationCoordinator(
            database.connection,
            (*MIGRATION_REGISTRY, invalid),
            backup_directory=tmp_path / "backups",
        ).migrate()

    assert database.connection.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='before-failure'"
    ).fetchone()[0] == 1
    assert database.connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=7"
    ).fetchone()[0] == 0
    assert database.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='should_not_exist'"
    ).fetchone()[0] == 0
    database.connection.close()


def test_recovery_verifies_temporary_copy_before_same_volume_replacement(tmp_path):
    path = tmp_path / "recover.db"
    database = Database(path)
    database.connection.execute("INSERT INTO runs(started_at) VALUES ('before-backup')")
    database.connection.commit()
    migration = Migration.from_sql(
        7,
        "recovery_probe",
        "CREATE TABLE recovery_probe(id INTEGER PRIMARY KEY);",
    )
    coordinator = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, migration),
        backup_directory=tmp_path / "backups",
    )
    report = coordinator.migrate()
    assert report.backup_path is not None

    database.connection.execute("INSERT INTO runs(started_at) VALUES ('after-backup')")
    database.connection.commit()

    verification = coordinator.recover(report.backup_path)

    assert verification.ok is True
    restored = sqlite3.connect(path)
    assert restored.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='before-backup'"
    ).fetchone()[0] == 1
    assert restored.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='after-backup'"
    ).fetchone()[0] == 0
    assert restored.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=7"
    ).fetchone()[0] == 0
    restored.close()


def test_recovery_rejects_unverified_backup_without_replacing_database(tmp_path):
    path = tmp_path / "reject-invalid-backup.db"
    database = Database(path)
    database.connection.execute("INSERT INTO runs(started_at) VALUES ('keep-me')")
    database.connection.commit()
    invalid_backup = tmp_path / "invalid-backup.db"
    invalid_backup.write_text("not a sqlite database", encoding="utf-8")
    coordinator = MigrationCoordinator(database.connection, MIGRATION_REGISTRY)

    with pytest.raises(MigrationSafetyError, match="backup verification failed"):
        coordinator.recover(invalid_backup)

    assert database.connection.execute(
        "SELECT COUNT(*) FROM runs WHERE started_at='keep-me'"
    ).fetchone()[0] == 1
    assert list(tmp_path.glob(".reject-invalid-backup.db.restore-*.tmp")) == []
    database.connection.close()


def test_recovery_fails_safely_when_another_connection_holds_write_lock(tmp_path):
    path = tmp_path / "concurrent-recovery.db"
    database = Database(path)
    migration = Migration.from_sql(
        7,
        "concurrent_recovery_probe",
        "CREATE TABLE concurrent_recovery_probe(id INTEGER PRIMARY KEY);",
    )
    coordinator = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, migration),
        backup_directory=tmp_path / "backups",
    )
    report = coordinator.migrate()
    assert report.backup_path is not None

    concurrent = sqlite3.connect(path)
    concurrent.execute("PRAGMA journal_mode=WAL")
    concurrent.execute("BEGIN IMMEDIATE")
    concurrent.execute("INSERT INTO runs(started_at) VALUES ('concurrent-writer')")

    with pytest.raises(MigrationSafetyError, match="database is not quiescent"):
        coordinator.recover(report.backup_path)

    concurrent.rollback()
    concurrent.close()
    database.connection.close()
    reopened = sqlite3.connect(path)
    assert reopened.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=7"
    ).fetchone()[0] == 1
    assert reopened.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='concurrent_recovery_probe'"
    ).fetchone()[0] == 1
    reopened.close()


def test_recovery_requires_other_litwatch_database_connections_to_be_closed(
    tmp_path, monkeypatch
):
    path = tmp_path / "litwatch-process-quiescence.db"
    database = Database(path)
    other_process_connection = Database(path)
    migration = Migration.from_sql(
        7,
        "litwatch_process_quiescence_probe",
        "CREATE TABLE litwatch_process_quiescence_probe(id INTEGER PRIMARY KEY);",
    )
    coordinator = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, migration),
        backup_directory=tmp_path / "backups",
    )
    report = coordinator.migrate()
    assert report.backup_path is not None

    def sqlite_preflight_must_not_run():
        raise AssertionError("shared lifetime lock must reject recovery first")

    monkeypatch.setattr(
        coordinator, "_acquire_recovery_quiescence", sqlite_preflight_must_not_run
    )

    with pytest.raises(MigrationSafetyError, match="database is not quiescent"):
        coordinator.recover(report.backup_path)

    other_process_connection.connection.close()
    assert coordinator.connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=7"
    ).fetchone()[0] == 1
    database.connection.close()


def test_recovery_holds_cross_process_lock_through_path_replacement(
    tmp_path, monkeypatch
):
    path = tmp_path / "locked-through-replace.db"
    database = Database(path)
    migration = Migration.from_sql(
        7,
        "cross_process_lock_probe",
        "CREATE TABLE cross_process_lock_probe(id INTEGER PRIMARY KEY);",
    )
    coordinator = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, migration),
        backup_directory=tmp_path / "backups",
    )
    report = coordinator.migrate()
    assert report.backup_path is not None
    real_replace = Path.replace
    observed_locked = False

    def assert_lock_is_held_then_replace(source, target):
        nonlocal observed_locked
        lock_path = path.with_name(f".{path.name}.recovery.lock")
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os, sys\n"
                    "from pathlib import Path\n"
                    "handle = Path(sys.argv[1]).open('a+b')\n"
                    "handle.seek(0)\n"
                    "try:\n"
                    "    if os.name == 'nt':\n"
                    "        import msvcrt\n"
                    "        msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)\n"
                    "    else:\n"
                    "        import fcntl\n"
                    "        fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)\n"
                    "except OSError:\n"
                    "    raise SystemExit(3)\n"
                    "raise SystemExit(0)\n"
                ),
                str(lock_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        observed_locked = probe.returncode == 3
        assert observed_locked, (probe.returncode, probe.stdout, probe.stderr)
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", assert_lock_is_held_then_replace)

    verification = coordinator.recover(report.backup_path)

    assert verification.ok is True
    assert observed_locked is True


def test_replacement_failure_restores_journal_mode_and_busy_timeout(
    tmp_path, monkeypatch
):
    path = tmp_path / "failed-replace.db"
    database = Database(path)
    migration = Migration.from_sql(
        7,
        "failed_replace_probe",
        "CREATE TABLE failed_replace_probe(id INTEGER PRIMARY KEY);",
    )
    coordinator = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, migration),
        backup_directory=tmp_path / "backups",
    )
    report = coordinator.migrate()
    assert report.backup_path is not None
    coordinator.connection.execute("PRAGMA busy_timeout=4321")
    original_journal_mode = coordinator.connection.execute(
        "PRAGMA journal_mode"
    ).fetchone()[0]

    def fail_replace(source, target):
        raise PermissionError("sensitive-path-that-must-not-leak")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(MigrationSafetyError, match="database replacement failed") as exc:
        coordinator.recover(report.backup_path)

    assert "sensitive-path-that-must-not-leak" not in str(exc.value)
    assert coordinator.connection.execute("PRAGMA journal_mode").fetchone()[0] == (
        original_journal_mode
    )
    assert coordinator.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 4321
    coordinator.connection.close()


def test_missing_recovery_backup_is_reported_without_path_leak(tmp_path):
    database = Database(tmp_path / "missing-source.db")
    coordinator = MigrationCoordinator(database.connection, MIGRATION_REGISTRY)
    missing = tmp_path / "sensitive-missing-backup.db"

    with pytest.raises(MigrationSafetyError, match="backup is unavailable") as exc:
        coordinator.recover(missing)

    assert "sensitive-missing-backup.db" not in str(exc.value)
    database.connection.close()


def test_recovery_copy_failure_is_reported_without_path_leak(tmp_path, monkeypatch):
    path = tmp_path / "copy-failure.db"
    database = Database(path)
    migration = Migration.from_sql(
        7,
        "copy_failure_probe",
        "CREATE TABLE copy_failure_probe(id INTEGER PRIMARY KEY);",
    )
    coordinator = MigrationCoordinator(
        database.connection,
        (*MIGRATION_REGISTRY, migration),
        backup_directory=tmp_path / "backups",
    )
    report = coordinator.migrate()
    assert report.backup_path is not None

    def fail_copy(source, target):
        raise PermissionError("sensitive-copy-path-that-must-not-leak")

    monkeypatch.setattr("litwatch.migrations.copy2", fail_copy)

    with pytest.raises(MigrationSafetyError, match="backup copy failed") as exc:
        coordinator.recover(report.backup_path)

    assert "sensitive-copy-path-that-must-not-leak" not in str(exc.value)
    database.connection.close()


def test_no_pending_migration_does_not_create_backup(tmp_path):
    database = Database(tmp_path / "current.db")
    backup_directory = tmp_path / "explicit-backups"

    report = MigrationCoordinator(
        database.connection,
        MIGRATION_REGISTRY,
        backup_directory=backup_directory,
    ).migrate()

    assert report.backup_path is None
    assert report.applied_versions == ()
    assert backup_directory.exists() is False
    database.connection.close()
