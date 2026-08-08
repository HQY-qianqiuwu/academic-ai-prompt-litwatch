# V1.1 API Audit

## 1. Stable Baseline

- Commit: `9d2a29e`
- Tag: `dify-v1.0`
- Stable DSL: `dify/workflows/literature-search-v1.0.yml`
- Stable status: frozen; the commit, tag, and DSL must not be modified or overwritten.

The v1.0 Dify workflow currently executes this chain:

```text
Dify user input (`topic`)
→ Dify HTTP Request node
→ OpenAlex `GET https://api.openalex.org/works`
→ Dify Code node
→ OpenAlex metadata normalization
→ Dify Output node (`paper_count`, `papers_json`)
```

The v1.0 Code node reconstructs OpenAlex abstracts and normalizes title, authors, publication
year, venue, DOI, URL, abstract, and source into JSON output.

## 2. Existing Reusable Components

### Paper model

- File: `src/litwatch/models.py`
- Current responsibility: defines the normalized `Paper` domain model and `Author` model. The
  model already contains canonical ID, source IDs, sources, title, abstract, authors,
  publication date, venue, DOI, URL, PDF URL, open-access status, citation count, topic data,
  ranking data, and analysis data.
- Reused in v1.1: yes. `LiteratureSearchService` must return `Paper` instances rather than a
  second OpenAlex-specific dictionary schema.
- Modification allowed in v1.1: no modification is planned. API-specific conversion such as
  `publication_date` to `year` and `Author` objects to author-name strings belongs in the API
  serializer, not in the stable domain model.

### PaperSource interface

- File: `src/litwatch/sources/base.py`
- Current responsibility: defines the structural `PaperSource` protocol with a source name and
  a `search(topic, start_date, end_date, limit) -> list[Paper]` method.
- Reused in v1.1: yes. It is the existing boundary between deterministic search orchestration
  and an external literature provider.
- Modification allowed in v1.1: no modification is planned for Stage 1 or the initial Stage 2
  implementation. Any signature change would affect all existing providers and requires a
  separately reviewed need.

### OpenAlexSource

- File: `src/litwatch/sources/openalex.py`
- Current responsibility: owns the OpenAlex HTTP client, query construction, date filtering,
  request execution, HTTP error propagation, abstract reconstruction, canonical ID creation,
  and conversion of OpenAlex metadata into `Paper`.
- Reused in v1.1: yes. It is the only provider called by the v1.1 API.
- Modification allowed in v1.1: no client rewrite or duplicate OpenAlex implementation is
  allowed. A minimal backward-compatible change may only be proposed if Stage 2 proves it is
  necessary and the change is reviewed before implementation.

### FastAPI web.py

- File: `src/litwatch/web.py`
- Current responsibility: creates the FastAPI application and currently exposes the HTML home
  page, background scan actions, quick search form, BibTeX export, static assets, and health
  endpoint. It initializes the existing settings and SQLite database used by the dashboard.
- Reused in v1.1: yes. The new JSON endpoint will be mounted on this existing FastAPI
  application.
- Modification allowed in v1.1: yes, but only in Stage 3 to register
  `POST /api/v1/literature/search`, inject the search service, and map validated service results
  and errors to the API contract. Stage 1 does not modify this file.

### SQLite

- File: `src/litwatch/db.py`
- Current responsibility: creates and manages the `runs`, `papers`, and `paper_topics` tables;
  stores normalized papers, topic associations, scores, analysis results, and scan summaries.
- Reused in v1.1: no. The v1.1 synchronous search endpoint is request/response only and must not
  start a run, upsert papers, or query stored papers.
- Modification allowed in v1.1: no.

The existing FastAPI application may still open its dashboard database during application
startup. The v1.1 endpoint itself must not perform SQLite persistence.

### Ranking

- File: `src/litwatch/ranking.py`
- Current responsibility: applies exclusion rules, domain gates, keyword or optional semantic
  relevance, recency, citation impact, access, and metadata scoring to a `Paper`.
- Reused in v1.1: no. v1.1 returns normalized OpenAlex search results without LitWatch ranking.
- Modification allowed in v1.1: no.

### Pipeline

- File: `src/litwatch/pipeline.py`
- Current responsibility: coordinates OpenAlex, arXiv, and optional Semantic Scholar retrieval;
  merges duplicate papers; ranks results; optionally extracts full text and analyzes papers;
  and persists runs and papers to SQLite.
- Reused in v1.1: no. Calling `Pipeline.run()` would introduce multi-source retrieval, ranking,
  analysis, full-text, and persistence behavior outside the v1.1 boundary.
- Modification allowed in v1.1: no.

### Existing tests

- Files:
  - `tests/test_core.py`
  - `tests/test_web_static.py`
  - `tests/test_weekly_report.py`
- Current responsibility: 16 existing tests cover canonical IDs, OpenAlex abstract
  reconstruction, ranking and domain gates, metadata merge behavior, SQLite round trips,
  BibTeX export, analyzer fallback, web background scanning, static export, and weekly reports.
- Reused in v1.1: yes. They remain regression tests and must pass after every v1.1 Stage.
- Modification allowed in v1.1: existing test intent must not be weakened. New service and API
  behavior should be covered by new focused test files. Existing tests may only be adjusted if a
  reviewed interface refactor makes an import path obsolete without changing behavior.

## 3. V1.1 Architecture Boundary

v1.1 introduces one new internal application service and changes only the Dify-to-provider
boundary:

```text
Dify
→ POST /api/v1/literature/search
→ LiteratureSearchService
→ OpenAlexSource
→ Paper
→ API response serializer
→ Dify output
```

Responsibilities inside this boundary:

- Dify supplies the user topic and requested limit.
- FastAPI validates the request and translates service errors into HTTP responses.
- `LiteratureSearchService` coordinates the single OpenAlex search without knowing HTTP response
  formatting.
- `OpenAlexSource` performs the real external request and metadata normalization.
- `Paper` is the internal source-of-truth model.
- The API serializer exposes only the approved v1.1 response fields.

## 4. Explicit Non-Goals

v1.1 does not add or invoke:

- Semantic Scholar
- arXiv
- Crossref
- RSS
- SQLite persistence from the literature search endpoint
- Ranking
- LLM analysis or relevance filtering
- Zotero synchronization
- Full-text retrieval or analysis
- Research Gap analysis

The existing static browser search in `src/litwatch/static/live-search.js` is also outside this
Stage. v1.1 changes the Dify workflow path, not every existing LitWatch user interface.

## 5. API Contract Draft

Planned endpoint:

```text
POST /api/v1/literature/search
```

Request draft:

```json
{
  "topic": "underwater acoustic TDOA localization",
  "limit": 10
}
```

Response draft:

```json
{
  "query": "underwater acoustic TDOA localization",
  "paper_count": 10,
  "papers": [
    {
      "canonical_id": "doi:10.xxxx/example",
      "title": "Example title from OpenAlex",
      "authors": ["Example Author"],
      "year": 2024,
      "venue": "Example venue",
      "doi": "10.xxxx/example",
      "url": "https://doi.org/10.xxxx/example",
      "abstract": "Example abstract reconstructed from OpenAlex data.",
      "sources": ["openalex"]
    }
  ]
}
```

This is a contract draft only. Stage 1 does not implement the endpoint, request model, response
model, service, or Dify v1.1 workflow.

## 6. Error Boundary

The planned HTTP error boundary is:

- Request validation error → `422 Unprocessable Entity`
- OpenAlex timeout → `504 Gateway Timeout`
- OpenAlex upstream HTTP error or response parsing error → `502 Bad Gateway`
- An upstream failure must not be returned as a successful response with
  `paper_count: 0`.

The API response must use a stable, sanitized error message and must not expose credentials or
unnecessary internal exception details.

## 7. Data Integrity Rules

The following fields may only originate from real Provider data normalized into `Paper`:

- `title`
- `authors`
- `publication_date` and derived `year`
- `venue`
- `doi`
- `url`
- `abstract`

Neither AI nor the API serializer may invent, rewrite, or infer missing bibliographic facts.
The serializer may perform deterministic representation changes only, such as deriving `year`
from a real `publication_date` or converting `Author` objects to author-name strings. Missing
Provider values must remain missing according to the final API schema; they must not be guessed.

`canonical_id` must continue to use the existing deterministic DOI-first and normalized-title
fallback logic. `sources` must identify the real provider and must be `["openalex"]` in v1.1.

## 8. Stage 2 Entry Criteria

Stage 2 may begin only when all of the following are true:

1. This Stage 1 audit has been reviewed and approved.
2. Stage 1 has its own approved commit; no automatic commit is permitted.
3. HEAD still descends from the frozen `9d2a29e` baseline.
4. `dify-v1.0` still resolves to `9d2a29e`.
5. `dify/workflows/literature-search-v1.0.yml` has no modification.
6. The Stage 1 diff contains only `docs/V1_1_API_AUDIT.md`.
7. Existing pytest and Ruff checks pass, or any environment-only tool failure is reported without
   installing or changing dependencies.
8. The request/response draft, error boundary, and data-integrity rules are accepted.
9. Stage 2 remains limited to `LiteratureSearchService` and the existing OpenAlex Provider; it
   does not begin FastAPI endpoint or Dify DSL work.
10. Existing untracked `.github` files and all other unrelated files remain unmodified,
    unstaged, and uncommitted.
