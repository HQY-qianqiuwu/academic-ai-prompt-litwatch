# v2.0H Task 2 Report — Real Migration and Python Lifecycle Rehearsal

## Outcome

**PASS for the scoped isolated rehearsal. Release remains NOT STABLE.**

The real v1.7 SQLite database was opened read-only, snapshotted consistently,
migrated on an isolated copy, exercised through disposable failure and recovery
paths, and left byte-for-byte unchanged at its recorded source hash. The real
Python-only lifecycle then completed cold/warm/status/stop/restart/final-stop
on port 18080 with an isolated v10 database. A real OpenAlex request, no-key
extractive analysis, and subscription/radar restart persistence all passed.

No production file was changed in this task. The only intended repository
changes are the two evidence documents and this report.

## Safety boundaries

- Source v1.7 database: SQLite URI `mode=ro`, `PRAGMA query_only=1`.
- Port 8000 and protected v1.7 PID 37408: not signalled, stopped, or replaced.
- Runtime port: 18080 only, verified free before the final orchestration.
- Runtime database: `<task-temp>/runtime-h2-corrected.db`, never the live DB.
- Interpreter: existing trusted launcher, allowed only through the explicit
  non-default-port switch; exact v2 import validation remained active.
- Secrets: no `.env` read or created; no provider headers, credentials, paper
  payloads, titles, or abstracts recorded.
- Dify/DSL/stable/protected/`.learnings`: untouched.
- Network: only the required real OpenAlex search was performed.
- Git: no push or tag.

## Review-fix reproducibility record

The complete secret-free pseudoharness is now documented in
`docs/V2_0_MIGRATION_REHEARSAL.md`. This section records the same execution
contract compactly so the report is independently auditable. Angle-bracket
values are placeholders; no actual user path, key, header, or paper payload is
included.

### Sanitized environment

From `<v2.0-worktree>`, create a fresh `<task-temp>`, verify port 18080 and
`data/litwatch-stack-18080.pid` are absent, remove inherited `LITWATCH_*`,
`H2_*`, `OPENAI_API_KEY`, and `ANTHROPIC_API_KEY` variables, and refuse to run
if `<v2.0-worktree>/.env` exists. The isolated child receives only:

```text
LITWATCH_PYTHON=<already-trusted-python>
LITWATCH_ALLOW_EXTERNAL_PYTHON=1       # port 18080 only; never port 8000
LITWATCH_RUNTIME_MODE=python_default
LITWATCH_DATABASE_PATH=<task-temp>/runtime-h2.db
LITWATCH_DATABASE_BACKUP_PATH=<task-temp>/runtime-backups
LITWATCH_TOPICS_PATH=<v2.0-worktree>/config/topics.yaml
LITWATCH_ANALYSIS_MODES_PATH=<v2.0-worktree>/config/analysis_modes.yaml
LITWATCH_LLM_API_KEY=
LITWATCH_SEMANTIC_SCHOLAR_API_KEY=
LITWATCH_SCHEDULER_POLL_SECONDS=3600
LITWATCH_JOB_POLL_SECONDS=1
```

The start script must resolve `litwatch.web` under `<v2.0-worktree>/src`.
No environment, dependency, or package installation is part of the procedure.

### SQLite snapshot, migration, failure, and recovery

The pseudoharness uses these production calls:

```python
source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
source.execute("PRAGMA query_only=1")
snapshot = sqlite3.connect(snapshot_path)
source.backup(snapshot)
snapshot.close()

coordinator = MigrationCoordinator(
    sqlite3.connect(snapshot_path),
    MIGRATION_REGISTRY,
    backup_directory=task / "backups",
)
state_before = coordinator.inspect()       # require v6
report = coordinator.migrate()             # require applied (7, 8, 9, 10)
verification = coordinator.verify()        # require ok, v10, integrity ok, FK 0
```

Hashes and the approved non-sensitive table counts are captured before and
after each operation. Two disposable v6 copies are made before migration. One
is migrated normally, then passed to a registry with only this approved v11
fixture appended:

```python
invalid_v11 = Migration.from_sql(
    11,
    "intentionally_invalid",
    "CREATE TABLE partial_table(id INTEGER); THIS IS NOT VALID SQL;",
)
MigrationCoordinator(
    failure_connection,
    (*MIGRATION_REGISTRY, invalid_v11),
    backup_directory=task / "failure-backups",
).migrate()  # must raise sqlite3.OperationalError
```

After the exception, assert schema version 10, zero schema/audit rows for v11,
zero `partial_table` rows in `sqlite_master`, unchanged application counts,
integrity `ok`, and zero foreign-key errors. For recovery, copy the successful
v10 database to a third disposable target and call:

```python
verification = MigrationCoordinator(
    recovery_connection,
    MIGRATION_REGISTRY,
    backup_directory=task / "recovery-backups",
).recover(report.backup_path)
```

Discard the coordinator after `recover`, reopen the target read-only, and
require verification at v6, integrity `ok`, unchanged counts, and SHA-256 equal
to the coordinator-created backup. Re-hash the source and require the same hash
recorded before `backup()`.

Observed safe summary: source hash unchanged; v6 snapshot integrity `ok`;
versions 7–10 applied; v10 verification true with zero foreign-key errors;
invalid v11 fully rolled back; recovery verified at v6 and was byte-identical
to its real backup.

### Bounded lifecycle and summary-only HTTP calls

Every lifecycle wrapper is started with explicit file handles, never
`PIPE`/`capture_output`:

```python
with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
    process = subprocess.Popen(
        powershell_command,
        cwd=repo,
        env=sanitized_child_env,
        stdin=subprocess.DEVNULL,
        stdout=stdout_file,
        stderr=stderr_file,
        close_fds=True,
    )
    return_code = process.wait(timeout=phase_timeout)
```

The sequence and bounds are:

```text
start-stack.ps1  -Port 18080 -LitWatchTimeoutSeconds 45 -NoBrowser  (80 s)
start-stack.ps1  -Port 18080 -LitWatchTimeoutSeconds 30 -NoBrowser  (50 s warm)
status-stack.ps1 -Port 18080                                      (30 s)
GET /health, GET /api/v2/runtime, GET /api/v1/providers           (bounded)
POST /api/v1/literature/search                                    (90 s)
POST /api/v1/subscriptions, POST /api/v1/radars                   (15 s each)
stop-stack.ps1   -Port 18080                                      (50 s)
start-stack.ps1  -Port 18080 -LitWatchTimeoutSeconds 45 -NoBrowser  (80 s)
status-stack.ps1 -Port 18080; GET subscriptions; GET radars       (bounded)
finally: stop-stack.ps1 -Port 18080                               (45 s)
```

Total budget is 360 seconds with 60 seconds reserved for `finally`. After cold
start require a final v2 `launcher_child` `.pid`; after warm start require the
complete launcher and port-owner identities to be unchanged. HTTP results are
held only in memory and projected to status/count fields. Runtime projection:
mode, Python-primary, Dify/Docker/SSRF requirements, migration/runtime state,
worker running/active, and scheduler running/last error. Provider projection:
provider name and `runnable` only.

The exact real-search body was:

```json
{
  "topic": "underwater acoustic TDOA localization",
  "limit": 5,
  "providers": ["openalex"]
}
```

Its printed summary was restricted to HTTP status, paper count, OpenAlex
provenance count, provider status, raw count, deduplicated count, and duplicates
removed. Observed: 200, 5, 5, `success`, 10, 8, 2. The full response, ranking,
titles, abstracts, URLs, headers, and keys were not printed.

The summary command was the PowerShell equivalent below; it parses the response
in memory and never emits `$Search` or `$SearchResponse.Content`:

```powershell
$SearchBody = @{
    topic = 'underwater acoustic TDOA localization'
    limit = 5
    providers = @('openalex')
} | ConvertTo-Json -Compress
$SearchResponse = Invoke-WebRequest -UseBasicParsing -TimeoutSec 90 `
    -Method Post -ContentType 'application/json' -Body $SearchBody `
    -Uri 'http://127.0.0.1:18080/api/v1/literature/search'
$Search = $SearchResponse.Content | ConvertFrom-Json
[PSCustomObject]@{
    http_status = [int]$SearchResponse.StatusCode
    paper_count = @($Search.papers).Count
    openalex_provenance_count = @($Search.papers | Where-Object {
        @($_.sources) -contains 'openalex'
    }).Count
    provider_status = @($Search.provider_status | ForEach-Object { $_.status })
    raw_count = $Search.diagnostics.raw_count
    dedup_count = $Search.diagnostics.dedup_count
    duplicates_removed = $Search.diagnostics.duplicates_removed
} | ConvertTo-Json -Compress
Remove-Variable SearchBody, SearchResponse, Search
```

The exact official create bodies were:

```json
{
  "name": "H2 TDOA Rehearsal Corrected",
  "topic": "underwater acoustic TDOA localization",
  "providers": ["openalex"],
  "search_limit": 5,
  "recommendation_limit": 5,
  "frequency": "weekly",
  "weekday": 4,
  "local_time": "16:00",
  "timezone": "Asia/Shanghai",
  "enabled": true
}
```

```json
{
  "name": "H2 TDOA Evolution Corrected",
  "topic": "underwater acoustic TDOA localization",
  "keywords": ["TDOA", "localization"],
  "exclude_keywords": [],
  "providers": ["openalex"],
  "start_year": 2026,
  "end_year": 2026,
  "recent_window_years": 1,
  "search_limit_per_period": 5,
  "enabled": true
}
```

Keep the returned IDs only in memory, print their final eight characters, call
production stop, require listener/identity absence, restart, then GET
`/api/v1/subscriptions` and `/api/v1/radars`. Assert each full in-memory ID is
present and print only booleans and total counts. Observed create status
201/201, suffixes `42aff916`/`8052e1c1`, persistence true/true, totals 4/3.

### No-key analysis and cleanup

Choose one in-memory result with an abstract. Do not print it. Construct a
production `Paper`, then call:

```python
analyzer = PaperAnalyzer(Settings(
    _env_file=None,
    runtime_mode="python_default",
    database_path=Path("<task-temp>/runtime-h2.db"),
    database_backup_path=Path("<task-temp>/runtime-backups"),
    topics_path=Path("<v2.0-worktree>/config/topics.yaml"),
    analysis_modes_path=Path("<v2.0-worktree>/config/analysis_modes.yaml"),
    llm_api_key="",
))
assert analyzer.enabled is False
analysis = analyzer.analyze(paper, Topic(
    id="h2-tdoa",
    name="Underwater acoustic TDOA localization",
    query="underwater acoustic TDOA localization",
    include=["TDOA", "localization"],
))
```

Print only status, evidence level, method/result/limitation counts, and
`llm_enabled`. Observed: `extractive`, abstract, 1/1/0, false.

The outer `finally` always calls production `stop-stack.ps1 -Port 18080`, then
requires listener count 0, exact LitWatch command match count 0, and
`litwatch-stack-18080.pid` absent. A missing, provisional, stale, reused, or
non-exact identity is a blocker; it never authorizes naked-PID cleanup.

## Migration evidence

Source SHA-256 before and after:
`a828fb97fde3b8d5c53ca97db1934f778ecaecf9339b869bac304484e341bbc7`.
The source was 2,654,208 bytes, schema v6, integrity `ok`.

The consistent snapshot was 2,670,592 bytes with SHA-256
`5a7dd16dc704079cd4881e44c272ed6b063f2647745a12fbc8162ca5a3298ae5`,
schema v6, integrity `ok`. Source/snapshot counts matched: papers 455,
paper_topics 104, subscriptions 3, subscription_runs 8, deliveries 8,
research_radars 2, radar_scans 15, radar_papers 335.

Real migration produced v10 with SHA-256
`4c0deee710d34bf7c02493dc43f0308f6ad163cf1b3a5e89830dbce1b2ea2d28`,
verification true, integrity `ok`, zero foreign-key errors, ten successful audit
rows, and preserved application counts. The real v6 backup SHA-256 was
`2389a0956feaba7aee79408014ad0df9f2df2c5169ed5ae248824ca99a4729db`.

The disposable invalid v11 migration raised `OperationalError` and left v10,
zero v11 audit rows, zero fixture partial-table rows, unchanged counts,
verification true, integrity `ok`, and zero foreign-key errors. Its failure
backup SHA-256 was
`5caf0b0c28f30cd03fb416d972dabb14be37f2c64f60cd7b8d2055f9533b86fa`.

Recovery on a third disposable copy returned to v6 with verification true,
integrity `ok`, unchanged counts, and a file byte-identical to the real backup.

## Runtime/search evidence

The final corrected orchestration completed in 76.781 seconds under a 360
second total budget with 60 seconds reserved for cleanup. Each lifecycle child
redirected stdout/stderr to explicit task-temporary files and had its own
timeout. The `finally` path invoked production `stop-stack.ps1`.

- Cold identity: v2 `launcher_child`, launch PID 55972, owner PID 54248.
- Warm start: exact same launch and owner identity.
- Status: all five checks PASS; System READY.
- Runtime: `python_default`, migration/runtime/worker/scheduler healthy,
  worker active 0, scheduler last error null, Dify/Docker/SSRF false.
- Real OpenAlex: HTTP 200, 5 papers, provenance 5/5, provider `success`, raw 10,
  deduplicated 8, duplicates removed 2.
- Analysis: no-key production analyzer, `extractive`, abstract evidence, one
  method and one result, no LLM enabled.
- Created through official APIs: subscription suffix `42aff916` and radar
  suffix `8052e1c1`, both HTTP 201.
- First production stop: exit 0; listener and `.pid` absent.
- Restart identity: new v2 lineage, launch PID 4772, owner PID 47200.
- Persistence: both IDs present through official GET routes; totals 4
  subscriptions and 3 radars.
- Final production stop: exit 0; listener count 0, exact matching process count
  0, `.pid` absent.
- Final isolated DB: v10, integrity `ok`, foreign-key errors 0, SHA-256
  `4ad6bd9468d6108d5ff23f57fc83ec7a3a05222b8184d583921c012d256c94bc`.

Phase logs are retained under
`<task-temp>/orchestration-corrected/01-cold_start.stdout.log` through
`07-final_stop.stdout.log`, with paired stderr logs. All seven stderr logs are
empty.

## Harness RED/GREEN record

The first orchestration was a test-harness RED, not a product RED. It used
anonymous `capture_output` pipes around a PowerShell wrapper. The wrapper
launched the persistent server lineage, which inherited the anonymous output
handles; therefore the parent Python wait could not observe pipe EOF when the
wrapper's work was otherwise ready. The server returned HTTP 200 for health,
runtime, and providers, but the harness timed out at `cold_start` waiting on
the captured subprocess I/O lifecycle and never entered search. Sanitized exit:
`PhaseError: start-stack.ps1 exceeded phase timeout`; success false. Its finally
path invoked the production stop script.

After root-cause confirmation, the one authorized corrected harness replaced
PIPE capture with explicit file redirection and process-handle waits. No
production code changed. The corrected run was GREEN and no retry followed.

## Verification gates

Focused migration/lifecycle/API acceptance:

```powershell
python -m pytest -q tests/test_database_migrations.py tests/test_lifecycle_scripts.py tests/test_v2_acceptance.py tests/test_literature_search_api.py tests/test_radars.py tests/test_subscriptions.py tests/test_paper_analyzer.py
```

Result: `150 passed, 1 warning in 67.96s`.

Full suite:

```powershell
python -m pytest -q
```

Result: `604 passed, 1 warning in 117.08s`.

The one warning in both runs is the existing Starlette deprecation warning for
the installed `httpx` TestClient integration; it does not weaken the gate.

Static and repository gates:

```powershell
ruff check src tests
# PowerShell parser over all scripts/*.ps1
git diff --check
git fsck --no-dangling
git diff --exit-code dify-v1.0 -- dify/workflows/literature-search-v1.0.yml
git diff --exit-code dify-v1.1 -- dify/workflows/literature-search-v1.1.yml
```

Results: Ruff `All checks passed!`; PowerShell parser PASS for all 15 scripts;
diff-check, fsck, and both stable DSL comparisons exited zero. Final safety
probe: port-18080 listener count 0, exact matching process count 0, managed
identity absent, and repository `.env` absent.

Documentation-only review-fix gates:

- Markdown fence structure and final-newline checks: PASS for both files;
- Python fenced blocks: `ast.parse` PASS;
- JSON fenced blocks: JSON parse PASS;
- PowerShell fenced blocks: PowerShell parser PASS;
- real-path/credential/token/Bearer/non-empty-secret scan: PASS;
- `git diff --check`: PASS;
- full `python -m pytest -q`: `604 passed, 1 warning in 114.61s`;
- `ruff check src tests`: `All checks passed!`; and
- `git fsck --no-dangling` plus stable v1.0/v1.1 DSL comparisons: PASS.

The review fix did not execute the lifecycle rehearsal, open a real network
request, or start a LitWatch listener. The full suite uses only its existing
controlled test boundaries. The warning remains the existing Starlette/httpx
deprecation described above.

## Files in the H2 commit

- `docs/V2_0_E2E_RESULTS.md`
- `docs/V2_0_MIGRATION_REHEARSAL.md`
- `.superpowers/sdd/2026-08-11-v2-0h-acceptance/task-2-report.md`

This documentation-only review fix changes exactly
`docs/V2_0_MIGRATION_REHEARSAL.md` and this Task 2 report. It does not revise
the already accurate `docs/V2_0_E2E_RESULTS.md` evidence summary.

No push or tag is authorized. Final release-owner manual acceptance is still
required; old Dify rollback assets and stable v1.0/v1.1 DSL files remain frozen.
