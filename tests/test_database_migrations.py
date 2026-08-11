from __future__ import annotations

import sqlite3

import pytest

from litwatch.db import MIGRATION_REGISTRY, MIGRATIONS, SCHEMA, Database
from litwatch.migrations import (
    Migration,
    MigrationChecksumError,
    MigrationCoordinator,
    MigrationReport,
    MigrationSafetyError,
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
