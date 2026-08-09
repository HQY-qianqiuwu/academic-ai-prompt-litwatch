# Stack Iteration Plan

## Version Semantics

This project tracks three related but independent versions:

1. **Stack / System Release** covers the complete Dify + LitWatch + Provider +
   Zotero + analysis system and is represented by stable tags such as
   `dify-v1.1`.
2. **LitWatch Backend** covers FastAPI, services, providers, configuration,
   deduplication, ranking, integrations, and analysis capabilities.
3. **Dify Workflow DSL** changes only when the workflow contract or user-facing
   workflow capability changes.

Stack and Workflow versions are not required to match. A backend-only Stack
release may reuse an older compatible DSL. See `docs/RELEASE_MATRIX.md` for the
authoritative mapping.

## Stack v1.0 — Direct OpenAlex

Status: Stable

- Architecture: Dify -> OpenAlex
- Workflow: `dify/workflows/literature-search-v1.0.yml`
- Stable tag: `dify-v1.0`

## Stack v1.1 — LitWatch Search API

Status: Stable

- Architecture: Dify -> LitWatch API -> `LiteratureSearchService` -> OpenAlex
- Workflow: `dify/workflows/literature-search-v1.1.yml`
- FastAPI search endpoint and offline contract tests: complete
- Host, Docker networking, DSL import, runtime, and dynamic-topic validation: pass
- Stable tag: `dify-v1.1`

## Stack v1.2 — Provider Configuration Layer

Status: Stable

- Architecture: Dify -> LitWatch API -> Provider Configuration -> Provider
  Registry -> OpenAlex
- Compatible workflow: `dify/workflows/literature-search-v1.1.yml`
- The v1.1 `topic + limit` request remains backward compatible.
- Search optionally accepts `providers`.
- Provider Profile, enable/disable, credential reference, BYOK boundary, and
  credential redaction are implemented.
- OpenAlex is the only runnable provider.
- Semantic Scholar, arXiv, Crossref, IEEE Xplore, Scopus, and Web of Science are
  capability declarations only.
- No `literature-search-v1.2.yml` should be created merely to match the Stack
  version.
- Local lifecycle management covers cold start, warm start, safe stop, restart,
  provider readiness, and SSRF proxy readiness without deleting Docker volumes.
- The Dify 1.16.1 LitWatch SSRF exception is reproducible from the versioned
  integration asset and remains restricted to `host.docker.internal:8000`.
- Stable tag: `dify-v1.2`

### v1.2 Completion Evidence

Import `literature-search-v1.1.yml` as a new Dify application without replacing
v1.0, then run:

- `underwater acoustic TDOA localization`
- `underwater acoustic OFDM communication`

Both runs passed through LitWatch v1.2, returned `paper_count > 0`, included
`openalex` in `sources`, and produced clearly different paper sets. Provider
configuration, profile redaction, restart behavior, Docker networking, narrow
SSRF access, local lifecycle management, tests, Ruff, and stable DSL protection
also passed. The complete record is `docs/V1_2_E2E_RESULTS.md`.

## Stack v1.3 — Multi-Source Literature Retrieval

Status: Stable

First runnable provider set:

- OpenAlex
- Semantic Scholar
- arXiv
- Crossref

IEEE Xplore, Scopus, and Web of Science remain non-runnable in v1.3.

Released architecture:

```text
User Query
    -> LiteratureSearchService
    -> Provider Registry
       |-- OpenAlex
       |-- Semantic Scholar
       |-- arXiv
       `-- Crossref
    -> Paper normalization
    -> Merge
    -> Response with provider status
```

All providers must return the existing `Paper` model. Provider metadata remains
source-grounded; missing metadata stays null/empty according to the existing
model and must never be invented by an LLM.

V1.3 aggregates normalized records without deduplication or ranking. Duplicate
records are intentionally preserved so that v1.4 can introduce and validate
deterministic deduplication separately. Provider failures must be isolated,
partial results may be returned, and response diagnostics must state which
providers succeeded, timed out, or failed. The approved architecture and stage
boundaries are recorded in `docs/V1_3_MULTI_SOURCE_PLAN.md`.

Semantic Scholar and any future keyed provider must reuse the v1.2 profile and
credential-reference layer. Anonymous mode may be supported where the provider
permits it. Keys remain excluded from source, DSL, Git, and ordinary logs.

The released BYOK extension supports known-provider-compatible HTTPS endpoints,
write-only runtime Profile secrets, environment fallback, partial update secret
preservation, DNS/IP validation, and redirect blocking. Semantic Scholar
authenticated real success remains **not verified**. Anonymous access returned
an upstream HTTP 429, and rate-limit isolation passed.

### v1.3 Workflow Decision Gate

Continue reusing `literature-search-v1.1.yml` if the default multi-source search
remains compatible with `topic + limit`. Create `literature-search-v1.3.yml`
only if Dify adds a real user-facing provider selection input or another workflow
contract change.

The release decision is to reuse `literature-search-v1.1.yml`. Dify continues
to send `topic + limit` without `providers`, preserving OpenAlex-only default
behavior, while explicit multi-source API requests can select all four providers.

After Stack v1.2 is tagged, create v1.3 from that tag:

```powershell
git switch -c feat/v1.3-multisource dify-v1.2
```

### v1.3 Completion Evidence

- OpenAlex, arXiv, and Crossref real E2E: pass
- Semantic Scholar anonymous: upstream rate limited HTTP 429
- Semantic Scholar rate-limit isolation and BYOK paths: pass
- Semantic Scholar authenticated real success: not verified
- Four-provider HTTP 200, aggregation, and partial failure handling: pass
- Dynamic-topic API and Dify UI runs: pass
- Dify Topic A and Topic B: workflow success with non-empty results
- Provider Registry, BYOK, SSRF-safe base URLs, and secret redaction: pass
- Tests: 143 passed; Ruff and `git diff --check`: pass
- v1.0 and v1.1 stable DSL files: unchanged
- Stable tag: `dify-v1.3`

The complete release evidence is `docs/V1_3_E2E_RESULTS.md`.

## Stack v1.4 — Deduplication, Relevance, and Quality Ranking

Candidate papers -> deduplication -> keyword relevance -> metadata completeness
-> citation/venue signals -> priority score. Deterministic ranking remains the
default; LLMs do not replace deterministic scoring.

Initial deterministic deduplication priority:

1. DOI exact match
2. arXiv identifier exact match
3. Canonical URL
4. Normalized title

Merged papers must preserve all contributing source names and identifiers.

## Stack v1.5 — LitWatch Web UI

Build the user-facing UI for topic, year range, result count, provider selection,
provider status, search execution, and paper metadata. Add Provider Settings with
Ready/Configured/Missing Key states. Keep `/docs` as a developer interface, not
the end-user UI.

## Stack v1.6 — Zotero Integration

Support collection routing, tags, notes, Library ID, collection mapping, and
secure Zotero credentials through the configuration layer.

## Stack v1.7 — LLM Abstract Analysis

Extract research question, method, dataset/experiment, results, innovation,
limitations, and keywords. Every analysis must declare `metadata_only` or
`abstract` evidence scope and must not claim full-text evidence.

## Stack v1.8 — PDF and Full-Text Analysis

Add PDF retrieval, parsing, section extraction, and `fulltext_excerpt` /
`fulltext` evidence scopes.

## Stack v1.9 — Cross-Paper Synthesis

Add method comparison, research landscape, representative work, shared
limitations, research gaps, and future directions with paper-level evidence.

## Stack v2.0 — Sustainable Personal Research System

```text
Research Topic
    -> Multi-source Search
    -> Deduplication
    -> Ranking
    -> Zotero
    -> Abstract / PDF Analysis
    -> Cross-paper Synthesis
    -> Research Gap
    -> Sustainable RSS / API Updates
```

## Release and Branch Rules

Every Stable Stack release requires tests, Ruff, manual E2E, a release commit,
an annotated tag, and non-force pushes of the release branch and tag to the
private backup. The next feature branch starts from the preceding Stable tag;
development must not accumulate indefinitely on an older feature branch.

Secrets, `.env`, API keys, tokens, and passwords are never committed. Stable
tags and stable DSL files are immutable.
