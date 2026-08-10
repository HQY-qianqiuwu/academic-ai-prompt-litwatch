# Stack v1.7 Research Radar and Historical Trend Intelligence

Status: **RELEASE CANDIDATE**

Base tag: `dify-v1.6`

Base commit: `dec49ea2ecc466bfa2f8a71cf8f22b762e0e24c0`

Branch: `feat/v1.7-research-radar`

## Product boundary

Stack v1.7 separates four user intents:

| Module | Question answered | Persistent history |
|---|---|---|
| Manual Search | What do I want to find now? | No Radar or Subscription state |
| Research Radar | How did this direction evolve and what is active now? | Per-Radar observations and scans |
| Research Subscription | Which future papers must not be missed? | Per-Subscription seen/recommended state |
| Weekly Digest | What new papers are worth reading this period? | Immutable Subscription run delivery |

Radar observations never mark a Subscription paper as seen or recommended.
Manual Search never changes either history. All three features reuse the global
`papers.canonical_id` metadata identity.

## Architecture

```text
Research Radar UI / API
    -> ResearchRadarService
    -> LiteratureSearchService
    -> Provider Registry / Provider Profiles / BYOK
    -> OpenAlex, Semantic Scholar, arXiv, Crossref
    -> existing search-time deduplication and ranking
    -> global Paper metadata enrichment
    -> RadarRepository (Radar-specific observation state)
    -> RadarAnalysisService
       -> annual statistics
       -> deterministic keyword extraction
       -> keyword evolution
       -> trend scoring and classification
       -> timeline and representative papers
    -> persisted scan analysis JSON
    -> Research Radar dashboard
```

`ResearchRadarService` must not instantiate or call a Provider directly. It
receives `LiteratureSearchService`, repositories, and clocks through dependency
injection. Existing Provider failure isolation, SSRF validation, profile-backed
BYOK, deduplication, ranking, and metadata truth rules remain authoritative.

## Release Candidate implementation

The release candidate implements validated Radar CRUD, restart-safe SQLite
persistence, bounded two-year historical backfill, provider failure isolation,
global `Paper` metadata reuse, Radar-specific observation history, stale scan
recovery, deterministic annual and keyword statistics, trend classification,
paper-evidenced timelines, and representative-paper selection.

The FastAPI/Jinja2/vanilla JavaScript interface is available at `/radars`.
`/dashboard` redirects to this canonical route. The page reads persisted
analysis without contacting Providers and exposes explicit scan actions for
external retrieval. Radar and trend actions may prefill `/subscriptions`, but
the user must explicitly submit the Subscription form.

Automated and real validation evidence is recorded in
`docs/V1_7_E2E_RESULTS.md`. Stack v1.7 remains a Release Candidate until manual
acceptance; no `dify-v1.7` tag exists.

## Existing components reused

- `litwatch.models.Paper`: the only paper metadata model.
- `papers.canonical_id`: the only persisted global paper identity.
- `LiteratureSearchService`: Provider selection, execution isolation,
  deduplication, ranking, and safe Provider diagnostics.
- `deduplicate_papers`, `papers_are_duplicates`, and deterministic metadata
  merge rules: cross-Provider and cross-period identity resolution.
- `ProviderRegistry` and `ProviderProfileStore`: runnable Provider validation;
  Radar stores identifiers only, never credentials.
- `Database` migrations and SQLite transactions: additive, restart-safe
  persistence.
- existing FastAPI, Jinja2, vanilla JavaScript, CSS, and central `i18n.js`.

## Date-range retrieval contract

The v1.1 HTTP search contract remains unchanged. Internally,
`LiteratureSearchService.search` gains optional `start_date` and `end_date`
arguments. When omitted, it retains the v1.6 historical-default behavior.
Radar always supplies explicit dates.

Current Provider behavior is recorded truthfully:

| Provider | Filtering mode | Evidence in adapter |
|---|---|---|
| OpenAlex | provider-side | `from_publication_date` / `to_publication_date` |
| Crossref | provider-side | `from-pub-date` / `until-pub-date` |
| Semantic Scholar | provider-side | `publicationDateOrYear` |
| arXiv | provider-side plus post-validation | `submittedDate` query and local date check |

Future adapters without native date filtering must declare post-filtering and
return bounded candidates. Diagnostics expose the mode; they must not claim a
uniform capability that does not exist.

## Historical backfill

- accepted range: 1 to 20 inclusive years;
- default range: current year and the preceding nine years;
- chunk size: deterministic two-year periods, with a one-year final chunk;
- execution: sequential by period and Provider through
  `LiteratureSearchService`; no unbounded fan-out;
- per-period limit: configurable, default 30, maximum 50;
- each completed period is persisted through the scan transaction boundary;
- Provider failures remain isolated; at least one successful/empty Provider
  permits a `partial_success` scan;
- all Providers failing produces `failed` and no new analysis snapshot;
- a failed rescan leaves the previous successful analysis readable.

The first implementation is deliberately bounded. It is a research landscape
sample, not a claim of exhaustive bibliographic coverage.

## Persistence schema

Migration 6 adds the following tables.

### `research_radars`

| Column | Rule |
|---|---|
| `id TEXT PRIMARY KEY` | generated opaque identifier |
| `name TEXT NOT NULL` | trimmed, 1-120 characters |
| `topic TEXT NOT NULL` | trimmed, 1-500 characters |
| `keywords_json TEXT NOT NULL` | unique nonblank phrases |
| `exclude_keywords_json TEXT NOT NULL` | unique nonblank phrases |
| `providers_json TEXT NOT NULL` | runnable Provider identifiers only |
| `start_year INTEGER NOT NULL` | valid year; range maximum 20 |
| `end_year INTEGER NOT NULL` | greater than or equal to start |
| `recent_window_years INTEGER NOT NULL` | 1-5 and within range |
| `search_limit_per_period INTEGER NOT NULL` | 1-50, default 30 |
| `enabled INTEGER NOT NULL` | soft-disable, no default hard delete |
| `created_at`, `updated_at` | UTC aware ISO timestamps |
| `last_scan_at`, `last_success_at` | nullable UTC aware ISO timestamps |

Names are not unique and are never used as identity.

### `radar_scans`

| Column | Rule |
|---|---|
| `id TEXT PRIMARY KEY` | opaque scan identifier |
| `radar_id TEXT NOT NULL` | restricted FK to `research_radars` |
| `started_at`, `heartbeat_at`, `finished_at` | UTC aware timestamps |
| `status TEXT NOT NULL` | pending/running/success/partial_success/failed/interrupted |
| `start_year`, `end_year` | immutable range snapshot |
| `raw_count`, `dedup_count`, `new_count` | nonnegative counts |
| `provider_status_json` | safe status/error codes and filtering modes |
| `analysis_json` | persisted successful deterministic analysis |
| `safe_error` | allowlisted code only; no traceback or upstream body |

A partial unique index permits at most one `running` scan per Radar. A stale
running scan is marked `interrupted` after the configured lease timeout.

### `radar_papers`

| Column | Rule |
|---|---|
| `radar_id`, `canonical_id` | composite primary key |
| `first_seen_at`, `last_seen_at` | UTC observation timestamps |
| `first_scan_id`, `last_scan_id` | Radar scan provenance |
| `publication_year` | nullable real Provider metadata year |
| `relevance_score`, `representative_score` | deterministic 0-1 values |

The relation references the existing global `papers` row. A rescan updates
`last_seen_at` and metadata but counts only newly inserted Radar relations as
`new_count`.

## Persisted analysis shape

The latest successful scan stores a rebuildable JSON snapshot containing:

- `annual_counts`: year/count pairs;
- `partial_current_year`: boolean and current-year label;
- `periods`: deterministic year windows and their keyword frequencies;
- `trends`: phrase, classification, normalized score components, counts,
  growth, sources, and evidence canonical IDs;
- `timeline`: periods, top phrases, and representative canonical IDs; and
- `representative_papers`: canonical IDs with deterministic selection scores.

Opening a Radar reads this snapshot. It never calls a Provider. Only create and
rescan actions perform historical retrieval.

## Deterministic keyword extraction

Inputs are Provider keywords when available in the future, title text, and
abstract text. v1.7 does not require an LLM.

1. Normalize Unicode punctuation and case while retaining display forms.
2. Preserve allowlisted technical terms such as `TDOA`, `GCC-PHAT`, `OFDM`,
   `MIMO`, `AUV`, `CNN`, `LSTM`, and `YOLO`.
3. Detect transparent multi-word phrases including `deep learning`, `neural
   network`, `underwater localization`, `time delay estimation`, `receiver
   geometry`, `cross correlation`, and `synchronization-free`.
4. Count remaining informative unigrams/bigrams.
5. Remove general stopwords and topic-neutral tokens, including `paper`,
   `study`, `method`, `result`, `using`, `based`, `analysis`, `underwater`, and
   `acoustic` when they carry no discriminatory value.
6. Keep only phrases backed by persisted canonical IDs.

Equal inputs always produce equal ordered output: descending count, then
casefolded phrase.

## Periods and keyword evolution

The year range is divided into at most four chronological windows with stable,
near-equal widths. Each period exposes its top phrases and evidence papers.
Periods are data labels, not generated historical narratives. The UI uses
“主要研究关键词” when no evidence-based stage name exists.

## Recent window and partial-year handling

The recent window is `[end_year - recent_window_years + 1, end_year]`; earlier
years form the historical baseline. If `end_year` is the current year, the UI
labels it incomplete. Trend volume calculations apply a deterministic exposure
factor based on elapsed days in the year, capped to prevent extreme early-year
inflation. Classification never marks every phrase declining solely because
the current calendar year is incomplete.

## Hotness score

All components are normalized to 0-1. The documented v1.7 score is:

```text
hotness =
    0.35 * recent_volume_component
  + 0.30 * growth_component
  + 0.20 * recency_component
  + 0.15 * source_diversity_component
```

- `recent_volume_component`: phrase recent count divided by the largest recent
  phrase count in the same Radar;
- `growth_component`: normalized recent annual rate versus historical annual
  rate, clipped to `[-1, 3]` and mapped to `[0, 1]`;
- `recency_component`: weighted mean publication recency inside the configured
  range;
- `source_diversity_component`: distinct evidence Providers divided by the
  number of configured Providers.

No citation count, Impact Factor, JCR quartile, journal prestige, or LLM score
is used.

## Trend classification

Classification is deterministic and evidence-count aware:

- **Emerging**: historical count at most 1, recent count at least 2, and
  positive growth;
- **Hot**: recent count at least 2, hotness at least 0.65, and recent annual
  rate greater than the baseline rate;
- **Sustained**: recent and historical counts are both at least 2 and the
  recent/baseline annual-rate ratio is between 0.75 and 1.5;
- **Declining**: historical count at least 2 and the corrected recent annual
  rate is below 0.75 of baseline;
- phrases without sufficient evidence are omitted from trend cards.

Every returned trend contains at least one persisted evidence canonical ID.

## Representative papers and timeline

Representative score is deterministic:

```text
0.45 * relevance + 0.25 * metadata_quality
+ 0.20 * phrase_representativeness + 0.10 * source_diversity
```

Selection is ordered by score, then publication date, then canonical ID and is
not simply “newest first”. UI wording is always “代表论文”, never “most
important” or “foundational”. Timeline periods show top phrases and evidence;
v1.7 does not fabricate narrative stage names.

## API and UI routes

API:

- `GET /api/v1/radars`
- `POST /api/v1/radars`
- `GET /api/v1/radars/{id}`
- `PATCH /api/v1/radars/{id}`
- `POST /api/v1/radars/{id}/scan`
- `GET /api/v1/radars/{id}/scans`
- `GET /api/v1/radars/{id}/papers`
- `GET /api/v1/radars/{id}/timeline`
- `GET /api/v1/radars/{id}/trends`

UI:

- `/radars`: list and create/edit controls;
- `/radars/new`: create form;
- `/radars/{id}`: persisted overview and analysis;
- `/radars/{id}/scans`: scan history;
- `/dashboard`: HTTP redirect to `/radars` for bookmark compatibility.

Long scans run outside the request thread. The API returns the persisted scan
record and the UI polls its status. Duplicate active scans are rejected safely.

## Radar to Subscription handoff

“持续跟踪此方向” links to `/subscriptions` with allowlisted query parameters
for `topic`, `providers`, `name`, and optional `keywords`. Trend cards use their
evidence-backed phrase as a prefill. The Subscription form displays the values;
the user must submit explicitly. No Radar action silently creates a
Subscription.

## Security boundary

Radar persistence, diagnostics, HTML, logs, API responses, and documentation
must not contain API keys, authorization headers, cookies, passwords, SMTP
secrets, or institution credentials. Provider IDs are safe configuration;
secrets remain write-only in Provider Profiles/credential storage. Safe errors
are allowlisted codes such as `all_providers_failed`, `scan_failed`, and
`interrupted`.

## Deferred

CNKI, institution login, paid full-text retrieval, Zotero, LLM deep reading,
Research Gap generation, Related Work generation, Impact Factor, JCR ranking,
and automatic citation-quality ranking remain outside v1.7.

## Stage gates

Each implementation stage must independently pass `python -m pytest -q`,
`ruff check src tests`, and `git diff --check`, then be committed with explicit
file staging. Stable v1.0/v1.1 DSL files and all historical tags remain frozen.
The final v1.7 result is a Release Candidate only; no `dify-v1.7` tag is
created before manual acceptance.
