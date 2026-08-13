# LitWatch v2.0 Dify-free Acceptance Evidence

## Release status

**RELEASE CANDIDATE PREPARATION — NOT STABLE**

This document records the automated Task 1 gate only. It proves that the
approved core capabilities compose inside the Python runtime without a
Docker, Dify, Compose, SSRF-proxy, real-network, real-process, or real-port
readiness dependency. It does not replace the Task 2 lifecycle and migration
rehearsal or final manual acceptance, and it does not authorize a v2.0 Stable
tag.

## Automated acceptance result

`tests/test_v2_acceptance.py` contains five cross-feature acceptance tests:

1. A real FastAPI lifespan starts in `dify_free` mode and exposes live
   migration, runtime, JobWorker, and Scheduler health. The same application
   serves Manual Search through the production registry/profile-backed
   `LiteratureSearchService`, stores a write-only Provider Settings credential,
   and serves zh-CN/English navigation. Multi-provider results exercise
   aggregation, DOI deduplication, deterministic ranking, and HTTP 429 failure
   isolation.
2. Real subscription, historical-paper, run, scheduler, dashboard-delivery,
   and Radar services share one isolated SQLite database and the exact same
   production `LiteratureSearchService` instance/configuration path used by
   the Manual Search API. Repeated and scheduled runs remove historical
   duplicates, generate a weekly digest, and survive a database reopen
   alongside Radar history.
3. Structured Paper Analysis passes through the real `LLMGateway`,
   `PaperAnalyzer`, `PaperAnalysisService`, usage ledger, and
   `AnalysisRepository`, then reuses the persisted analysis on an identical
   request.
4. The real durable job repository and worker prove enqueue idempotency,
   completion, cancellation, normalized timeout failure, and stale-lease
   restart recovery.
5. The real migration coordinator verifies SQLite, creates a pending-migration
   backup, restores that backup, and rejects an invalid backup without
   replacing valid data.

The new acceptance file was run immediately after it was added and passed on
its first run: `5 passed`. No earlier-owner product contract failed, so no
production boundary was changed and no artificial RED was created.

During final tightening, a Provider Settings POST assertion produced one
test-owned RED because the substring `api_key` also matches the safe schema
field `requires_api_key`. The response structure matched the existing focused
contract; the assertion was corrected to reject only an exact raw `api_key`
key. The final acceptance run returned `5 passed`. This was not a production
failure and no runtime behavior was weakened or changed.

Review then identified that the original literature fixture replaced the
whole search service and therefore did not prove its internal seams. A new
regression requiring FastAPI, Subscription, Scheduler, and Radar to hold a
real shared `LiteratureSearchService` failed against that fixture, as expected.
The fixture was replaced at the injectable `PaperSource`/Provider factory
boundary only. The production search implementation now remains in every
acceptance path; no production change was required.

## Runtime health contract

The in-process FastAPI acceptance run returned these live fields while its
lifespan was active:

| Field | Observed value |
|---|---:|
| `mode` | `dify_free` |
| `python_primary` | `true` |
| `requires_dify` | `false` |
| `requires_docker` | `false` |
| `requires_ssrf_proxy` | `false` |
| `migration_verified` | `true` |
| `runtime_started` | `true` |
| `job_worker_running` | `true` |
| `job_worker_active` | `0` |
| `scheduler_running` | `true` |
| `scheduler_last_error` | `null` |

These are production runtime and component state fields. They are not
constants fabricated by the acceptance fixture.

## Real and deterministic boundaries

The automated gate uses the production FastAPI routes and lifespan, SQLite
schema and migrations, Provider registry/profile/credential selection,
`LiteratureSearchService`, aggregation, deduplication, ranking, failure
classification, repositories, subscription and Radar services, scheduler,
weekly digest delivery, structured-analysis gateway/service, usage ledger,
durable job worker, templates, static localization, backup, and recovery
implementation.

Only external nondeterminism is replaced:

- deterministic `PaperSource` objects replace only external Provider I/O and
  return source-native `Paper` lists or a controlled Provider exception. The
  real registry builds those sources from the active profile, the real
  `LiteratureSearchService` invokes them and constructs
  `LiteratureSearchResult`, and no provider adapter opens the network;
- the structured LLM provider returns deterministic schema-valid JSON while
  the real gateway, policy, ledger, analyzer, service, and repository remain
  in the path; and
- a fixed current date and explicit scheduler due time remove date-dependent
  nondeterminism without replacing scheduling behavior.

Provider Settings posts a test-only sentinel credential through the real
write-only API into the process-local `InMemoryCredentialStore`. The active
profile is then used to build the Semantic Scholar fake source, proving
credential resolution. API responses, the server-rendered Provider Settings
page and navigation pages, and the Provider Settings/localization JavaScript
are all asserted not to contain the sentinel or a raw `api_key` response
field. No `.env` file is used.

The job acceptance handler is deterministic and secret-free. The acceptance
timeout path raises `TimeoutError` through the real worker normalization path;
the elapsed watchdog and no-duplicate physical-attempt behavior remain covered
by `tests/test_job_worker.py`.

`TestClient` runs the ASGI application in-process. Task 1 opened no listening
socket, made no real HTTP request, launched no service process, and inspected
or changed no real port owner.

## Focused contract references

The acceptance layer intentionally does not duplicate every unit assertion.
Detailed boundaries remain covered by:

- runtime and live health: `tests/test_runtime.py`;
- Manual Search and Provider Settings: `tests/test_literature_search_api.py`,
  `tests/test_provider_config.py`, and `tests/test_provider_settings_ui.py`;
- Radar persistence/backfill/analysis/API: `tests/test_radars.py`,
  `tests/test_radar_backfill.py`, `tests/test_radar_analysis.py`, and
  `tests/test_radar_web.py`;
- subscriptions, scheduler, digest, and historical deduplication:
  `tests/test_subscriptions.py`, `tests/test_subscription_runs.py`,
  `tests/test_scheduler.py`, `tests/test_delivery.py`, and
  `tests/test_historical_papers.py`;
- structured analysis and the LLM gateway: `tests/test_llm_gateway.py`,
  `tests/test_paper_analyzer.py`, `tests/test_paper_analysis.py`, and
  `tests/test_paper_analysis_api.py`;
- durable jobs: `tests/test_jobs.py`, `tests/test_job_worker.py`, and
  `tests/test_job_api.py`;
- migration, backup, and recovery safety: `tests/test_database_migrations.py`;
  and
- zh-CN/English pages and navigation: `tests/test_ui_localization.py` and
  `tests/test_local_ui_navigation.py`.

## Exact automated commands and results

Focused pre-acceptance baseline:

```powershell
python -m pytest -q tests/test_runtime.py tests/test_literature_search_api.py tests/test_radars.py tests/test_subscription_runs.py tests/test_scheduler.py tests/test_paper_analysis_api.py tests/test_jobs.py tests/test_database_migrations.py tests/test_ui_localization.py
```

Result: `132 passed, 1 warning in 13.27s`.

New acceptance gate:

```powershell
python -m pytest -q tests/test_v2_acceptance.py
```

Initial result: `5 passed, 1 warning in 1.68s`.

Final result after the exact Provider Settings response-key assertion:
`5 passed, 1 warning in 1.35s`.

Review-fix RED:

```powershell
python -m pytest -q tests/test_v2_acceptance.py -x
```

Result: `1 failed`; FastAPI held the whole-service `ScriptedSearch` fixture,
not a production `LiteratureSearchService`. This was the intended review
regression failure.

Review-fix focused GREEN:

```powershell
python -m pytest -q tests/test_v2_acceptance.py tests/test_literature_search_service.py tests/test_literature_search_api.py tests/test_provider_config.py tests/test_provider_registry.py tests/test_provider_settings_ui.py tests/test_subscription_runs.py tests/test_scheduler.py tests/test_radar_backfill.py tests/test_radar_web.py
```

Result: `117 passed, 1 warning in 7.76s`.

Final revised acceptance result: `5 passed, 1 warning in 1.48s`.

Full suite:

```powershell
python -m pytest -q
```

Final review-fix result: `591 passed, 1 warning in 92.44s`.

Static and repository gates:

```powershell
ruff check src tests
git diff --check
git fsck --no-dangling
git diff --exit-code dify-v1.0 -- dify/workflows/literature-search-v1.0.yml
git diff --exit-code dify-v1.1 -- dify/workflows/literature-search-v1.1.yml
```

Result: all commands exited `0`; Ruff reported `All checks passed!`; both
stable DSL comparisons were empty.

## Known warning and protected local conflict

Pytest reports one existing `StarletteDeprecationWarning`: Starlette's current
`TestClient` integration says the installed `httpx` should eventually move to
`httpx2`. It does not fail or weaken this acceptance gate.

Per the protected task context, local port `8000` remains associated with the
v1.7 owner process PID `37408`. Task 1 did not inspect, signal, stop, or replace
that process and did not attempt a real port smoke. Any later real lifecycle
test must continue to fail closed rather than stopping an unknown or protected
owner.

## Remaining Task 2 and manual acceptance

Task 2 must still provide real, isolated evidence for:

- copied-v1.7 database migration, integrity, backup, failed-migration rollback,
  and recovery count/hash preservation;
- cold start, warm start, status, safe stop, and restart through the real
  Python lifecycle;
- real OpenAlex TDOA search without Dify/Docker readiness;
- persisted Radar and subscription behavior across a real restart; and
- one locally safe or explicitly authorized external-model analysis path.

Until those rehearsals and final manual acceptance complete, the historical
Dify repository, volumes, integration assets, and stable v1.0/v1.1 DSL files
remain frozen rollback assets and v2.0 remains Not Stable.
