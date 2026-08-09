# V1.3 Multi-Source Retrieval Plan

## 1. Stable Baseline

Stack v1.3 starts from the immutable Stack v1.2 release:

- Base commit: `cc8d44f3418809d75ce66bbfc8a534d322612787`
- Base tag: `dify-v1.2`
- Development branch: `feat/v1.3-multisource`
- Compatible stable workflow: `dify/workflows/literature-search-v1.1.yml`
- Protected stable workflow: `dify/workflows/literature-search-v1.0.yml`

The branch was created directly from `dify-v1.2`. Stable tags and stable DSL files
are immutable. This plan replaces the earlier proposal to perform deduplication in
v1.3; deduplication remains a v1.4 concern.

## 2. Current V1.2 Architecture Audit

The current API path is:

```text
Dify / API client
    -> POST /api/v1/literature/search
    -> LiteratureSearchService
    -> ProviderProfileStore
    -> ProviderRegistry
    -> OpenAlexSource
    -> list[Paper]
    -> LiteratureSearchResponse
```

The audited implementation boundaries are:

| Concern | Current location | Current behavior | V1.3 action |
|---|---|---|---|
| Internal paper model | `src/litwatch/models.py` | `Paper` is the normalized provider output | Reuse |
| Provider protocol | `src/litwatch/sources/base.py` | `PaperSource.search(Topic, start_date, end_date, limit) -> list[Paper]` | Retain |
| OpenAlex adapter | `src/litwatch/sources/openalex.py` | Runnable and normalized | Reuse; no duplicate client |
| Existing Semantic Scholar adapter | `src/litwatch/sources/semantic_scholar.py` | Implements search/normalization but is not registered | Harden and register, not rewrite |
| Existing arXiv adapter | `src/litwatch/sources/arxiv.py` | Implements Atom parsing/normalization but is not registered | Harden and register, not rewrite |
| Crossref adapter | Not present | No implementation | Add one adapter |
| Provider configuration | `src/litwatch/provider_config.py` | Safe config and credential references | Extend selection semantics without storing secrets |
| Provider registry | `src/litwatch/sources/registry.py` | Only OpenAlex has a runnable factory | Register three v1.3 adapters |
| Search service | `src/litwatch/services/literature_search.py` | Sequential, fail-fast, final slicing | Add isolated orchestration and diagnostics |
| HTTP schemas | `src/litwatch/api_models.py` | Optional `providers`; stable paper projection | Add diagnostics additively |
| HTTP endpoint | `src/litwatch/web.py` | Registry errors 422, timeout 504, other upstream failures 502 | Map aggregate failures safely |
| Secrets | `src/litwatch/config.py`, `.env.example`, Registry credential store | Environment values and opaque references | Reuse/extend only where required |
| Tests | Provider config, Registry, Service, and API test modules | Offline behavior and redaction coverage | Extend with provider fixtures and failure matrices |

The legacy `Pipeline` directly constructs OpenAlex, arXiv, and optionally Semantic
Scholar. It also performs SQLite writes, deduplication, ranking, analysis, and full-text
work. V1.3 must not route the API through `Pipeline` and must not refactor that path as
part of multi-source API retrieval.

## 3. Confirmed V1.2 Request and Limit Semantics

The following behavior is established by current code and tests:

1. `providers` omitted: the service selects every `enabled` provider in the active
   profile. The built-in default profile contains only enabled OpenAlex, so the actual
   default behavior is OpenAlex-only.
2. `providers` supplied: identifiers must be unique, exist in the active profile, and
   each selected provider must be enabled, runnable, and correctly configured.
3. `limit` is passed to every selected provider.
4. Provider result lists are concatenated in provider selection order.
5. The concatenated list is sliced with `papers[:limit]`.

Therefore, the public v1.2 meaning of `limit` is a **final response total maximum**, not
a per-provider total. V1.3 preserves that meaning. The current implementation happens
to request up to `limit` from each provider as an internal fetch cap.

The current service is fail-fast: any provider exception aborts the entire search. It
does not expose provider status metadata.

## 4. V1.3 Scope and Explicit Non-Goals

V1.3 makes OpenAlex, Semantic Scholar, arXiv, and Crossref runnable through the v1.2
Registry and Search Service. IEEE Xplore, Scopus, and Web of Science remain declared but
non-runnable.

V1.3 does **not** add DOI/arXiv-ID/URL/title/fuzzy deduplication, ranking, SQLite
persistence for the search endpoint, RSS, Zotero, LLM analysis, full-text processing,
embeddings/vector storage, research-gap synthesis, or a LitWatch provider-selection UI.
Duplicate papers from different providers are intentionally allowed. Their independent
source identities make the later v1.4 deduplication work observable and testable.

## 5. Unified Provider Adapter Contract

All runnable adapters continue to satisfy the existing `PaperSource` protocol:

```python
class PaperSource(Protocol):
    name: str

    def search(
        self,
        topic: Topic,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[Paper]: ...
```

Contract rules:

- `name` is the stable identifier stored in `Paper.sources`.
- `search` returns only validated `Paper` instances, never loose dictionaries.
- The adapter owns query translation, HTTP/Atom parsing, and metadata normalization.
- The adapter does not deduplicate, rank, write databases, call Dify, or call an LLM.
- Missing strings remain empty internally; the API converts unavailable optional strings
  to JSON `null` through the existing projection.
- An individual record may be skipped only if it lacks the minimum title/identity needed
  for a valid `Paper`. A malformed whole response must raise, not return `[]`.
- Timeout, 429, 5xx, and parse failures remain distinguishable. No adapter may disguise
  them as a successful empty result.
- Retries are finite, honor valid `Retry-After`, and otherwise use capped exponential
  backoff with jitter. Unit tests replace sleep and transport operations.

Factories remain in `ProviderRegistry.from_settings`. Core search logic knows only
provider IDs, profile config, the Registry, and `PaperSource`.

## 6. Existing Normalized Paper Schema

The internal `Paper` schema remains authoritative:

| Field | Type | Integrity rule |
|---|---|---|
| `canonical_id` | `str` | Derived from real DOI, arXiv ID, or provider/title fallback |
| `source_ids` | `dict[str, str]` | Provider-native identifiers only |
| `sources` | `list[str]` | Adapters that actually supplied the record |
| `title` | `str` | Required source metadata; never generated |
| `abstract` | `str` | Source metadata or empty string |
| `authors` | `list[Author]` | Source order preserved; no AI completion |
| `publication_date` | `date | None` | Parsed source date or `None` |
| `venue` | `str` | Source venue/container or empty string |
| `doi` | `str` | DOI without `https://doi.org/`, or empty string |
| `url` | `str` | Source landing URL/DOI URL or empty string |
| `pdf_url` | `str` | Source-declared PDF URL or empty string |
| `is_open_access` | `bool` | True only with explicit provider evidence |
| `citation_count` | `int` | Provider value or zero |
| Topic/score/analysis fields | Existing types | Not populated by v1.3 API retrieval |

The stable HTTP projection remains `canonical_id`, `title`, `authors`, `year`, `venue`,
`doi`, `url`, `abstract`, and `sources`. No serializer or LLM may invent or rewrite these
metadata fields. Provider records may share a `canonical_id` in v1.3; they remain separate
entries until v1.4.

## 7. Semantic Scholar Provider Design

Reuse `SemanticScholarSource`. Required work is registration, configurable base URL
support, bounded retries, and fixtures.

- Endpoint: `GET https://api.semanticscholar.org/graph/v1/paper/search`
- Query/date: `query=<topic>` and `publicationDateOrYear=<start>:<end>`
- Limit: provider request cap, maximum 100 in the existing adapter
- Fields: `paperId`, `externalIds`, `title`, `abstract`, `authors`,
  `publicationDate`, `venue`, `url`, `openAccessPdf`, `citationCount`
- Authentication: optional `x-api-key`; most endpoints allow shared, throttled anonymous
  access. The introductory keyed limit is 1 RPS.

| Semantic Scholar | Paper |
|---|---|
| `paperId` | `source_ids["semantic_scholar"]` |
| DOI / ArXiv in `externalIds` | `doi` / canonical-ID input |
| `title`, `abstract` | `title`, `abstract` |
| `authors[].name` | `authors` in source order |
| `publicationDate`, `venue`, `url` | corresponding normalized fields |
| `openAccessPdf.url` | `pdf_url`, `is_open_access` |
| `citationCount` | `citation_count` |

`LITWATCH_SEMANTIC_SCHOLAR_API_KEY` remains the only key source. The Registry should
support an optional credential reference: use the key when configured; permit anonymous
mode only when the profile explicitly allows it. Keys never appear in config responses,
errors, logs, DSL, or fixtures.

Reference: <https://www.semanticscholar.org/product/api>

## 8. arXiv Provider Design

Reuse `ArxivSource` and its Atom parser. Required work is Registry integration,
configurable base URL, query/date correctness tests, and finite retries.

- Endpoint: `GET https://export.arxiv.org/api/query`
- Query: `search_query` from topic terms and optional categories
- Paging/order: `start=0`, `max_results=<cap>`, `sortBy=submittedDate`,
  `sortOrder=descending`
- Response: Atom 1.0
- Etiquette: repeated calls should be about three seconds apart; v1.3 uses one page per
  search and retries must respect the guidance

| arXiv Atom | Paper |
|---|---|
| entry ID | `source_ids["arxiv"]`, canonical-ID input, `url` |
| `title`, `summary` | whitespace-normalized `title`, `abstract` |
| `author/name` | `authors` in source order |
| `published`, `arxiv:doi` | `publication_date`, `doi` |
| PDF link | `pdf_url` |
| constant `arXiv` | `venue` |

The current local publication-date filter is retained. Implementation tests should also
evaluate the official `submittedDate` query clause for bounded searches without changing
broad historical behavior.

Reference: <https://info.arxiv.org/help/api/user-manual.html>

## 9. Crossref Provider Design

Add `src/litwatch/sources/crossref.py`; no Crossref adapter currently exists.

- Endpoint: `GET https://api.crossref.org/v1/works`
- Query/date: `query.bibliographic=<topic>` and
  `filter=from-pub-date:<start>,until-pub-date:<end>`
- Result cap/order: `rows=<cap>`, upstream relevance; no LitWatch ranking
- Identification: `mailto` and an identifying `User-Agent` for the polite pool
- Authentication: none for public/polite access; Metadata Plus is out of scope
- Rate behavior: honor advertised headers and 429; one request at a time per Crossref
  adapter in the public/polite pool

| Crossref work | Paper |
|---|---|
| `DOI` | normalized `doi`, `source_ids["crossref"]`, canonical-ID input |
| first `title` | `title` |
| `author[].given` + `author[].family` | `authors` in source order |
| first valid published/issued date-parts | `publication_date` |
| first `container-title` | `venue` |
| `URL` or DOI URL | `url` |
| `abstract` | markup-stripped source abstract or empty string |
| PDF item in `link` | `pdf_url`; never infer a PDF from a generic URL |
| `is-referenced-by-count` | `citation_count` |

`is_open_access` remains false unless the record supplies an explicit, reliable basis.
A publisher URL alone is not evidence of open access.

References:

- <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>
- <https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/>
- <https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/>

## 10. Provider Configuration, Selection, and Secrets

V1.2 uses `enabled` for both availability and implicit selection. That cannot preserve
an OpenAlex-only default while making new providers explicitly selectable. The proposed
additive model separates:

- `enabled`: allowed to run when selected.
- `default_selected`: selected when the request omits `providers`.

For an old profile payload where `default_selected` is absent, derive it from `enabled`
to preserve v1.2 profile semantics. The built-in v1.3 profile contains four enabled
runnable providers with only OpenAlex default-selected. Validation enforces
`default_selected => enabled` and at least one default-selected provider.

| Provider ID | Enabled | Default selected | Credential |
|---|---:|---:|---|
| `openalex` | yes | yes | no key; optional contact email |
| `semantic_scholar` | yes | no | optional `semantic_scholar_default` reference |
| `arxiv` | yes | no | none |
| `crossref` | yes | no | no key; recommended contact email |

New settings are limited to non-secret base URLs and a Crossref contact email. The
existing Semantic Scholar key and credential store are reused. `.env` stays ignored;
`.env.example` has placeholders only. Profile responses expose readiness, never values.

## 11. Limit and Deterministic Aggregation Semantics

V1.3 keeps `limit` as the maximum total response size. A multi-source request is:

```json
{
  "topic": "underwater acoustic TDOA localization",
  "limit": 10,
  "providers": ["openalex", "semantic_scholar", "arxiv", "crossref"]
}
```

Rules:

1. Pass `limit` to each adapter as a fetch cap. The API maximum of 50 and four providers
   bounds normalization to 200 records.
2. Preserve each provider's native order; v1.3 does not rank.
3. Aggregate by deterministic round-robin in request order, preventing the first source
   from consuming the entire total limit.
4. Stop at the total `limit` or when all provider lists are exhausted.
5. Preserve duplicates, including equal DOI, URL, title, arXiv ID, or canonical ID.
6. One-provider order and slicing remain equivalent to v1.2.

Providers may execute with bounded cross-provider parallelism, but completion order never
controls output. Per-provider rate/concurrency policies still apply.

## 12. Failure Isolation and Provider Status

Selection/config validation happens before network work. Unknown, duplicate, disabled,
non-runnable, or credential-invalid providers remain 422 and do not yield partial results.

- Every runtime provider call has its own failure boundary.
- A successful empty result is `ok`, not an error.
- Timeout, 429, HTTP, and parse failures remain distinct.
- At least one successful provider yields HTTP 200 plus every provider status.
- If all providers fail, return 504 only when all failures are timeouts; otherwise 502.
- Never expose raw exception text, headers, keys, paths, bodies, or tokens.

Add `provider_status` to the response:

```json
{
  "provider_status": [
    {
      "provider_id": "openalex",
      "status": "ok",
      "paper_count": 10,
      "returned_count": 3,
      "duration_ms": 412,
      "error_code": null
    },
    {
      "provider_id": "semantic_scholar",
      "status": "rate_limited",
      "paper_count": 0,
      "returned_count": 0,
      "duration_ms": 1021,
      "error_code": "upstream_429"
    }
  ]
}
```

Status values are `ok`, `timeout`, `rate_limited`, `upstream_error`, and `parse_error`.
`error_code` is LitWatch-controlled. `paper_count` is the normalized pre-aggregation
count; `returned_count` is the count retained after the total limit.

## 13. API Compatibility and Dify Workflow Decision

The endpoint remains `POST /api/v1/literature/search`. Existing `topic + limit` requests
stay OpenAlex-only with the built-in profile. Explicit `providers` enables multi-source.
Existing response fields keep their meanings; `provider_status` is additive.

Decision: reuse `dify/workflows/literature-search-v1.1.yml`. Do not create a v1.3 DSL
just to match the Stack version. Backend/API E2E covers explicit multi-source selection;
Dify E2E proves backward compatibility through the OpenAlex default.

A new `literature-search-v1.3.yml` needs separate approval and is justified only if Dify
adds provider selection or visibly consumes diagnostics. Stable v1.0 and v1.1 DSL files
must remain byte-for-byte unchanged.

## 14. Test Strategy

CI uses fake transports, fixtures, and injected sources. Live network tests are opt-in.

### Unit and adapter tests

- Config defaults, `default_selected`, legacy payloads, optional credentials, redaction
- Registry capability matrix/factories for four runnable providers
- Semantic Scholar parameters, mapping, keyed/anonymous behavior, 429/timeout/5xx/JSON
- arXiv query/Atom mapping, author order, dates, malformed XML, bounded retries
- Crossref query/headers, field/date/JATS/PDF mapping, missing fields, failure classes

### Service tests

- Omitted providers stays OpenAlex; explicit one/four-provider selection
- Invalid/duplicate/disabled/non-runnable/credential-invalid selection
- Total limit, per-provider caps, round-robin order, duplicate preservation
- Partial failures and all-timeout/mixed all-failed cases
- `Paper` enforcement, status counts/durations, no forbidden framework/pipeline imports

### API and manual tests

- Stable v1.1 request/response compatibility and additive OpenAPI diagnostics
- 422 selection errors, 200 partial success, 504 all-timeout, 502 other all-failed
- No secrets/raw upstream details in responses or examples
- One live query per provider; one four-provider request; one partial-failure exercise
- Omitted-provider result compared with explicit `providers: ["openalex"]`
- Stable v1.1 Dify workflow run unchanged

## 15. Staged Implementation Plan

### Stage 0 - Stable Branch Baseline

- Goal: branch exactly from `dify-v1.2`.
- Inspect: Git refs, tags, status, stable DSLs.
- Modify/create: none.
- Tests: tracked diff and tag/commit identity.
- Acceptance: `feat/v1.3-multisource` initially points to `cc8d44f...`.
- Commit: none.
- Rollback: remove only the uncommitted branch if explicitly approved; never move a tag.

### Stage 1 - Architecture Audit and Approved Plan

- Goal: freeze v1.3 semantics before implementation.
- Inspect: models, sources, Registry, config, Service, API, tests, DSLs, official docs.
- Modify/create: this and directly related planning documents only.
- Tests: pytest, Ruff, DSL diffs, `git diff --check`.
- Acceptance: default, limit, aggregation, errors, secrets, Dify, and stages are explicit.
- Commit: `docs(v1.3): define multi-source retrieval architecture`.
- Rollback: revert the docs commit; runtime is unaffected.

### Stage 2 - Selection and Diagnostic Contracts

- Goal: separate enabled/default selection and add internal provider-result/error models.
- Modify: `provider_config.py`, Service, API models, focused tests; `.env.example` only for
  non-secret names.
- Create: optional framework-independent provider result module.
- Tests: legacy profiles, OpenAlex default, explicit selection, status redaction/merge.
- Acceptance: OpenAlex-only request unchanged; no new provider marked runnable yet.
- Commit: `refactor(search): define multi-source selection and status contracts`.
- Rollback: revert the isolated commit.

### Stage 3 - Semantic Scholar Adapter Integration

- Goal: register/harden existing adapter with optional key and bounded retries.
- Modify: Semantic Scholar source, Registry, config, `.env.example`, tests.
- Create: JSON fixtures if needed.
- Tests: parameters/mapping/key redaction/anonymous policy/timeout/429/5xx/invalid JSON.
- Acceptance: runnable capability; `list[Paper]`; no live CI or leaked key.
- Commit: `feat(providers): enable Semantic Scholar retrieval`.
- Rollback: revert; capability becomes non-runnable.

### Stage 4 - arXiv Adapter Integration

- Goal: register/harden existing Atom adapter with polite bounded retrieval.
- Modify: arXiv source, Registry, config, `.env.example`, tests.
- Create: Atom fixtures.
- Tests: query/date/category, mapping/order, malformed Atom, timeout/retry ceiling.
- Acceptance: runnable; one page/request; all metadata source-grounded.
- Commit: `feat(providers): enable arXiv retrieval`.
- Rollback: revert; other providers remain intact.

### Stage 5 - Crossref Adapter Integration

- Goal: add/register a polite Crossref works adapter.
- Modify: source exports, Registry, config, `.env.example`, tests.
- Create: Crossref source, focused test module, JSON fixtures.
- Tests: parameters/headers/mapping/date/JATS/missing data/timeout/429/5xx/JSON.
- Acceptance: runnable public/polite provider, `list[Paper]`, no false OA inference.
- Commit: `feat(providers): add Crossref retrieval`.
- Rollback: revert; the other providers remain available.

### Stage 6 - Multi-Provider Orchestration and HTTP Semantics

- Goal: isolation, deterministic round-robin, total limit, additive statuses.
- Modify: Service, API models, web endpoint, focused tests.
- Create: small orchestration helpers only if needed for separation.
- Tests: four-provider/duplicate/order/partial/all-failed/counts/redaction/OpenAPI.
- Acceptance: valid peers survive one failure; 422 vs 200 vs 502/504 is correct.
- Commit: `feat(search): aggregate isolated multi-source results`.
- Rollback: revert orchestration while retaining independently tested adapters.

### Stage 7 - Contract, Integration, and Dify E2E

- Goal: offline regression plus manual provider/API/Dify evidence.
- Modify/create: fixtures and v1.3 E2E evidence; no stable DSL changes.
- Tests: full suites, DSL diffs, live single/four-provider, partial failure, Dify v1.1.
- Acceptance: four sources work when available, default differs correctly, failures visible.
- Commit: `test(e2e): verify v1.3 multi-source retrieval`.
- Rollback: revert evidence/tests separately from runtime commits.

### Stage 8 - Stable Release Finalization

- Goal: mark Stable only after human E2E approval.
- Modify: version/release/E2E/recovery docs as necessary.
- Tests: pytest/Ruff/diff-check/secret scan/DSL comparison/tag target/clean tracked status.
- Acceptance: approved release commit, annotated `dify-v1.3`, non-force private backup.
- Commit: `docs(release): mark stack v1.3 stable`.
- Rollback: never move a published tag; use a corrective version/commit.

## 16. Risks and Human Decision Gates

1. Approve additive `default_selected` plus the legacy fallback before Stage 2.
2. Approve round-robin aggregation and total `limit`; concatenation starves later sources.
3. Approve HTTP 200 partial success and 502/504 only for all-failed searches.
4. Bounded parallelism improves latency but needs per-provider gates; sequential execution
   remains a compatible lower-complexity option.
5. Semantic Scholar anonymous access is shared and easily throttled; scheduled use should
   prefer an environment key.
6. arXiv term extraction may be broad; query expansion is outside v1.3.
7. Crossref metadata shapes vary; missing values must not be guessed.
8. Duplicate papers are expected and must not be silently merged before v1.4.
9. Keep the v1.1 DSL unless a later approval adds a Dify provider-selection capability.
10. Registry factories create adapters per search; Stage 6 should review deterministic
    client cleanup without turning v1.3 into a general networking rewrite.
