# LitWatch v2.0 Migration and Runtime Rehearsal

## Status and scope

**RELEASE CANDIDATE PREPARATION — NOT STABLE**

This document records the 2026-08-14 isolated rehearsal of the real v1.7
SQLite data and the v2.0 Python-only lifecycle. It is secret-free evidence, not
permission to modify the live v1.7 database, stop its protected process, delete
historical Dify assets, or create a Stable tag.

Sanitized path names used below:

- `<v1.7-repo>/data/litwatch.db`: the live source, opened read-only;
- `<v2.0-worktree>`: the isolated v2.0 Git worktree;
- `<task-temp>`: a task-specific directory under the current user's local
  temporary directory; and
- `<task-temp>/runtime-h2-corrected.db`: the isolated v10 runtime database.

The retained task directory is named
`litwatch-v2h-task2-20260813T221055Z-89077177`. It contains only disposable
copies, backups, SQLite lock/WAL companions, and rehearsal logs; it contains no
`.env` file or captured provider payload.

## Reproducible secret-free pseudoharness

The following is the sanitized procedure used for the rehearsal. Angle-bracket
values are operator-supplied paths, not literal values. Create a new
`<task-temp>` for every run. Do not substitute the live database for any
writable target, and do not use port 8000.

### 1. Sanitize the child environment

Run from `<v2.0-worktree>`. This setup deliberately removes inherited LitWatch
and cloud/provider credentials, refuses a repository `.env`, and supplies only
the non-secret settings needed by the isolated process:

```powershell
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path '<v2.0-worktree>').Path
$RequestedTaskTemp = '<new-task-temp>'
if (Test-Path -LiteralPath $RequestedTaskTemp) {
    throw 'Use a new task-specific temporary directory.'
}
$TaskTemp = (New-Item -ItemType Directory -Path $RequestedTaskTemp).FullName
$TrustedPython = (Resolve-Path '<trusted-python>').Path
$Port = 18080
$RuntimeDb = Join-Path $TaskTemp 'runtime-h2.db'
$LogDir = New-Item -ItemType Directory -Path (Join-Path $TaskTemp 'orchestration')

Get-ChildItem Env: | Where-Object {
    $_.Name -like 'LITWATCH_*' -or $_.Name -like 'H2_*'
} | ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" }
foreach ($Name in @('OPENAI_API_KEY', 'ANTHROPIC_API_KEY')) {
    Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath (Join-Path $Repo '.env')) {
    throw 'Rehearsal requires an .env-free worktree.'
}

$env:LITWATCH_PYTHON = $TrustedPython
$env:LITWATCH_ALLOW_EXTERNAL_PYTHON = '1' # permitted only because Port is not 8000
$env:LITWATCH_RUNTIME_MODE = 'python_default'
$env:LITWATCH_DATABASE_PATH = $RuntimeDb
$env:LITWATCH_DATABASE_BACKUP_PATH = Join-Path $TaskTemp 'runtime-backups'
$env:LITWATCH_TOPICS_PATH = Join-Path $Repo 'config\topics.yaml'
$env:LITWATCH_ANALYSIS_MODES_PATH = Join-Path $Repo 'config\analysis_modes.yaml'
$env:LITWATCH_LLM_API_KEY = ''
$env:LITWATCH_SEMANTIC_SCHOLAR_API_KEY = ''
$env:LITWATCH_SCHEDULER_POLL_SECONDS = '3600'
$env:LITWATCH_JOB_POLL_SECONDS = '1'
```

The interpreter must already be trusted. Do not create a virtual environment
or install dependencies for this procedure. `start-stack.ps1` must print an
import path under `<v2.0-worktree>/src`; its external-interpreter switch cannot
authorize default port 8000.

### 2. Create a read-only SQLite snapshot and exercise migrations

The migration pseudoharness below uses only placeholder paths and prints hashes,
versions, integrity, foreign-key counts, row counts, and backup *file names*.
It never prints paper fields or a full local path.

```python
from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2
import sqlite3

from litwatch.db import MIGRATION_REGISTRY
from litwatch.migrations import Migration, MigrationCoordinator

source_path = Path("<v1.7-repo>/data/litwatch.db").resolve()
task = Path("<new-task-temp>").resolve()
snapshot = task / "v1_7-consistent-snapshot.db"
failure_db = task / "failure-disposable.db"
recovery_db = task / "recovery-disposable.db"
tables = (
    "papers", "paper_topics", "subscriptions", "subscription_runs",
    "deliveries", "research_radars", "radar_scans", "radar_papers",
)

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def safe_counts(connection):
    return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in tables}

# The source is opened read-only and made query-only before SQLite backup().
source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
source.execute("PRAGMA query_only=1")
source_hash_before = digest(source_path)
snapshot_connection = sqlite3.connect(snapshot)
source.backup(snapshot_connection)
snapshot_connection.close()
source_counts = safe_counts(source)
source.close()

# Preserve two v6 disposable copies before migrating the real snapshot copy.
copy2(snapshot, failure_db)
snapshot_hash_v6 = digest(snapshot)

connection = sqlite3.connect(snapshot)
connection.execute("PRAGMA foreign_keys=ON")
coordinator = MigrationCoordinator(
    connection, MIGRATION_REGISTRY, backup_directory=task / "backups"
)
state_before = coordinator.inspect()
report = coordinator.migrate()
verification = coordinator.verify()
assert state_before.current_version == 6
assert report.applied_versions == (7, 8, 9, 10)
assert verification.ok and verification.current_version == 10
assert safe_counts(connection) == source_counts
real_backup = report.backup_path
assert real_backup is not None
connection.close()

# Start the failure fixture from v6, migrate it normally, then add only the
# approved invalid v11. The invalid CREATE and audit/version row must roll back.
failure_connection = sqlite3.connect(failure_db)
failure_connection.execute("PRAGMA foreign_keys=ON")
MigrationCoordinator(
    failure_connection, MIGRATION_REGISTRY, backup_directory=task / "backups"
).migrate()
invalid_v11 = Migration.from_sql(
    11,
    "intentionally_invalid",
    "CREATE TABLE partial_table(id INTEGER); THIS IS NOT VALID SQL;",
)
try:
    MigrationCoordinator(
        failure_connection,
        (*MIGRATION_REGISTRY, invalid_v11),
        backup_directory=task / "failure-backups",
    ).migrate()
    raise AssertionError("invalid v11 unexpectedly succeeded")
except sqlite3.OperationalError:
    pass
assert failure_connection.execute(
    "SELECT COUNT(*) FROM schema_migrations WHERE version=11"
).fetchone()[0] == 0
assert failure_connection.execute(
    "SELECT COUNT(*) FROM migration_audit WHERE version=11"
).fetchone()[0] == 0
assert failure_connection.execute(
    "SELECT COUNT(*) FROM sqlite_master WHERE name='partial_table'"
).fetchone()[0] == 0
failure_connection.close()

# Recovery uses a third disposable v10 copy and the coordinator-created v6
# backup. The coordinator is discarded after recover(); reopen for checks.
copy2(snapshot, recovery_db)
recovery_connection = sqlite3.connect(recovery_db)
recovery_connection.execute("PRAGMA foreign_keys=ON")
recovery = MigrationCoordinator(
    recovery_connection, MIGRATION_REGISTRY,
    backup_directory=task / "recovery-backups",
).recover(real_backup)
assert recovery.ok and recovery.current_version == 6
restored = sqlite3.connect(recovery_db.as_uri() + "?mode=ro", uri=True)
restored.execute("PRAGMA query_only=1")
assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
assert safe_counts(restored) == source_counts
restored.close()
assert digest(recovery_db) == digest(real_backup)

source_hash_after = digest(source_path)
assert source_hash_after == source_hash_before
print(json.dumps({
    "source_sha256_before": source_hash_before,
    "source_sha256_after": source_hash_after,
    "snapshot_v6_sha256": snapshot_hash_v6,
    "migrated_v10_sha256": digest(snapshot),
    "backup_name": real_backup.name,
    "migration_ok": verification.ok,
    "migration_version": verification.current_version,
    "integrity": verification.integrity,
    "foreign_key_error_count": len(verification.foreign_key_errors),
    "counts": source_counts,
    "invalid_v11_rolled_back": True,
    "recovery_version": recovery.current_version,
    "recovery_byte_identical": True,
}, sort_keys=True))
```

Observed sanitized summary: source hashes matched before/after; source and
snapshot were v6 with integrity `ok`; migration applied versions 7–10 and
verified at v10 with zero foreign-key errors; invalid v11 left no schema,
audit, or partial-table commit; recovery verified at v6 and was byte-identical
to the coordinator backup. Exact hashes and counts appear in the evidence
sections below.

### 3. Run lifecycle commands without anonymous capture pipes

Use a bounded parent process and redirect each PowerShell wrapper to real files.
The important property is `stdout=file`, `stderr=file`, `stdin=DEVNULL`, and
`close_fds=True`; do not use `PIPE` or `capture_output=True` around a wrapper
that launches the persistent server lineage.

```python
from pathlib import Path
import subprocess

repo = Path("<v2.0-worktree>")
log_dir = Path("<new-task-temp>/orchestration")
powershell = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
child_env = sanitized_environment_from_step_1()

def lifecycle(phase, script, *arguments, timeout):
    command = [
        str(powershell), "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File",
        str(repo / "scripts" / script), *map(str, arguments),
    ]
    with (log_dir / f"{phase}.stdout.log").open("wb") as stdout_file, \
         (log_dir / f"{phase}.stderr.log").open("wb") as stderr_file:
        process = subprocess.Popen(
            command, cwd=repo, env=child_env, stdin=subprocess.DEVNULL,
            stdout=stdout_file, stderr=stderr_file, close_fds=True,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()       # retained wrapper handle, never a naked PID
            process.wait(timeout=10)
            raise
    if return_code != 0:
        raise RuntimeError(f"{phase} exited {return_code}")

# Overall deadline: 360 seconds; keep 60 seconds reserved for finally cleanup.
lifecycle("01-cold", "start-stack.ps1", "-Port", 18080,
          "-LitWatchTimeoutSeconds", 45, "-NoBrowser", timeout=80)
lifecycle("02-warm", "start-stack.ps1", "-Port", 18080,
          "-LitWatchTimeoutSeconds", 30, "-NoBrowser", timeout=50)
lifecycle("03-status", "status-stack.ps1", "-Port", 18080, timeout=30)
```

After cold start, read
`<v2.0-worktree>/data/litwatch-stack-18080.pid` and require
`version=2`, `state=final`, and `topology=launcher_child`. After warm start,
require the complete `launch_process` and `port_owner_process` objects to be
unchanged. Do not authorize a stop from a provisional, stale, missing, or
partially matching record.

### 4. Request runtime/provider/search summaries only

The following HTTP pseudocode retains responses only in memory and prints a
strict safe projection. `http_json` is an ordinary bounded JSON request helper
returning `(status_code, parsed_json)`; it sets only `Content-Type:
application/json` for JSON POSTs and prints no request or response headers.

```python
health_status, _ = http_json("GET", "http://127.0.0.1:18080/health")
runtime_status, runtime = http_json(
    "GET", "http://127.0.0.1:18080/api/v2/runtime"
)
provider_status, providers = http_json(
    "GET", "http://127.0.0.1:18080/api/v1/providers"
)
runtime_fields = (
    "mode", "python_primary", "requires_dify", "requires_docker",
    "requires_ssrf_proxy", "migration_verified", "runtime_started",
    "job_worker_running", "job_worker_active", "scheduler_running",
    "scheduler_last_error",
)
print({
    "health_http_status": health_status,
    "runtime_http_status": runtime_status,
    "runtime": {name: runtime.get(name) for name in runtime_fields},
    "provider_http_status": provider_status,
    "providers": [
        {"name": item.get("name"), "runnable": item.get("runnable")}
        for item in providers
    ],
})

search_status, search = http_json(
    "POST",
    "http://127.0.0.1:18080/api/v1/literature/search",
    json_body={
        "topic": "underwater acoustic TDOA localization",
        "limit": 5,
        "providers": ["openalex"],
    },
    timeout=90,
)
papers = search.get("papers", [])
provenance_count = sum(
    "openalex" in paper.get("sources", []) for paper in papers
)
diagnostics = search.get("diagnostics", {})
print({
    "http_status": search_status,
    "paper_count": len(papers),
    "openalex_provenance_count": provenance_count,
    "provider_status": [
        item.get("status") for item in search.get("provider_status", [])
    ],
    "raw_count": diagnostics.get("raw_count"),
    "dedup_count": diagnostics.get("dedup_count"),
    "duplicates_removed": diagnostics.get("duplicates_removed"),
})
```

Required assertions are HTTP 200, `paper_count > 0`, all provider statuses
`success`, and OpenAlex provenance on every returned paper. Observed summary:
HTTP 200, 5 papers, provenance 5/5, provider `success`, raw 10, deduplicated 8,
duplicates removed 2. Do not print `search`, `papers`, ranking entries, titles,
abstracts, headers, or URLs.

This PowerShell equivalent makes the output restriction explicit. It parses
the bodies in memory, emits only whitelisted fields, then drops the full
objects. `Invoke-WebRequest` sends no credential or custom provider header:

```powershell
$BaseUrl = 'http://127.0.0.1:18080'
$HealthResponse = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 `
    -Uri "$BaseUrl/health"
$RuntimeResponse = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 `
    -Uri "$BaseUrl/api/v2/runtime"
$ProviderResponse = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 `
    -Uri "$BaseUrl/api/v1/providers"
$Runtime = $RuntimeResponse.Content | ConvertFrom-Json
$Providers = $ProviderResponse.Content | ConvertFrom-Json
[PSCustomObject]@{
    health_http_status = [int]$HealthResponse.StatusCode
    runtime_http_status = [int]$RuntimeResponse.StatusCode
    mode = $Runtime.mode
    python_primary = $Runtime.python_primary
    requires_dify = $Runtime.requires_dify
    requires_docker = $Runtime.requires_docker
    requires_ssrf_proxy = $Runtime.requires_ssrf_proxy
    migration_verified = $Runtime.migration_verified
    runtime_started = $Runtime.runtime_started
    job_worker_running = $Runtime.job_worker_running
    job_worker_active = $Runtime.job_worker_active
    scheduler_running = $Runtime.scheduler_running
    scheduler_last_error = $Runtime.scheduler_last_error
    providers = @($Providers | ForEach-Object {
        [PSCustomObject]@{ name = $_.name; runnable = $_.runnable }
    })
} | ConvertTo-Json -Compress -Depth 4

$SearchBody = @{
    topic = 'underwater acoustic TDOA localization'
    limit = 5
    providers = @('openalex')
} | ConvertTo-Json -Compress
$SearchResponse = Invoke-WebRequest -UseBasicParsing -TimeoutSec 90 `
    -Method Post -ContentType 'application/json' -Body $SearchBody `
    -Uri "$BaseUrl/api/v1/literature/search"
$Search = $SearchResponse.Content | ConvertFrom-Json
$OpenAlexCount = @($Search.papers | Where-Object {
    @($_.sources) -contains 'openalex'
}).Count
[PSCustomObject]@{
    http_status = [int]$SearchResponse.StatusCode
    paper_count = @($Search.papers).Count
    openalex_provenance_count = $OpenAlexCount
    provider_status = @($Search.provider_status | ForEach-Object { $_.status })
    raw_count = $Search.diagnostics.raw_count
    dedup_count = $Search.diagnostics.dedup_count
    duplicates_removed = $Search.diagnostics.duplicates_removed
} | ConvertTo-Json -Compress
Remove-Variable HealthResponse, RuntimeResponse, ProviderResponse, Runtime, `
    Providers, SearchBody, SearchResponse, Search, OpenAlexCount
```

### 5. Exercise the no-key extractive path

Select one in-memory OpenAlex result with a non-empty abstract, but never print
the result or evidence. Build only the production models required by the
analyzer:

```python
from litwatch.analysis import PaperAnalyzer
from litwatch.config import Settings, Topic
from litwatch.models import Author, Paper

sample = next(item for item in papers if item.get("abstract"))
paper = Paper(
    canonical_id=sample["canonical_id"],
    sources=sample.get("sources", []),
    title=sample.get("title", ""),
    abstract=sample.get("abstract", ""),
    authors=[Author(name=name) for name in sample.get("authors", [])],
)
analyzer = PaperAnalyzer(Settings(
    _env_file=None,
    runtime_mode="python_default",
    database_path=Path("<new-task-temp>/runtime-h2.db"),
    database_backup_path=Path("<new-task-temp>/runtime-backups"),
    topics_path=Path("<v2.0-worktree>/config/topics.yaml"),
    analysis_modes_path=Path("<v2.0-worktree>/config/analysis_modes.yaml"),
    llm_api_key="",
))
assert analyzer.enabled is False
analysis = analyzer.analyze(
    paper,
    Topic(
        id="h2-tdoa",
        name="Underwater acoustic TDOA localization",
        query="underwater acoustic TDOA localization",
        include=["TDOA", "localization"],
    ),
)
print({
    "status": analysis.get("status"),
    "evidence_level": analysis.get("evidence_level"),
    "method_count": len(analysis.get("methods", [])),
    "result_count": len(analysis.get("results", [])),
    "limitation_count": len(analysis.get("limitations", [])),
    "llm_enabled": analyzer.enabled,
})
```

Observed safe projection: `extractive`, abstract evidence, one method, one
result, zero limitations, and `llm_enabled=false`.

### 6. Create, restart, and verify official persisted records

Use `http_json` from step 4. Keep full IDs only in process memory and print
only their last eight characters:

```python
subscription_status, subscription = http_json(
    "POST", "http://127.0.0.1:18080/api/v1/subscriptions",
    json_body={
        "name": "H2 TDOA Rehearsal Corrected",
        "topic": "underwater acoustic TDOA localization",
        "providers": ["openalex"],
        "search_limit": 5,
        "recommendation_limit": 5,
        "frequency": "weekly",
        "weekday": 4,
        "local_time": "16:00",
        "timezone": "Asia/Shanghai",
        "enabled": True,
    },
)
radar_status, radar = http_json(
    "POST", "http://127.0.0.1:18080/api/v1/radars",
    json_body={
        "name": "H2 TDOA Evolution Corrected",
        "topic": "underwater acoustic TDOA localization",
        "keywords": ["TDOA", "localization"],
        "exclude_keywords": [],
        "providers": ["openalex"],
        "start_year": 2026,
        "end_year": 2026,
        "recent_window_years": 1,
        "search_limit_per_period": 5,
        "enabled": True,
    },
)
assert subscription_status == radar_status == 201
subscription_id, radar_id = subscription["id"], radar["id"]
print({
    "subscription_http_status": subscription_status,
    "subscription_id_suffix": subscription_id[-8:],
    "radar_http_status": radar_status,
    "radar_id_suffix": radar_id[-8:],
})

lifecycle("04-first-stop", "stop-stack.ps1", "-Port", 18080, timeout=50)
assert not port_listening(18080) and not identity_file_exists(18080)
lifecycle("05-restart", "start-stack.ps1", "-Port", 18080,
          "-LitWatchTimeoutSeconds", 45, "-NoBrowser", timeout=80)
lifecycle("06-status", "status-stack.ps1", "-Port", 18080, timeout=30)
_, subscriptions = http_json(
    "GET", "http://127.0.0.1:18080/api/v1/subscriptions"
)
_, radars = http_json("GET", "http://127.0.0.1:18080/api/v1/radars")
assert any(item.get("id") == subscription_id for item in subscriptions)
assert any(item.get("id") == radar_id for item in radars)
print({
    "subscription_persisted": True,
    "subscription_count": len(subscriptions),
    "radar_persisted": True,
    "radar_count": len(radars),
})
```

Observed safe projection: create HTTP 201/201, suffixes `42aff916` and
`8052e1c1`, persistence true/true, subscription total 4, radar total 3.

### 7. Always perform production cleanup and fail closed

Put the phase sequence inside `try/finally`. The final action is always the
production stop script, followed by read-only absence checks:

```python
try:
    run_all_phases()
finally:
    lifecycle("07-final-stop", "stop-stack.ps1", "-Port", 18080, timeout=45)
    assert not port_listening(18080)
    assert not identity_file_exists(18080)  # litwatch-stack-18080.pid
    assert exact_litwatch_command_matches(port=18080) == 0
```

If the port has no valid managed identity or any exact lineage check fails,
stop and report the blocker. Never stop the occupant by naked PID. Observed
cleanup: production stop exit 0, listener count 0, exact command matches 0,
and managed identity absent.

## Source snapshot

The source connection used a SQLite URI with `mode=ro`, followed by
`PRAGMA query_only=1`. Python's SQLite backup API created a transactionally
consistent copy; ordinary filesystem copying was not used for the live source.

| Evidence | Source | Consistent snapshot |
|---|---:|---:|
| Bytes | 2,654,208 | 2,670,592 |
| SHA-256 | `a828fb97fde3b8d5c53ca97db1934f778ecaecf9339b869bac304484e341bbc7` | `5a7dd16dc704079cd4881e44c272ed6b063f2647745a12fbc8162ca5a3298ae5` |
| Schema version | 6 | 6 |
| Integrity | `ok` | `ok` |

The source SHA-256 was calculated again after all migration, failure, and
recovery operations and was unchanged. Source and snapshot row counts matched:

| Table | Rows |
|---|---:|
| `papers` | 455 |
| `paper_topics` | 104 |
| `subscriptions` | 3 |
| `subscription_runs` | 8 |
| `deliveries` | 8 |
| `research_radars` | 2 |
| `radar_scans` | 15 |
| `radar_papers` | 335 |

## Real migration and backup

The v2.0 import was resolved from `<v2.0-worktree>/src` before invoking the
production `MigrationCoordinator`. Preflight identified v6, migration advanced
the isolated snapshot to v10, and production verification returned true.

| Evidence | Result |
|---|---:|
| Post-migration SHA-256 | `4c0deee710d34bf7c02493dc43f0308f6ad163cf1b3a5e89830dbce1b2ea2d28` |
| Schema version | 10 |
| Integrity | `ok` |
| Foreign-key errors | 0 |
| Successful migration-audit rows | 10 |
| `jobs` rows | 0 |
| `paper_analyses` rows | 0 |

All pre-existing table counts listed above were preserved. The coordinator
created one real v6-to-v10 backup. Its SHA-256 was
`2389a0956feaba7aee79408014ad0df9f2df2c5169ed5ae248824ca99a4729db`;
it independently verified at schema v6 with integrity `ok` and the same source
counts.

## Failing migration and recovery

Failure and recovery used separate disposable copies; neither operation
targeted the source or the successful migrated snapshot.

For failure rehearsal, the approved fixture added an invalid v11 migration to
the production migration sequence. The coordinator raised SQLite
`OperationalError`. The disposable database remained at v10, had zero v11
audit rows, zero rows for the fixture's partial table, unchanged application
counts, verification true, integrity `ok`, and zero foreign-key errors. Its
single failure backup had SHA-256
`5caf0b0c28f30cd03fb416d972dabb14be37f2c64f60cd7b8d2055f9533b86fa`.

For recovery rehearsal, another disposable v10 copy was restored through
`MigrationCoordinator.recover` using the real v6-to-v10 backup. Verification
returned true at v6, integrity returned `ok`, every recorded pre-migration
count matched, and the recovered file SHA-256 was the backup SHA-256
`2389a0956feaba7aee79408014ad0df9f2df2c5169ed5ae248824ca99a4729db`.
The restored database was byte-identical to the backup.

## Python-only lifecycle and real OpenAlex

Port 18080 was verified to have zero listeners and no managed `.pid` before
the final run. The v2.0 worktree has no local `.venv`, so the lifecycle used the
already trusted v1.7 virtual-environment launcher through the explicit
`LITWATCH_ALLOW_EXTERNAL_PYTHON=1` non-default-port smoke policy. Exact import
validation still required `litwatch.web` to resolve from the v2.0 `src`
directory. This policy cannot authorize an external interpreter on default
port 8000.

The corrected test harness launched each lifecycle PowerShell process with
stdout/stderr redirected to explicit files under
`<task-temp>/orchestration-corrected`; it did not use anonymous PIPE capture.
Every phase had a timeout, the total budget was 360 seconds with 60 seconds
reserved for cleanup, and the `finally` path invoked production
`stop-stack.ps1`. The run completed in 76.781 seconds.

| Phase | Result | Duration (s) |
|---|---|---:|
| Cold start | final v2 `launcher_child`; launch 55972, owner 54248 | 9.641 |
| Warm start | same launch/owner identity | 5.781 |
| Status before search | all five checks PASS; System READY | 5.109 |
| Runtime endpoint | HTTP 200; live components healthy | 0.110 |
| Real OpenAlex search | HTTP 200; provider success | 1.468 |
| First exact stop | exit 0; listener and identity absent | 17.875 |
| Restart | new final v2 lineage; launch 4772, owner 47200 | 11.969 |
| Status after restart | all five checks PASS; System READY | 5.156 |
| Final production stop | exit 0 | 17.515 |

The live runtime state was `python_default`, Python-primary, migration verified,
runtime started, job worker running with zero active jobs, scheduler running
with no last error, and `requires_dify`, `requires_docker`, and
`requires_ssrf_proxy` all false.

The official Manual Search API queried
`underwater acoustic TDOA localization` with limit 5 and provider OpenAlex.
Sanitized evidence: HTTP 200; paper count 5; OpenAlex provenance count 5;
provider status `success`; raw count 10; deduplicated count 8; duplicates
removed 2. No paper title, abstract, full response, header, key, or credential
was retained in this document.

One returned paper with an abstract was passed to the production
`PaperAnalyzer` configured with no LLM key. The analyzer reported
`status=extractive`, `evidence_level=abstract`, one method, one result, no cloud
LLM enabled, and OpenAlex provenance.

The official APIs created a non-sensitive subscription and radar:

| Record | Create | Sanitized ID suffix | After restart |
|---|---:|---|---:|
| Subscription | HTTP 201 | `42aff916` | present; total 4 |
| Research radar | HTTP 201 | `8052e1c1` | present; total 3 |

The final isolated database was v10, 2,732,032 bytes, integrity `ok`, zero
foreign-key errors, and SHA-256
`4ad6bd9468d6108d5ff23f57fc83ec7a3a05222b8184d583921c012d256c94bc`.
The sanitized suffixes were each unique in their table.

After the final production stop, port 18080 had zero listeners, the exact
LitWatch command match count was zero, and
`<v2.0-worktree>/data/litwatch-stack-18080.pid` was absent.

## Harness diagnostic note

An earlier temporary harness used `subprocess.run(capture_output=True)` around
a PowerShell wrapper. The wrapper launched the persistent server lineage,
whose descendant inherited the anonymous output handles. The parent Python
wait therefore could not observe pipe EOF even though health, runtime, and
provider probes returned HTTP 200. It reported
`PhaseError: start-stack.ps1 exceeded phase timeout` before entering search.
This was the test harness's descendant-handle/pipe-EOF lifecycle, not a
production readiness failure. That run did not create the H2 records. After
diagnosis, the release owner authorized exactly one corrected run using
explicit file redirection; the successful results above are solely from that
run.

## Rollback procedure

1. Stop only a v2 process whose complete managed identity, creation times,
   executable fingerprints, exact argv, app directory, host, port owner, and
   lineage all validate. Never stop by a naked PID or because a port is merely
   occupied.
2. Preserve the target database and its WAL/SHM companions for investigation.
   Do not overwrite `<v1.7-repo>/data/litwatch.db`.
3. Select an authorized coordinator-created backup, independently verify its
   expected hash, SQLite integrity, schema version, and application counts,
   then call `MigrationCoordinator.recover` against an isolated or explicitly
   authorized v2 target.
4. Re-run production verification, `PRAGMA integrity_check`,
   `PRAGMA foreign_key_check`, and row-count invariants before restart.
5. If Python-native v2 acceptance is withdrawn, use the documented explicit
   legacy Dify rollback path. There is no automatic fallback from Python to
   Dify. The old repository/volumes and stable v1.0/v1.1 DSL files remain
   frozen until release-owner manual acceptance.

Port 8000 and protected v1.7 PID 37408 were never signalled, stopped, or
replaced during this rehearsal.
