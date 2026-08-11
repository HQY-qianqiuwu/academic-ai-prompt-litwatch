# V2.0B Database Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every schema-changing startup backed up, transactional, verified, and recoverable.

**Architecture:** A `MigrationCoordinator` wraps the existing ordered migration registry. Database construction delegates migration safety to the coordinator before repositories are created.

**Tech Stack:** Python 3.11, sqlite3 backup API, SHA-256, pytest temporary databases.

## Global Constraints

- Never rehearse destructive recovery against `data/litwatch.db`.
- Migration failure is fail-closed.
- Existing v1.7 data and migration versions 1-6 must remain readable.
- No migration may commit partially.

---

### Task 1: Versioned migration registry and verification

**Files:**
- Create: `src/litwatch/migrations.py`
- Modify: `src/litwatch/db.py`
- Test: `tests/test_database_migrations.py`

**Interfaces:**
- `Migration(version: int, name: str, sql: str, checksum: str)`.
- `MigrationState(current_version: int, target_version: int, pending: tuple[Migration, ...])`.
- `MigrationVerification(ok: bool, integrity: str, foreign_key_errors: tuple[str, ...], current_version: int)`.
- `MigrationCoordinator.inspect()`, `.migrate()`, `.verify()`.

- [ ] **Step 1: Write failing tests for a fresh database, a copied v1.7 schema at version 6, checksum mismatch, and `PRAGMA integrity_check`/`foreign_key_check`.**
- [ ] **Step 2: Run `python -m pytest tests/test_database_migrations.py -q`; verify failure is caused by the absent coordinator.**
- [ ] **Step 3: Move the authoritative migration definitions behind immutable `Migration` objects, preserve SQL and versions 1-6, and add an audit table containing version/name/checksum/start/finish/status.**
- [ ] **Step 4: Run the targeted tests and `tests/test_subscriptions.py tests/test_radars.py`; verify PASS.**
- [ ] **Step 5: Commit explicit files with `feat(database): add verified migration registry`.**

### Task 2: Backup, transactional failure, and recovery

**Files:**
- Modify: `src/litwatch/migrations.py`
- Modify: `src/litwatch/config.py`
- Test: `tests/test_database_migrations.py`

**Interfaces:**
- `MigrationReport(backup_path: Path | None, applied_versions: tuple[int, ...], verification: MigrationVerification)`.
- `MigrationCoordinator.migrate() -> MigrationReport`.
- `MigrationCoordinator.recover(backup_path: Path) -> MigrationVerification`.
- `Settings.database_backup_path: Path = Path("data/backups")`.

- [ ] **Step 1: Add failing tests asserting pending migration creates a backup, injected invalid SQL leaves version/data unchanged, recovery verifies a temporary copy before replacement, and no pending migration creates no backup.**
- [ ] **Step 2: Run the targeted test and observe the expected missing backup/recovery failures.**
- [ ] **Step 3: Implement SQLite backup, per-migration `BEGIN IMMEDIATE`, rollback, verified temporary restore, and same-volume `Path.replace`.**
- [ ] **Step 4: Run `python -m pytest tests/test_database_migrations.py tests/test_historical_papers.py tests/test_radar_backfill.py -q`; verify PASS.**
- [ ] **Step 5: Commit with `feat(database): add migration backup and recovery`.**

### Task 3: Fail-closed startup integration

**Files:**
- Modify: `src/litwatch/db.py`
- Modify: `src/litwatch/runtime.py`
- Modify: `src/litwatch/web.py`
- Test: `tests/test_runtime.py`
- Test: `tests/test_database_migrations.py`

- [ ] **Step 1: Add a failing application test whose injected migration verification fails and assert scheduler/services never start.**
- [ ] **Step 2: Verify RED with `python -m pytest tests/test_runtime.py -q`.**
- [ ] **Step 3: Run migration and verification before service startup; raise `MigrationSafetyError` with only safe paths/codes.**
- [ ] **Step 4: Run migration/runtime tests plus the full suite; verify PASS.**
- [ ] **Step 5: Commit explicit files with `refactor(database): fail closed on unsafe migration`.**

