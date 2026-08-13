# Task 3 Report: Dify-free configuration and compatibility evidence

## Outcome

- The documented v2.0 default is now unambiguously Python-only: FastAPI,
  SQLite, Scheduler, JobWorker, and the Python LLM gateway. Default start,
  stop, and status do not probe, start, or require Docker, Dify, Compose, or
  the Dify SSRF proxy.
- Python startup failure is fail-closed. There is no automatic Dify fallback.
  Dify rollback is an explicit operator action through the two launchers whose
  names include `旧版 Dify`.
- The old Dify repository, Docker volumes, integration patch, and v1.0/v1.1
  workflow DSL files remain retained and frozen until manual v2.0 acceptance
  completes and separate cleanup authorization is granted.
- v2.0 is documented as implementation / RC preparation, not Stable. No v2.0
  Stable tag exists or is authorized by this task.

## Runtime contract evidence

The approved plan proposed a RED test in which `dify_free` application startup
must not call Docker or Dify probes. The current implementation already
satisfied that contract before Task 3 changes:

- `RuntimeStatus.from_mode(RuntimeMode.DIFY_FREE)` uses the Python-primary
  branch and returns all three legacy dependency flags as false;
- application construction and startup contain no Docker/Dify probe boundary;
  and
- the controlled lifecycle tests make any Docker, Dify, or SSRF-proxy call from
  a default script fail immediately.

The unmodified runtime/lifecycle baseline therefore passed with `43 passed`.
No production change was needed, and no artificial RED was created. The actual
missing structural contract was an explicit assertion for the `DIFY_FREE`
status mapping. `test_dify_free_runtime_contract_has_no_legacy_dependencies`
was added and was GREEN on its first run alongside the default-mode assertion:
`2 passed`.

## Documentation changes

- `README.md` now leads with the Python-only v2.0 runtime contract, exact
  default and legacy launcher names, no-fallback policy, frozen legacy assets,
  and Not-Stable status.
- `docs/RESTORE_ON_NEW_PC.md` makes Docker optional for explicit legacy
  rollback, separates normal Python recovery from frozen Dify recovery, and
  gives exact daily start/stop/status commands.
- `docs/DIFY_ITERATION_PLAN.md` replaces the future-only v2.0 description with
  the current Python-native implementation / RC boundary and manual-acceptance
  gate.
- `docs/RELEASE_MATRIX.md` adds a v2.0 Not-Stable row with no default Dify DSL,
  plus explicit cutover, rollback, recovery, and Stable-tag rules.

## Verification

- Focused runtime and lifecycle tests: `44 passed`, with one pre-existing
  Starlette/httpx deprecation warning.
- Full suite: `586 passed`, with the same single pre-existing warning.
- `python -m ruff check src tests`: passed.
- `git diff --check`: passed.
- `dify/workflows/literature-search-v1.0.yml` compared with `dify-v1.0`: empty
  diff.
- `dify/workflows/literature-search-v1.1.yml` compared with `dify-v1.1`: empty
  diff.
- Dify and integration trees, `.env`, stable/protected content, and the
  unrelated untracked `.learnings/` directory were not changed.
- No service smoke or lifecycle mutation was run. Protected port-8000 v1.7 PID
  `37408` was not touched.

## Remaining acceptance boundary

Python-only manual acceptance is still required before v2.0 may become Stable.
Until that separate gate passes, the explicit legacy Dify rollback assets stay
frozen and retained; this documentation commit does not authorize deletion,
migration, a push, or a tag.
