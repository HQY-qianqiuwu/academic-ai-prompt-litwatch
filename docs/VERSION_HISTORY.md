# Version History

## Version Naming

Headings in this file are **Stack / System Release** versions. They describe the
combined system and do not imply that the Dify Workflow DSL has the same version.
Backend-only releases may reuse an older compatible workflow. The exact mapping
is recorded in `docs/RELEASE_MATRIX.md`.

## Stack v1.0

Status: Stable Baseline

Architecture:

```text
Dify -> OpenAlex
```

Features:

- User-defined research topic
- Direct OpenAlex literature search
- Title, author, year, venue, DOI, URL, and abstract extraction
- JSON output

Dify Workflow:

`dify/workflows/literature-search-v1.0.yml`

Stable tag: `dify-v1.0`

## Stack v1.1

Status: Stable

Architecture:

```text
Dify -> LitWatch API -> LiteratureSearchService -> OpenAlex
```

Features:

- Unified `POST /api/v1/literature/search` endpoint
- Provider-backed normalized `Paper` response
- Explicit 422, 502, and 504 error boundaries
- Offline API contract tests
- Docker Desktop access through `host.docker.internal:8000`

Dify Workflow:

`dify/workflows/literature-search-v1.1.yml`

Stable tag: `dify-v1.1`

Validation record: `docs/V1_1_E2E_RESULTS.md`

## Stack v1.2

Status: Stable

Architecture:

```text
Dify
    -> LitWatch API
    -> Provider Configuration Layer
    -> Provider Registry
    -> OpenAlex
```

Backend additions:

- Provider configuration and profile models
- Provider registry separated from `LiteratureSearchService`
- Provider enable/disable state
- Configurable OpenAlex base URL
- Optional `providers` search parameter
- BYOK credential-reference architecture
- Redacted profile and validation responses
- Process-local credential submission without JSON or SQLite persistence
- Backward compatibility with the v1.1 `topic + limit` request

System integration additions:

- Idempotent local lifecycle management for Docker, Dify, LitWatch, Provider
  Registry, OpenAlex, and the SSRF proxy
- Recoverable Dify 1.16.1 Squid integration restricted to
  `host.docker.internal:8000`
- Safe port-owner inspection and Docker-volume-preserving stop behavior

Dify Workflow:

`dify/workflows/literature-search-v1.1.yml` (compatible reuse)

Provider state:

- OpenAlex: runnable
- Semantic Scholar: non-runnable capability declaration
- arXiv: non-runnable capability declaration
- Crossref: non-runnable capability declaration
- IEEE Xplore: non-runnable capability declaration
- Scopus: non-runnable capability declaration
- Web of Science: non-runnable capability declaration

Validation state:

- Backend, Provider Registry, real OpenAlex, profile, credential-redaction, and
  Docker-to-host checks: pass
- Dify import, backward-compatible workflow, and dynamic-topic runs: pass
- Dify SSRF allow target and blocked regression targets: pass
- Cold start, warm start, safe stop, restart, and idempotency: pass
- Tests: 58 passed; Ruff: pass
- Stable v1.0 and v1.1 DSL protection: pass
- `literature-search-v1.2.yml`: intentionally absent
- Stable tag: `dify-v1.2`

Architecture record: `docs/V1_2_PROVIDER_CONFIGURATION.md`

Validation record: `docs/V1_2_E2E_RESULTS.md`

## Stack v1.3

Status: Stable

Architecture:

```text
Dify
    -> LitWatch API
    -> LiteratureSearchService
    -> Provider Registry
       |-- OpenAlex
       |-- Semantic Scholar
       |-- arXiv
       `-- Crossref
    -> Deterministic round-robin aggregation
    -> Provider status diagnostics
```

Backend additions:

- Runnable OpenAlex, Semantic Scholar, arXiv, and Crossref adapters
- Explicit multi-provider search selection
- Per-provider success, empty, timeout, rate-limit, authentication, upstream,
  and parse diagnostics
- Failure isolation and successful partial-result responses
- Deterministic round-robin aggregation with duplicates intentionally preserved
- Secure known-provider base URL overrides
- Environment and process-memory Provider Profile BYOK
- Profile secret over environment secret over anonymous precedence
- HTTPS, DNS/IP, redirect, and credential-redaction protections

Dify Workflow:

`dify/workflows/literature-search-v1.1.yml` (compatible reuse)

Validation state:

- OpenAlex, arXiv, and Crossref real E2E: pass
- Semantic Scholar anonymous access: upstream rate limited HTTP 429
- Semantic Scholar rate-limit isolation: pass
- Semantic Scholar environment and profile BYOK paths: pass by tests
- Semantic Scholar authenticated real success: **not verified**
- Four-provider HTTP 200 and partial failure handling: pass
- Dynamic-topic API and Dify UI runs: pass
- Dify Topic A and Topic B: workflow success, non-empty results, clearly
  different paper sets
- Tests: 143 passed; Ruff and `git diff --check`: pass
- Stable v1.0 and v1.1 DSL protection: pass
- `literature-search-v1.3.yml`: intentionally absent
- Stable tag: `dify-v1.3`

BYOK record: `docs/V1_3_PROVIDER_BYOK.md`

Validation record: `docs/V1_3_E2E_RESULTS.md`

## Stack v1.4

Status: Stable

Architecture:

```text
Provider retrieval
    -> bounded candidate pool
    -> DOI / canonical-ID / title deduplication
    -> deterministic metadata merge
    -> query relevance scoring
    -> metadata quality scoring
    -> stable final ranking
    -> response limit
```

Backend additions:

- Canonical DOI normalization and conservative title matching
- Input-order-independent duplicate grouping and metadata merge
- Sorted union of contributing Provider provenance
- Title-dominant deterministic query relevance scoring
- Real-metadata-only quality scoring
- Relevance-dominant final score and explicit stable tie-break rules
- Per-Provider candidate budget `min(50, 2 * final_limit)`
- Limit-after-dedup semantics
- Additive raw, deduplicated, removed, budget, and ranking diagnostics
- Existing Provider failure isolation retained through ranking

Dify Workflow:

`dify/workflows/literature-search-v1.1.yml` (compatible reuse)

Automated validation state:

- OpenAlex, arXiv, and Crossref real E2E: pass
- Semantic Scholar anonymous access: upstream rate limited HTTP 429
- Semantic Scholar partial-failure isolation: pass
- Semantic Scholar environment and Profile BYOK paths: pass by tests
- Semantic Scholar authenticated real success: **not verified**
- TDOA real search: 60 raw, 57 deduplicated, 3 removed
- TDOA cross-source OpenAlex/Crossref merge: pass
- OFDM real search: 60 raw, 60 deduplicated
- Topic-specific top-result ranking: automated checks pass
- Dify Worker -> SSRF Proxy -> LitWatch: HTTP 200
- Tests: 164 passed; Ruff and `git diff --check`: pass
- Stable v1.0 and v1.1 DSL protection: pass
- `literature-search-v1.4.yml`: intentionally absent
- Manual TDOA, OFDM, and dynamic ranking: pass
- Manual deduplication: 60 raw, 57 unique, 3 removed
- Final duplicate DOI count: 0
- Manual multi-source merge: pass
- Dify Topic A and Topic B: pass
- Stable tag: `dify-v1.4`

Architecture record: `docs/V1_4_DEDUP_RANKING.md`

Validation record: `docs/V1_4_E2E_RESULTS.md`

## Stack v1.5

Status: **Stable**

Architecture:

```text
Browser
    -> LitWatch FastAPI / Jinja2 / vanilla JavaScript UI
    -> POST /api/v1/literature/search
    -> LiteratureSearchService
    -> Providers -> deduplication -> ranking
```

Web additions:

- Local research search page at `/`
- Dynamic Provider selection from the Provider Registry API
- Backend-ordered paper cards with real metadata, sources, and score diagnostics
- Raw, unique, and removed-duplicate summary
- Per-Provider success, empty, rate-limit, authentication, timeout, upstream,
  and parse status display
- Partial-failure results with safe retry messages
- Provider Settings backed by the existing Profile APIs
- Write-only BYOK replacement and explicit clear semantics
- Responsive local UI, accessible labels, focus states, and navigation
- Existing database/weekly Dashboard preserved at `/dashboard`

Dify Workflow:

`dify/workflows/literature-search-v1.1.yml` (compatible reuse)

Validation state:

- TDOA and OFDM real browser searches: pass
- Dynamic topic result difference: pass
- TDOA dedup UI: 60 raw, 57 unique, 3 removed
- Multi-source source badge: pass
- Semantic Scholar anonymous HTTP 429 partial-failure UI: pass
- Semantic Scholar authenticated real success: **not verified**
- Fake-secret save, redaction, and cleanup: pass
- Responsive no-overflow check: pass
- Stable v1.0 and v1.1 DSL protection: pass
- Manual TDOA search, paper cards, ranking display, source merge, partial
  failure UX, and Provider Settings acceptance: pass
- Stable tag: `dify-v1.5`

Design record: `docs/V1_5_WEB_UI.md`

Validation record: `docs/V1_5_E2E_RESULTS.md`
