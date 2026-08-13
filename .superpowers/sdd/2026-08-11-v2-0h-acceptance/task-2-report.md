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
anonymous `capture_output` pipes around a PowerShell command that launched a
persistent descendant. The server returned HTTP 200 for health, runtime, and
providers, but the harness timed out at `cold_start` waiting on the subprocess
I/O lifecycle and never entered search. Sanitized exit:
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

## Files in the H2 commit

- `docs/V2_0_E2E_RESULTS.md`
- `docs/V2_0_MIGRATION_REHEARSAL.md`
- `.superpowers/sdd/2026-08-11-v2-0h-acceptance/task-2-report.md`

No push or tag is authorized. Final release-owner manual acceptance is still
required; old Dify rollback assets and stable v1.0/v1.1 DSL files remain frozen.
