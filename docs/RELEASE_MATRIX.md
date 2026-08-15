# Release Matrix

## Purpose

This matrix separates the complete Stack release, LitWatch Backend capability,
and Dify Workflow DSL version.

- **Stack / System Release** is the recoverable, tested system milestone.
- **LitWatch Backend** is the service and integration capability included in the
  Stack milestone.
- **Dify Workflow DSL** changes only when the workflow contract or user-facing
  workflow capability changes.

For v2.0, Python LitWatch is the default Stack and a Dify Workflow DSL is not a
runtime prerequisite. Historical Dify mappings remain below for Stable v1.x
recovery and explicit rollback only.

Stack Version and Workflow Version are not required to match. Do not copy a DSL
solely to make version numbers align.

## Stack-to-Workflow Matrix

| Stack Version | Release State | Backend Capability | Compatible Dify Workflow | Providers | Stable Tag |
|---|---|---|---|---|---|
| v1.0 | Stable | Direct OpenAlex | `literature-search-v1.0.yml` | OpenAlex | `dify-v1.0` |
| v1.1 | Stable | LitWatch Search API + `LiteratureSearchService` | `literature-search-v1.1.yml` | OpenAlex | `dify-v1.1` |
| v1.2 | Stable | Provider Configuration + Provider Registry + BYOK boundary | `literature-search-v1.1.yml` (compatible reuse) | OpenAlex | `dify-v1.2` |
| v1.3 | Stable | Multi-source retrieval, deterministic aggregation, failure isolation, secure Provider BYOK; duplicates intentionally preserved | `literature-search-v1.1.yml` (compatible reuse) | OpenAlex + Semantic Scholar + arXiv + Crossref | `dify-v1.3` |
| v1.4 | Stable | Deterministic deduplication, metadata merge, relevance/quality ranking, additive diagnostics | `literature-search-v1.1.yml` (compatible reuse) | OpenAlex + Semantic Scholar + arXiv + Crossref | `dify-v1.4` |
| v1.5 | Stable | Local research Web UI, diagnostics, Provider Settings, secret-safe BYOK UX | `literature-search-v1.1.yml` (compatible reuse) | OpenAlex + Semantic Scholar + arXiv + Crossref | `dify-v1.5` |
| v1.6 | Stable | Research subscriptions, historical novelty, weekly scheduling, Dashboard recommendations and digests | `literature-search-v1.1.yml` (compatible reuse) | OpenAlex + Semantic Scholar + arXiv + Crossref | `dify-v1.6` |
| v1.7 | Stable | Research Radar, historical backfill, deterministic trends, evidence timeline | `literature-search-v1.1.yml` (compatible reuse) | OpenAlex + Semantic Scholar + arXiv + Crossref | `dify-v1.7` |
| v2.0 | Release Candidate (**Not Stable**) | Python-native lifecycle, durable jobs, paper analysis, and existing Search/Radar/Subscriptions/Digest workspace | None for the default runtime; frozen v1.1 DSL is explicit legacy rollback only | OpenAlex + Semantic Scholar + arXiv + Crossref | None |

## Provider Capability Matrix

| Provider | Stack v1.2 | Stack v1.3 | Stack v1.4 | Stack v1.5 | Stack v1.6 | Stack v1.7 |
|---|---|---|---|---|---|
| OpenAlex | Runnable | Runnable | Runnable | Runnable and selectable in UI | Runnable in subscriptions | Runnable in Radar |
| Semantic Scholar | Declared, non-runnable | Runnable | Runnable | Runnable, optional BYOK | Runnable; anonymous 429 isolated | Runnable; failure isolated |
| arXiv | Declared, non-runnable | Runnable | Runnable | Runnable and selectable in UI | Runnable in subscriptions | Runnable in Radar |
| Crossref | Declared, non-runnable | Runnable | Runnable | Runnable and selectable in UI | Runnable in subscriptions | Runnable in Radar |
| IEEE Xplore | Declared, non-runnable | Non-runnable | Non-runnable | Disabled, Coming later | Disabled, Coming later | Disabled, Coming later |
| Scopus | Declared, non-runnable | Non-runnable | Non-runnable | Disabled, Coming later | Disabled, Coming later | Disabled, Coming later |
| Web of Science | Declared, non-runnable | Non-runnable | Non-runnable | Disabled, Coming later | Disabled, Coming later | Disabled, Coming later |

## Workflow Upgrade Policy

Create a new workflow DSL only when at least one of these changes:

- User inputs or visible workflow behavior
- Request or response contract consumed by Dify
- Node topology or workflow-side processing
- Provider selection exposed to the Dify user

Do not create `literature-search-v1.2.yml`. Stack v1.2 is backward compatible
with `literature-search-v1.1.yml`.

For Stack v1.3, continue reusing v1.1 if the backend automatically performs
multi-source retrieval for the existing `topic + limit` input. Create
`literature-search-v1.3.yml` only if users select providers in Dify or another
workflow capability changes.

Stack v1.3 reuses v1.1. The compatible workflow omits `providers` and therefore
retains the default OpenAlex-only behavior. Multi-source retrieval is available
through explicit provider selection in the LitWatch API without changing the
Dify workflow contract.

Stack v1.4 also reuses v1.1. The required `topic`, `limit`, `paper_count`,
and `papers` fields are unchanged. Deduplication and ranking diagnostics are
additive top-level fields. No `literature-search-v1.4.yml` is created.

Stack v1.5 also reuses v1.1. The Web UI is an additional local entry point to
the same LitWatch API and does not change Dify's request or response contract.
No `literature-search-v1.5.yml` is created.

Stack v1.6 also reuses v1.1. Subscriptions, scheduling, historical novelty,
recommendations, and Dashboard digests are LitWatch Web capabilities and do
not change the Dify search contract. No `literature-search-v1.6.yml` is
created.

Stack v1.7 also reuses v1.1. Research Radar is an additional LitWatch Web/API
capability and does not alter the Dify search request or response contract. No
`literature-search-v1.7.yml` is created.

## Stack v2.0 Cutover Policy

The v2.0 default entry points are `启动科研文献系统.cmd`,
`停止科研文献系统.cmd`, and
`scripts/status-stack.ps1`. They manage Python LitWatch only and must not probe,
start, or require Docker, Dify, Compose, or the Dify SSRF proxy. A Python
startup failure is reported; it never triggers an automatic Dify fallback.

Legacy rollback is explicit through `启动旧版 Dify 科研文献系统.cmd` and
`停止旧版 Dify 科研文献系统.cmd` only. The old Dify repository, Docker
volumes, integration patch, and v1.0/v1.1 DSL files remain retained and frozen
until manual v2.0 acceptance is complete and a separate cleanup action is
authorized. This compatibility path does not make v2.0 Stable. There is no
v2.0 Stable tag during implementation / RC preparation.

## Stack v2.0 Release Evidence

Stack v2.0 is a Release Candidate. Automated Dify-free acceptance covered the
real FastAPI lifespan, Manual Search through the production
`LiteratureSearchService`, Provider Settings credential redaction,
subscriptions, scheduler, Weekly Digest, historical deduplication, Research
Radar, structured Paper Analysis, durable jobs, migration/backup/recovery
boundaries, and zh-CN/English pages. Full suite: 604 tests passed; Ruff,
`git diff --check`, and `git fsck --no-dangling`: pass.

The isolated real rehearsal copied the live v1.7 SQLite database read-only,
migrated the copy from schema v6 to v10 with verification, proved an invalid
migration leaves no partial state, and proved byte-identical backup recovery.
The Python-only lifecycle passed cold start, warm start, status, stop, and
restart on port 18080 with `mode=python_default` and
`requires_dify=false`. A real OpenAlex TDOA search returned HTTP 200 with 5
papers, OpenAlex provenance on all 5, and provider status `success`. A no-key
extractive analysis and subscription/Radar restart persistence passed.

See `docs/V2_0_E2E_RESULTS.md` and `docs/V2_0_MIGRATION_REHEARSAL.md`. No
v2.0 Stable tag exists; final manual acceptance remains outstanding.

## Stack v1.2 Release Evidence

The compatible `literature-search-v1.1.yml` was imported as a new Dify
application and both topics were verified:

1. `underwater acoustic TDOA localization`
2. `underwater acoustic OFDM communication`

Both workflows succeeded, returned `paper_count > 0`, included `openalex` in
paper `sources`, and returned clearly different results. Provider, profile,
redaction, Docker, SSRF, lifecycle, tests, Ruff, and stable DSL checks also
passed. See `docs/V1_2_E2E_RESULTS.md`. The absence of
`literature-search-v1.2.yml` is expected because no workflow contract changed.

## Stack v1.3 Release Evidence

OpenAlex, arXiv, and Crossref passed real retrieval. The explicit four-provider
request returned HTTP 200 with 12 papers while Semantic Scholar anonymous access
was correctly isolated as `rate_limited/upstream_429`. Semantic Scholar
environment and profile BYOK paths passed tests; authenticated real success was
not verified.

Both Dify UI topics succeeded, returned `paper_count > 0` and non-empty
`papers_json`, and produced clearly different results. The compatible workflow
retained `sources=openalex`. BYOK, endpoint SSRF protection, secret redaction,
Provider Registry, partial failure, dynamic topics, 143 tests, Ruff, diff checks,
and both stable DSL checks passed. See `docs/V1_3_E2E_RESULTS.md`.

## Stack v1.4 Release Evidence

The TDOA four-provider request returned HTTP 200, reduced 60 raw candidates to
57 unique papers, and merged OpenAlex/Crossref provenance on the top result. The
OFDM request returned HTTP 200 with query-specific OFDM communication results.
Semantic Scholar anonymous HTTP 429 remained isolated while OpenAlex, arXiv,
and Crossref succeeded.

The Dify Worker reached the v1.4 service through the real SSRF proxy and
received the unchanged OpenAlex-only default contract. Tests reached 164 passed;
Ruff, diff checks, Provider/BYOK/SSRF regressions, and stable DSL checks passed.
See `docs/V1_4_E2E_RESULTS.md`.

Final manual validation passed for TDOA ranking, OFDM ranking, dynamic ranking,
deduplication, zero final duplicate DOIs, multi-source merging, and both Dify UI
topics. Stack v1.4 is Stable at `dify-v1.4`. Semantic Scholar authenticated real
success remains not verified.

## Stack v1.5 Release Evidence

The existing FastAPI/Jinja2/vanilla JavaScript application now provides a local
multi-source search page and Provider Settings page without adding a frontend
build dependency. Real browser searches returned topic-specific TDOA and OFDM
paper cards, displayed backend scores and source provenance, and showed valid
deduplication arithmetic. OpenAlex results remained usable while Semantic
Scholar anonymous access was isolated as rate limited.

Fake-secret Provider Settings tests passed without secret reflection, and the
test credential was cleared. Responsive checks passed at a 375px effective
viewport. Stable v1.0 and v1.1 DSL files remain unchanged. See
`docs/V1_5_E2E_RESULTS.md`. Manual acceptance passed for TDOA search, paper
cards, ranking display, source merging, partial-failure UX, and Provider
Settings. Stack v1.5 is Stable at `dify-v1.5`.

## Stack v1.6 Release Evidence

Stack v1.6 adds persistent research subscriptions, a unified run
engine, per-subscription historical novelty, weekly scheduling, catch-up,
concurrency leases, stale recovery, and idempotent Dashboard digests. Real
TDOA and OFDM runs returned distinct recommendations. An immediate repeat run
recommended no previously seen papers, and a Semantic Scholar anonymous 429
was isolated as a partial success while other Providers produced a digest.

Restart persistence, Manual Search, Provider Settings, Dify, BYOK, SSRF, and
lifecycle checks passed. The final gate reached 250 passing tests with Ruff and diff
checks passing. Email delivery is deferred. Stable v1.0 and v1.1 DSL files are
unchanged. Final manual acceptance passed for Manual Search, Research
Subscriptions, Run Now, Run History, Weekly Digest, historical duplicate
suppression, and restart persistence. See `docs/V1_6_E2E_RESULTS.md`. Stack
v1.6 is Stable at `dify-v1.6`.

## Stack v1.7 Release Evidence

Real 2018-2026 TDOA and OFDM Radar scans completed through OpenAlex, arXiv, and
Crossref, persisted distinct paper histories, rendered annual trends,
paper-backed keyword evolution, deterministic trend classifications,
representative papers, and scan history. Immediate rescans reported zero new
papers. Browser checks passed in zh-CN and English. Automated tests reached 305
passing tests with Ruff and diff checks passing. Manual acceptance passed for
TDOA and OFDM Radars, historical backfill, topic isolation, technical-topic
evolution, semantic-quality filtering, representative papers, trend evidence,
evidence auto-expand, normalized DOI display, safe DOI external navigation,
rescan deduplication, and restart persistence. The final DOI fix is
`1f821a4 fix(radar): repair evidence DOI navigation`. See
`docs/V1_7_E2E_RESULTS.md`. Stack v1.7 is Stable at `dify-v1.7`.

## Recovery Rule

A recoverable Stable Stack release consists of:

- Private Git repository and commit history
- Annotated Stack tag
- Workflow DSL identified by this matrix
- Locally restored `.env` secrets
- Recreated Python dependencies
- Restored Dify deployment and separately backed-up Docker data when required

Recovery on a new computer selects a Stable Stack tag first, then imports the
compatible workflow listed here when that Stable version requires Dify. The
Stack tag does not imply a same-numbered DSL file exists.

The in-progress v2.0 Python-default work is restored from its reviewed branch or
commit, not from a Stable tag. Its normal runtime does not import a Dify DSL.
The frozen v1.x Dify assets are restored separately only when an operator
explicitly chooses the legacy rollback path.
