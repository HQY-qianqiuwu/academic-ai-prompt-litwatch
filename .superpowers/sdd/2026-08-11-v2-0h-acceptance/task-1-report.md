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

## Review fix: real search composition

The review correctly identified that the first `ScriptedSearch` fixture
replaced the complete search service. Although downstream services were real,
that fixture bypassed Provider registry/profile selection and the production
aggregation, deduplication, ranking, and failure-isolation path.

TDD evidence:

- RED: `python -m pytest -q tests/test_v2_acceptance.py -x` failed because
  `app.state.literature_search_service` was `ScriptedSearch`, not
  `LiteratureSearchService`.
- GREEN: the fake moved to the injectable `PaperSource`/Provider factory
  boundary. FastAPI Manual Search, SubscriptionRunService, SchedulerService,
  and ResearchRadarService now reference the same real
  `LiteratureSearchService` and active Provider profile.
- Focused search/config/feature gate: `117 passed`, with the existing warning.
- Final revised acceptance gate: `5 passed`, with the existing warning.
- Final full suite: `591 passed`, with the existing warning.

While strengthening the stored-profile assertion, one intermediate run errored
because the test reused `profiles` for an HTTP response and shadowed the real
`ProviderProfileStore`. Renaming the response variable fixed that test-only
setup error; it did not expose or require a product change.

The revised acceptance test also:

- proves three raw multi-provider papers deduplicate to two ranked results;
- proves a Semantic Scholar HTTP 429 is isolated while OpenAlex results remain;
- posts a sentinel credential through the real Provider Settings API, resolves
  it from the process-local profile credential store during Provider source
  construction, and asserts it is absent from API, rendered HTML, and static
  UI projections; and
- uses no `.env`, network, process, port, or production-code change.

The review fix will be committed separately with only the acceptance test,
evidence document, and this appended report staged explicitly.
