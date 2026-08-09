# Release Matrix

## Purpose

This matrix separates the complete Stack release, LitWatch Backend capability,
and Dify Workflow DSL version.

- **Stack / System Release** is the recoverable, tested system milestone.
- **LitWatch Backend** is the service and integration capability included in the
  Stack milestone.
- **Dify Workflow DSL** changes only when the workflow contract or user-facing
  workflow capability changes.

Stack Version and Workflow Version are not required to match. Do not copy a DSL
solely to make version numbers align.

## Stack-to-Workflow Matrix

| Stack Version | Release State | Backend Capability | Compatible Dify Workflow | Providers | Stable Tag |
|---|---|---|---|---|---|
| v1.0 | Stable | Direct OpenAlex | `literature-search-v1.0.yml` | OpenAlex | `dify-v1.0` |
| v1.1 | Stable | LitWatch Search API + `LiteratureSearchService` | `literature-search-v1.1.yml` | OpenAlex | `dify-v1.1` |
| v1.2 | Stable | Provider Configuration + Provider Registry + BYOK boundary | `literature-search-v1.1.yml` (compatible reuse) | OpenAlex | `dify-v1.2` |
| v1.3 | In development | Multi-source retrieval, deterministic aggregation, provider failure diagnostics; duplicates intentionally preserved | Reuse v1.1 unless provider selection becomes a real Dify input | OpenAlex + Semantic Scholar + arXiv + Crossref | TBD |

## Provider Capability Matrix

| Provider | Stack v1.2 | Stack v1.3 Target |
|---|---|---|
| OpenAlex | Runnable | Runnable |
| Semantic Scholar | Declared, non-runnable | Runnable |
| arXiv | Declared, non-runnable | Runnable |
| Crossref | Declared, non-runnable | Runnable |
| IEEE Xplore | Declared, non-runnable | Non-runnable |
| Scopus | Declared, non-runnable | Non-runnable |
| Web of Science | Declared, non-runnable | Non-runnable |

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

## Recovery Rule

A recoverable Stable Stack release consists of:

- Private Git repository and commit history
- Annotated Stack tag
- Workflow DSL identified by this matrix
- Locally restored `.env` secrets
- Recreated Python dependencies
- Restored Dify deployment and separately backed-up Docker data when required

Recovery on a new computer selects the Stable Stack tag first, then imports the
compatible workflow listed here. The Stack tag does not imply a same-numbered DSL
file exists.
