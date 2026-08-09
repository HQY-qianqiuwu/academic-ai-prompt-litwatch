# Stack v1.5 LitWatch Web Interface

Status: implementation design for the v1.5 release-candidate branch

## Existing Web audit

The current project already has one FastAPI application with:

- server-rendered Jinja2 templates;
- package-mounted static files;
- vanilla JavaScript;
- plain CSS;
- an SQLite-backed historical dashboard and static-site export;
- JSON APIs for search, Provider capabilities, and Provider Profiles.

There is no HTMX, React, Vue, Next.js, Node.js build, Playwright, or Cypress
dependency. Stack v1.5 keeps this stack and adds no frontend build runtime.

The legacy `index.html` template serves both the database dashboard and static
export. Static export also uses `live-search.js`, which directly queries
OpenAlex only for the standalone public snapshot. Stack v1.5 does not reuse
that direct-fetch path for the local research interface. Local browser search
must call LitWatch's own API so Provider selection, BYOK, SSRF controls,
deduplication, ranking, and partial-failure behavior remain authoritative.

## Page and route architecture

```text
GET /
    -> research_search.html
    -> research-search.js
    -> POST /api/v1/literature/search

GET /provider-settings
    -> provider_settings.html
    -> provider-settings.js
    -> GET /api/v1/providers
    -> GET /api/v1/provider-profiles
    -> POST /api/v1/provider-profiles

GET /dashboard
    -> existing index.html and database/weekly-report view
```

All routes remain in the existing FastAPI app. This is not a second Web
application. The static exporter continues using `index.html` unchanged.

## Search interface

The main page contains:

- required, trimmed Research Topic input;
- result limits `5`, `10`, `20`, `30`, and `50`, default `10`;
- Provider choices loaded from `GET /api/v1/providers`;
- disabled Coming later choices for `runnable=false` Providers;
- default checks derived from `default_selected`;
- one Relevance ordering mode, with no unsupported sort selector;
- submit/loading protection and Enter submission;
- pre-search, empty, error, retry, and partial-success states.

The browser sends only:

```json
{
  "topic": "underwater acoustic TDOA localization",
  "limit": 10,
  "providers": ["openalex", "arxiv", "crossref"]
}
```

The `providers` field is omitted only when the UI intentionally uses backend
defaults. No browser code contacts an academic Provider directly.

## Date filter decision

`PaperSource.search(topic, start_date, end_date, limit)` has internal date
arguments, but the stable HTTP request and `LiteratureSearchService.search`
contracts do not expose a user date range. Stack v1.5 therefore does not show
From Year / To Year inputs. Date filtering is deferred until one additive,
cross-Provider API contract is designed and tested consistently.

## Paper cards

Cards preserve backend order and display:

- rank number;
- title;
- authors or `Authors unavailable`;
- year and venue when present;
- DOI/external link only from real `doi` or `url` fields;
- visually collapsed full abstract with Show more / Show less;
- `Abstract unavailable` when absent;
- source badges taken only from `paper.sources`;
- Relevance, Quality, and Rank values matched by `canonical_id` from top-level
  diagnostics.

Quality is labelled as metadata/source completeness, not journal prestige,
impact factor, or intrinsic scientific quality. Links use `target="_blank"`
and `rel="noopener noreferrer"`.

## Diagnostics and Provider status

The summary renders `raw_count`, `dedup_count`, and `duplicates_removed` as
candidate, unique, and merged counts. Candidate budget and detailed returned
scores stay in a collapsible Advanced details section.

Every `provider_status` entry receives a visible text label. Rate limits,
timeouts, authentication failures, upstream failures, parse failures, empty
results, and successes are distinct. Partial failure keeps successful paper
cards visible and announces how many Providers returned usable results.

## Safe errors

The UI maps status and safe API details to user messages:

- 400/422: Invalid search configuration
- 429: Provider rate limited
- 502: All providers are temporarily unavailable
- 504: Search timed out
- network failure: LitWatch service unavailable
- malformed JSON/shape: Invalid response from LitWatch

Raw traceback, headers, upstream body, exception text, and credentials are
never rendered. Retry reuses the visible form values.

## Provider Settings

The settings page reads the default Provider Profile and displays:

- Provider name;
- Enabled;
- Default Search;
- Base URL;
- Configured / Not configured credential state;
- empty `type=password` replacement input when a credential reference exists.

Save uses partial Provider updates. An empty password input omits `api_key`, so
the backend preserves any existing secret. A non-empty input is write-only and
is cleared from the DOM after the response. Explicit Clear API Key is available
only for Providers with a credential reference and requires browser
confirmation before sending `clear_secret=true`.

The browser never receives or injects a stored secret. HTTPS, DNS, SSRF,
private-address, and redirect validation remain backend responsibilities. A
rejected endpoint becomes the safe message `This endpoint is not allowed.`

Semantic Scholar is described as optional BYOK. Missing credentials mean
anonymous mode; HTTP 429 means Rate limited, not Broken. Credential configured
does not claim authenticated verification.

## Test Connection decision

No safe Provider test endpoint currently exists. Stack v1.5 does not add one,
because doing so would expand backend semantics and external-request security
scope. This remains a future additive improvement.

## Responsive and accessible behavior

The local desktop targets are 1920x1080, 1440x900, and 1366x768. Search controls
use a bounded content width, responsive grids, wrapping Provider choices, and
single-column cards below tablet width. Labels bind to controls; states include
text in addition to color; buttons expose clear names; disabled Providers are
both semantically and visually disabled; status containers use appropriate
live-region roles.

## Launcher decision

The existing full-stack launcher continues opening Dify at `http://localhost`
to avoid changing established lifecycle behavior. The repository already
provides `打开 LitWatch.cmd`, which starts or reuses LitWatch and opens
`http://127.0.0.1:8000/`. Stack v1.5 reuses this explicit LitWatch entry and
adds navigation between LitWatch Search, the legacy Dashboard, Provider
Settings, and Dify. No launcher change is required.

## Test plan

Offline tests cover:

- `GET /`, `/dashboard`, and `/provider-settings` HTML;
- local static assets and absence of direct academic Provider fetches;
- dynamic Provider capability and profile contracts;
- search request shape and unchanged API response fields;
- card, score, source, diagnostics, status, empty, loading, and error hooks;
- secret-free HTML/JavaScript and safe profile persistence behavior;
- empty password preservation, fake-secret write/redaction, explicit clear,
  safe public endpoint acceptance, and private endpoint rejection;
- stable DSL and v1.4 backend regression gates.

Real browser E2E uses the running current-branch service for TDOA and OFDM,
checks the rendered cards and dynamic result differences, verifies dedup
arithmetic and multi-source badges when present, confirms partial-failure UX,
and exercises Provider Settings only with a fake runtime secret followed by
cleanup/restoration.
