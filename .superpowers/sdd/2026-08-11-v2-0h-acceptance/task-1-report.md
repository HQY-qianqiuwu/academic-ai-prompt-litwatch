# Task 1 Report: Automated Dify-free acceptance gate

## Outcome

- Added `tests/test_v2_acceptance.py` with five deterministic cross-feature
  acceptance tests covering every seam listed in the Task 1 brief.
- Added `docs/V2_0_E2E_RESULTS.md` with the runtime-health snapshot, exact gate
  commands and counts, focused-test references, deterministic/real boundary,
  known warning, protected v1.7 port conflict, and remaining Task 2/manual
  acceptance work.
- No production file changed. The new acceptance suite passed on its first run,
  so there was no earlier-owner production failure to route and no artificial
  RED was created.
- Status remains **RELEASE CANDIDATE PREPARATION — NOT STABLE**.

## Composition boundary

The tests use production FastAPI/lifespan, SQLite, migrations, repositories,
Search API projection, Provider Settings projection, subscription runs,
historical deduplication, Scheduler, dashboard digest delivery, Radar,
`LLMGateway`, `PaperAnalyzer`, `PaperAnalysisService`, usage ledger, durable
JobWorker, backup/recovery, templates, and localization assets.

Deterministic replacements are limited to external literature results,
structured LLM-provider output, clocks, and identifiers. No real network,
listening port, launcher, service process, Docker, Dify, or SSRF proxy was used.

## TDD evidence

- Focused pre-change baseline: `132 passed`, with one existing warning.
- The acceptance tests were written before any production change.
- First acceptance run: `5 passed`, with the same warning.
- A later Provider Settings POST assertion had one test-owned RED because a
  substring check treated the safe `requires_api_key` field as a raw secret
  key. Exact response-key validation fixed the test; no production change was
  made.
- Final acceptance run: `5 passed`, with the same warning.
- Because the current production contracts already satisfied the new
  cross-component assertions, there was no honest product RED and no production
  patch was required.

## Verification

- `python -m pytest -q tests/test_v2_acceptance.py`: `5 passed`.
- `python -m pytest -q`: `591 passed`.
- `ruff check src tests`: passed.
- `git diff --check`: passed.
- `git fsck --no-dangling`: passed.
- v1.0 DSL comparison against `dify-v1.0`: empty.
- v1.1 DSL comparison against `dify-v1.1`: empty.
- The only warning is the existing Starlette/httpx `TestClient` deprecation
  warning.

## Safety and scope

- PID `37408` and port `8000` were not inspected or touched.
- Dify/DSL, `.env`, stable/protected content, and `.learnings/` were not
  changed or staged.
- No push or tag was performed.
- The intended commit is `test(v2.0): add Dify-free acceptance gate`, with
  explicit staging of only the acceptance test, evidence document, and this
  report.

## Remaining boundary

Real lifecycle, port, provider-network, copied-v1.7 migration, and restart
smoke remain Task 2/manual acceptance work. They must preserve the protected
v1.7 owner, retain the frozen legacy rollback assets, and keep v2.0 Not Stable
until acceptance is complete.
