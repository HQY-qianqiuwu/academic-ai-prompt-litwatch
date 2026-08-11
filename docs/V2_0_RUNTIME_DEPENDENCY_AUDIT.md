# LitWatch v2.0 Runtime Dependency Audit

## Scope and boundary

This audit freezes the Stack v1.7 dependency surface before the Python-native
runtime migration. The v2.0 implementation branch is based on the `dify-v1.7`
release lineage; the historic Dify workflow DSL files and all `dify-v1.x` tags
remain release artifacts and are not migration inputs to overwrite, move, or
delete.

The audit distinguishes a **legacy integration dependency** from a **core
runtime dependency**. Existing Python search, Radar, subscription, scheduler,
database, and web behavior remains present. `RuntimeStatus` reports the mode's
declared requirements only; it does not probe Dify, Docker, or a proxy.

## Frozen Dify and Docker dependencies

| Area | v1.7 dependency | Current location | v2.0 boundary |
|---|---|---|---|
| Dify workflow | The compatible HTTP workflow contract is retained in versioned release artifacts. | `dify/workflows/literature-search-v1.0.yml`, `dify/workflows/literature-search-v1.1.yml` | Frozen; do not modify, move, or delete. |
| Stack lifecycle | The full-stack start path starts Docker Desktop when needed, runs `docker compose up -d` in Dify, waits for `http://localhost`, and requires `ssrf_proxy`. | `scripts/start-stack.ps1`, `scripts/stack-common.ps1` | Legacy-only after cutover; it remains available for rollback. |
| Stack shutdown/status | Stop and status resolve the Dify compose directory and inspect Docker/Dify/`ssrf_proxy`. | `scripts/stop-stack.ps1`, `scripts/status-stack.ps1`, `scripts/stack-common.ps1` | Legacy-only after cutover. |
| Dify network smoke | A Dify worker container calls the LitWatch API through `host.docker.internal:8000`; the check is optional with `-SkipDocker`. | `scripts/smoke-v1.1.ps1` | Historical compatibility evidence, not a Python-default requirement. |
| SSRF integration | A version-locked Dify 1.16.1 patch permits only `host.docker.internal:8000` and can recreate `ssrf_proxy`. | `scripts/apply-dify-ssrf-integration.ps1`, `integrations/dify/1.16.1/litwatch-ssrf.patch`, `docs/DIFY_SSRF_INTEGRATION.md` | Frozen legacy integration; never broaden its allowlist. |
| Local Python launch | LitWatch can be started/stopped without the Dify stack through its local scripts. | `scripts/start-local.ps1`, `scripts/stop-local.ps1`, `scripts/run-weekly.ps1` | Foundation for Python-primary lifecycle. |

`src/litwatch/provider_security.py` is a separate Python SSRF defense for
user-configurable provider endpoints. It is retained in every mode and is not
the Dify `ssrf_proxy` dependency reported by `RuntimeStatus`.

## Environment and credential dependencies

`Settings` loads `LITWATCH_` environment values from `.env` by default. The
committed `.env.example` contains placeholders only; `.env`, provider keys,
SMTP passwords, and Zotero keys remain uncommitted.

| Configuration group | Settings / environment values | Runtime use |
|---|---|---|
| Runtime | `LITWATCH_RUNTIME_MODE` | Selects `legacy`, `dual`, `python_default`, or `dify_free`; defaults to `python_default`. |
| Provider connectivity | `LITWATCH_OPENALEX_EMAIL`, `LITWATCH_OPENALEX_BASE_URL`, `LITWATCH_SEMANTIC_SCHOLAR_API_KEY`, `LITWATCH_SEMANTIC_SCHOLAR_BASE_URL`, `LITWATCH_SEMANTIC_SCHOLAR_ANONYMOUS`, `LITWATCH_ARXIV_BASE_URL`, `LITWATCH_CROSSREF_BASE_URL`, `LITWATCH_CROSSREF_EMAIL`, `LITWATCH_IEEE_XPLORE_API_KEY` | Provider registry/source construction; external metadata still comes from real APIs. |
| Analysis | `LITWATCH_LLM_API_KEY`, `LITWATCH_LLM_BASE_URL`, `LITWATCH_LLM_MODEL` | Optional `PaperAnalyzer` model request; no key selects deterministic extractive fallback. |
| Delivery | `LITWATCH_SMTP_HOST`, `LITWATCH_SMTP_PORT`, `LITWATCH_SMTP_USERNAME`, `LITWATCH_SMTP_PASSWORD`, `LITWATCH_EMAIL_FROM`, `LITWATCH_EMAIL_TO` | Optional email digest delivery. |
| Zotero | `LITWATCH_ZOTERO_USER_ID`, `LITWATCH_ZOTERO_API_KEY` | Explicit Zotero export adapter. |
| Local persistence and limits | `LITWATCH_DATABASE_PATH`, `LITWATCH_TOPICS_PATH`, `LITWATCH_LOOKBACK_DAYS`, `LITWATCH_MAX_RESULTS_PER_SOURCE`, `LITWATCH_ANALYZE_TOP_N`, `LITWATCH_FULLTEXT_TOP_N` | SQLite, topic loading, retrieval, and analysis limits. |

The provider credential store layers write-only runtime profile values over
environment fallback values in `src/litwatch/sources/registry.py`. That is a
Python credential boundary and remains independent of Dify.

## Python lifecycle dependencies

`create_app()` in `src/litwatch/web.py` creates the database, provider registry,
`LiteratureSearchService`, subscriptions, deliveries, Radar services, and
`SchedulerService`. Its FastAPI lifespan recovers stale Radar scans, starts the
scheduler, then stops it and closes SQLite on shutdown. Task 2 moves this
ownership into `ApplicationRuntime`; Task 1 does not alter lifecycle behavior.

## Pipeline and Analyzer dependencies

| Component | Current v1.7 dependency | Boundary for later v2.0 work |
|---|---|---|
| CLI | `litwatch.cli` invokes `Pipeline(settings).run()` for a scheduled/manual run. | Preserve public behavior while the pipeline is refactored. |
| `Pipeline` | Directly constructs OpenAlex/arXiv and optional Semantic Scholar sources, `Database`, `PaperAnalyzer`, and `FullTextExtractor`; it retrieves, deduplicates, ranks, analyzes, and persists synchronously. | Keep one pipeline, then delegate retrieval through `LiteratureSearchService` and typed job/analysis steps. |
| `PaperAnalyzer` | Uses `httpx` directly against the configured OpenAI-compatible `/chat/completions` endpoint, retries HTTP 429, reads analysis modes, and returns a loose dictionary. | Later inject `LLMGateway`, retain the extractive no-key fallback, and introduce a typed analysis contract. |
| Full text | `Pipeline` asks `FullTextExtractor` only for enabled analysis and a paper PDF URL. | Later harden networking while retaining bounded optional extraction. |

## Runtime-mode declaration

| Mode | Python primary | Requires Dify | Requires Docker | Requires Dify SSRF proxy |
|---|---:|---:|---:|---:|
| `legacy` | no | yes | yes | yes |
| `dual` | yes | yes | yes | yes |
| `python_default` | yes | no | no | no |
| `dify_free` | yes | no | no | no |

`legacy` preserves the previous full-stack expectation. `dual` supports an
explicit migration comparison without silently duplicating work. The v2.0
default is `python_default`; `dify_free` is the explicit final acceptance mode.
No mode removes historic assets in this task.
