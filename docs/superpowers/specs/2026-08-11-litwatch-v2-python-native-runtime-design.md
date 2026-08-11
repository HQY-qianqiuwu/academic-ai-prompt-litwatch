# LitWatch v2.0 Python-native Runtime Design

## Goal

Stack v2.0 makes Python the authoritative runtime for workflow orchestration and
semantic analysis while preserving every verified deterministic capability from
`dify-v1.7`. LitWatch must start, search, schedule, analyze, persist, recover,
and render without Docker Desktop, Dify, or the Dify SSRF proxy.

Migration order is replacement, parity verification, regression, cutover, and
only then removal of the Dify runtime dependency. Historical DSL and Stable tags
remain frozen.

## Scope

- Python application lifecycle and explicit runtime modes.
- Versioned, backed-up, transactional SQLite migrations with fail-closed startup.
- Local SQLite-backed background jobs.
- An OpenAI-compatible `LLMGateway` used by the existing `PaperAnalyzer`.
- A typed `PaperAnalysis` contract with explicit evidence scope.
- A focused refactor of the existing `Pipeline`, not a second pipeline engine.
- Cloud-egress consent, prompt-injection isolation, redaction, cost guards, and
  hardened PDF networking.
- Controlled `legacy -> dual -> python_default -> dify_free` migration.
- Dify-free lifecycle and release-candidate evidence.

## Non-goals

v2.0 does not implement a hybrid/vector knowledge base, general PDF acquisition,
institution-login automation, complete full-text reading, knowledge QA,
cross-paper synthesis, Research Gap, a generic workflow DSL, a visual DAG, a
distributed queue, or complete Zotero automation. Those capabilities retain
their assignments in `计划表.md`. No `litwatch-v2.0` Stable tag is created
automatically.

## Current architecture

- `LiteratureSearchService` already owns Provider selection, failure isolation,
  deduplication, ranking, and normalized `Paper` results.
- Provider Registry/Profile owns adapters, safe Base URLs, and write-only BYOK.
- SQLite owns papers, subscriptions, runs, deliveries, and Radar history.
- Subscription, Scheduler, Research Radar, FastAPI, Jinja2, and the Web UI are
  already Python implementations.
- `PaperAnalyzer` directly calls `/chat/completions` and returns a loose dict.
- `Pipeline` constructs Providers directly instead of reusing
  `LiteratureSearchService` and performs analysis synchronously.
- `Database` has numbered migrations but no mandatory backup, checksum,
  post-migration verification, or durable recovery record.
- long analysis operations have no persistent job queue.
- `FullTextExtractor` bounds bytes and checks PDF magic, but follows redirects
  without resolved-host validation.
- `start-local.ps1` is independent, while full-stack scripts, navigation links,
  and historical integration assets still assume Dify.

## Target architecture

```text
Browser / CLI / Scheduler
        -> FastAPI Python Runtime
        -> LiteratureSearchService -> Provider Registry -> Scholarly APIs
        -> Radar / Subscription / Weekly Digest
        -> JobService -> SQLite JobRepository -> JobWorker
                                                  -> existing Pipeline
                                                  -> PaperAnalyzer
                                                  -> LLMGateway
                                                  -> OpenAI-compatible Provider

SQLite authority:
papers | subscriptions | radars | runs | jobs | analyses | migration records
```

Python owns every business rule. HTML/CSS/browser JavaScript remain presentation
layers. External services are adapters and never authoritative state stores.

## Component disposition matrix

| Component | Disposition | v2.0 action |
|---|---|---|
| `PaperAnalyzer` | REFACTOR | Inject `LLMGateway`; return `PaperAnalysis`; retain extractive fallback. |
| `Pipeline` | REFACTOR | Reuse `LiteratureSearchService` and typed analysis steps. |
| `FullTextExtractor` | KEEP/HARDEN | Add URL, redirect, host, type, size, and timeout enforcement. |
| `ZoteroExporter` | KEEP/LEGACY ADAPTER | Preserve explicit CLI behavior outside core startup. |
| `LiteratureSearchService` | KEEP | Sole retrieval orchestration path. |
| Provider Registry/Profile/BYOK | KEEP | Continue secure adapter construction. |
| Dedup/ranking/canonical identity | KEEP | Remain deterministic and LLM-independent. |
| Radar/Subscription/Scheduler | KEEP | Preserve current persistence and scheduling semantics. |
| SQLite | KEEP/HARDEN | Add coordinator, backup, verification, jobs, and analyses. |
| FastAPI/Web UI | KEEP | Add job APIs/UI and remove required Dify navigation. |
| startup scripts | REPLACE DEFAULT | Python-only lifecycle becomes standard; legacy helpers are explicit. |
| Dify DSL | LEGACY/FROZEN | Keep v1.0/v1.1 byte-for-byte unchanged. |
| Dify runtime/SSRF proxy | REMOVE FROM CORE | Not started, checked, or required by default lifecycle. |

## Data flow

Deterministic discovery remains:

```text
request -> LiteratureSearchService -> Providers -> normalized Paper
        -> deterministic dedup -> deterministic ranking -> Python consumers
```

Analysis becomes:

```text
validated Paper + declared evidence scope
-> POST job (202 + job_id)
-> durable worker claim
-> Pipeline trusted instructions + untrusted evidence
-> PaperAnalyzer -> LLMGateway
-> PaperAnalysis validation
-> idempotent persistence -> completed result_ref
```

LLM output never overwrites canonical title, authors, venue, publication date,
DOI, URL, or PDF URL.

## Runtime lifecycle

`RuntimeMode` accepts `legacy`, `dual`, `python_default`, and `dify_free`.
Unknown values fail configuration. v2.0 defaults to `python_default`; release
acceptance explicitly uses `dify_free`.

Startup is fail-closed:

```text
Settings validation
-> DB inspection
-> backup and migration when required
-> integrity verification
-> service construction
-> stale migration/run/job recovery
-> JobWorker start
-> Scheduler start
-> ready
```

Shutdown rejects new jobs, signals worker and scheduler, waits a bounded period,
leaves unfinished jobs recoverable, closes HTTP clients, and closes SQLite.

## Database migration strategy

`MigrationCoordinator` provides:

```python
class MigrationCoordinator:
    def inspect(self) -> MigrationState: ...
    def migrate(self) -> MigrationReport: ...
    def verify(self) -> MigrationVerification: ...
    def recover(self, backup_path: Path) -> MigrationVerification: ...
```

Pending migrations first use SQLite's backup API to create a timestamped sibling
under `data/backups/`. Each migration is a single `BEGIN IMMEDIATE` transaction.
The registry stores version, name, checksum, timestamps, and status; an applied
checksum mismatch fails startup. Verification runs `foreign_key_check`,
`integrity_check`, expected-version, and required-object checks. Failure rolls
back and prevents service startup. Recovery verifies a temporary restored copy
before an atomic same-volume replacement. Tests rehearse migration and recovery
on a copied v1.7 database, never live user data.

## Job Runtime

`JobRecord` stores `job_id`, `job_type`, `idempotency_key`, status, creation/
start/finish/heartbeat timestamps, attempt/max attempts, timeout, input hash,
JSON payload, result reference, safe error code/message, cancellation timestamp,
and lease owner/expiry. Status is one of `queued`, `running`, `completed`,
`failed`, or `cancelled`.

`JobRepository` atomically enqueues or returns the existing
`(job_type, idempotency_key)` job, claims work under a lease, heartbeats,
finishes, requests cancellation, retries bounded failures, and recovers stale
work. `JobWorker` enforces global and LLM concurrency. Cancellation is
cooperative at step boundaries. Timeout records `timeout` outside the FastAPI
request lifecycle.

- `POST /api/v2/jobs` returns HTTP 202 with `job_id`, status, and `status_url`.
- `GET /api/v2/jobs/{job_id}` returns safe status and result reference.
- `POST /api/v2/jobs/{job_id}/cancel` is idempotent.

Expired running jobs are requeued when attempts remain and otherwise fail with
`restart_recovery_exhausted`.

## LLM Gateway

```python
class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...

class LLMGateway:
    def complete_structured(
        self,
        request: LLMRequest,
        response_model: type[BaseModel],
        budget: LLMBudget,
    ) -> LLMResult: ...
```

`OpenAICompatibleProvider` uses injected `httpx.Client`, model, Base URL, and
write-only key. It has finite retries for timeout, 429, and 5xx; normalizes
authentication, rate-limit, timeout, upstream, parse, and validation errors;
captures usage/cost metadata; and never logs headers or credentials.

`LLMRequest` separates trusted system instructions from
`untrusted_evidence`. `DataEgressPolicy` requires explicit cloud consent and
allows metadata/abstract by default. Full text requires a separate opt-in.

## Pipeline Runtime

The existing `Pipeline` remains the only implementation:

```text
validate_paper
-> prepare_analysis_input
-> analyze_with_gateway or extractive fallback
-> validate_paper_analysis
-> persist_paper_analysis
```

Typed step state records safe trace entries. Retry belongs to Gateway/Job
Runtime, not duplicated inside Pipeline. Analysis persistence is idempotent by
`(canonical_id, analysis_version, evidence_hash, model_config_hash)`.
`Pipeline.run()` remains a compatibility adapter but delegates retrieval to
`LiteratureSearchService` and analysis to the typed pipeline/job services.

## Structured AI contracts

`PaperAnalysis` contains nullable `research_question` and `motivation`; lists
for `methods`, `key_modules`, `baselines`, `datasets`, `experimental_setup`,
`metrics`, `main_results`, `contributions`, `limitations`, and `future_work`;
typed `evidence`; an `evidence_scope` of `metadata_only`, `abstract`,
`fulltext_excerpt`, or `fulltext`; and a status of `completed`, `extractive`,
`skipped`, or `failed`.

Evidence records field, bounded excerpt, scope, and optional section/page
locator. Missing scalar facts use `None`; missing list facts use `[]`; UI labels
them `unknown`/`not_available`. Unknown response fields are rejected.

## Security boundaries

- Providers are classified `local` or `cloud`; cloud calls require explicit
  egress consent. Full text and notes require separate consent and size limits.
- Titles, abstracts, PDFs, Web metadata, and notes are untrusted data and never
  gain system-instruction authority.
- API keys, Authorization, Cookie, tokens, credentials, and sensitive headers
  are redacted before errors/traces persist. Job payloads store references only.
- Settings enforce `max_tokens_per_job`, `max_cost_per_job`, `max_daily_cost`,
  and `max_concurrent_llm_jobs` before a model call.
- PDF fetch accepts HTTPS by default, rejects credentials and unsafe resolved
  addresses on every redirect, and bounds redirects, timeout, content type,
  content length, streamed bytes, and PDF signature.

## Dify migration lifecycle

1. **LEGACY** keeps frozen DSL and integration assets as references.
2. **DUAL** exposes Python jobs and explicit comparison without silent duplicate
   execution.
3. **PYTHON DEFAULT** routes Web/API/CLI to Python; legacy is opt-in with a
   deprecation warning.
4. **DIFY FREE** removes Docker, Dify, and `ssrf_proxy` from default startup,
   health, navigation, and release tests while preserving historical assets.

## Rollback strategy

Every task is an independent commit. Historical tags and DSL remain immutable.
Schema changes require a verified backup. Migration failure blocks startup and
reports a safe recovery command. Before final cutover, an explicit runtime mode
can select the compatibility path without rewriting state. Release rollback is
the immutable `dify-v1.7` tag.

## Testing strategy

All behavior changes use RED -> GREEN -> REFACTOR. Tests cover migration plans,
backups, integrity, recovery, job state transitions, idempotency, cancellation,
timeout, retries, concurrency, budgets, redaction, structured validation,
pipeline steps, temporary SQLite integration, FastAPI job contracts, restart,
v1.7 database-copy migration, controlled network/DNS boundaries, and existing
Search, Provider Settings, Radar, Subscription, Scheduler, Digest, deduplication,
zh-CN, and English behavior.

Final gates are `python -m pytest -q`, `ruff check src tests`,
`git diff --check`, `git fsck --full`, and stable DSL comparisons.

## v2.0 Stable acceptance criteria

- Core startup/shutdown passes without Docker, Dify, or `ssrf_proxy`.
- Search, Provider Settings, Radar, Subscription, Scheduler, Digest, historical
  deduplication, zh-CN, and English pass.
- migration versioning, backup, transaction, verification, rollback, and
  recovery rehearsal pass.
- jobs pass idempotency, cancellation, timeout, retry, concurrency, restart,
  and stale-running recovery.
- `PaperAnalyzer` uses `LLMGateway`; `Pipeline` is the only analysis pipeline;
  persisted output validates as `PaperAnalysis`.
- egress, injection, redaction, cost, and PDF/network controls pass.
- v1.0/v1.1 DSL and every `dify-v1.x` tag remain unchanged.
- the feature branch is pushed to `private-backup`.
- `litwatch-v2.0` remains absent pending manual acceptance.

