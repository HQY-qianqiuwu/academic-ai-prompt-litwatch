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
PowerShell while PowerShell launched the persistent server lineage. Health,
runtime, and provider probes returned HTTP 200, but the harness waited for pipe
EOF and reported `PhaseError: start-stack.ps1 exceeded phase timeout` before it
could enter search. The problem was the test harness's descendant pipe
lifecycle, not production readiness. That run did not create the H2 records.
After diagnosis, the release owner authorized exactly one corrected run using
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
