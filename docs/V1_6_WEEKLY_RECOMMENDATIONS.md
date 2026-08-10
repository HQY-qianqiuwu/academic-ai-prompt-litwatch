# Stack v1.6 Research Subscriptions and Weekly Recommendations

Status: **Stable**

Base tag: `dify-v1.5`

Base commit: `9539c56df31c1af34cfe5bb7f0ce5afb921719bb`

This document records the approved and implemented Stack v1.6 architecture.
Automated, real E2E, and final human acceptance passed; the Stable release is
identified by the annotated `dify-v1.6` tag.

## Scope

Stack v1.6 must add:

- saved research subscriptions;
- weekly schedules with weekday, local time, and IANA timezone;
- a manual **Run Now** action that uses the same run engine as scheduled work;
- SQLite persistence across LitWatch and computer restarts;
- historical paper tracking based on the existing `Paper.canonical_id`;
- search-time deduplication plus subscription-specific historical deduplication;
- subscription run, recommendation, and Dashboard delivery history;
- a Weekly Digest in the existing LitWatch Web application;
- missed-run catch-up, concurrency protection, and stale-run recovery;
- partial-Provider failure handling; and
- idempotent recommendation semantics.

Manual Search at `/` and Weekly Subscriptions are parallel capabilities. The
existing search page, Provider Registry, Provider Settings, BYOK boundary,
SSRF protection, deterministic deduplication/ranking, partial-failure behavior,
Dify integration, and stable v1.0/v1.1 DSL files must remain compatible.

Email delivery is optional in the product scope and deferred from the core
v1.6 implementation. Dashboard delivery is mandatory and must not depend on
SMTP configuration.

## Non-goals

Stack v1.6 does not add:

- CNKI or institutional-login integrations;
- full-text PDF retrieval for subscriptions;
- Zotero delivery;
- LLM paper analysis or Research Gap generation;
- Impact Factor or citation-based ranking;
- RSS retrieval;
- a general cron-expression editor;
- repeat recommendation controls such as `include_seen` or rerun; or
- hard deletion of subscription history.

The existing legacy `Pipeline` may continue serving its current Dashboard
scan behavior, but the v1.6 scheduler must not use it as a shortcut because it
constructs Provider adapters directly and has different analysis semantics.

## Existing architecture audit

The design reuses these concrete components:

| Component | Current location | v1.6 boundary |
|---|---|---|
| `Paper` and `canonical_id` | `src/litwatch/models.py`, `src/litwatch/text.py` | Reuse as the only paper identity and metadata model. |
| `LiteratureSearchService` | `src/litwatch/services/literature_search.py` | Required retrieval boundary for manual, scheduled, and catch-up runs. |
| Provider Registry and Profile | `src/litwatch/sources/registry.py`, `src/litwatch/provider_config.py` | Reuse Provider construction, selection, BYOK references, and failure isolation. |
| Search-time deduplication | `src/litwatch/services/deduplication.py` | Reuse DOI/canonical-ID/title grouping and deterministic metadata merge. |
| Search ranking | `src/litwatch/services/search_ranking.py` | Reuse backend ordering before historical filtering. |
| SQLite database | `src/litwatch/db.py` | Extend additively; retain existing `papers`, `runs`, and `paper_topics`. |
| FastAPI/Jinja/vanilla JS Web | `src/litwatch/web.py`, `templates/`, `static/` | Extend the same application; do not create a second Web stack. |
| Legacy Dashboard | `GET /dashboard` | Preserve current functionality while adding subscription views. |

The current `papers` table already uses `canonical_id` as its primary key and
stores global `first_seen_at`/`last_seen_at`. The current `runs` and
`paper_topics` tables describe legacy Pipeline scans, not subscription
occurrences. v1.6 therefore adds subscription-specific tables instead of
changing the meaning of historical rows.

The current `Database` opens SQLite with `check_same_thread=False`, enables WAL,
and initializes schema with idempotent `CREATE TABLE IF NOT EXISTS` statements.
Stage 2 must introduce an explicit additive schema-version/migration mechanism
before creating the v1.6 tables. Existing databases must upgrade in place with
no destructive rebuild.

Provider Profiles and credentials are currently process-local. Subscriptions
store Provider identifiers only. They must never copy a credential, API key,
authorization header, or Provider Profile secret into SQLite.

## Architecture

```text
SchedulerService
    -> SubscriptionService
        -> LiteratureSearchService
            -> Provider Registry / selected Providers
            -> search-time deduplication
            -> deterministic ranking
        -> HistoricalPaperService
            -> global papers by canonical_id
            -> per-subscription seen state
        -> RecommendationService
            -> new, never-recommended papers only
        -> DeliveryService
            -> persisted Dashboard Weekly Digest
        -> existing LitWatch Dashboard / subscription pages
```

`SchedulerService` decides what occurrence is due and acquires a durable run
lease. It never imports or calls OpenAlex, Semantic Scholar, arXiv, or Crossref.

`SubscriptionService` owns subscription CRUD, enable/disable, Run Now, and the
orchestration of one claimed run. Both scheduled and manual runs call one
internal run path.

`LiteratureSearchService` remains authoritative for Provider selection,
failure isolation, candidate budgeting, search-time deduplication, metadata
merge, and ranking. A subscription passes its saved `topic`, `search_limit`,
and `providers` to `LiteratureSearchService.search`.

`HistoricalPaperService` performs transactional persistence and determines
which canonical IDs have never been seen for that subscription. It enriches
global paper metadata without creating another Paper identity.

`RecommendationService` selects at most `recommendation_limit` new papers in
the order returned by `LiteratureSearchService`. A database uniqueness
constraint, not only an in-memory check, prevents repeat recommendations.

`DeliveryService` creates a persistent Dashboard delivery for every completed
successful or partial-success run, including runs with zero new papers. Email
can later implement the same interface without changing retrieval or history.

## Data model

All timestamps are stored as UTC ISO-8601 values. JSON columns contain only
non-secret structured values. Foreign keys must be enabled for every SQLite
connection.

### `subscriptions`

| Column | Meaning |
|---|---|
| `id TEXT PRIMARY KEY` | Stable generated subscription identifier. |
| `name TEXT NOT NULL` | User-facing saved-topic name. |
| `topic TEXT NOT NULL` | Query passed to `LiteratureSearchService`. |
| `keywords_json TEXT NOT NULL` | Optional normalized supporting keywords. |
| `providers_json TEXT NOT NULL` | Ordered unique Provider IDs, never credentials. |
| `search_limit INTEGER NOT NULL` | Candidate/result limit requested from search. |
| `recommendation_limit INTEGER NOT NULL` | Maximum new papers in one digest. |
| `frequency TEXT NOT NULL` | v1.6 accepts only `weekly`. |
| `weekday INTEGER NOT NULL` | Python/ISO-style index: Monday `0` through Sunday `6`. |
| `local_time TEXT NOT NULL` | Valid `HH:MM` wall-clock time. |
| `timezone TEXT NOT NULL` | Valid IANA name such as `Asia/Shanghai`. |
| `enabled INTEGER NOT NULL` | Soft enable/disable flag. |
| `created_at TEXT NOT NULL` | UTC creation time. |
| `updated_at TEXT NOT NULL` | UTC last configuration change. |
| `last_run_at TEXT` | UTC completion time of the latest attempt of any outcome. |
| `last_success_at TEXT` | UTC completion time of latest success/partial success. |
| `next_run_at TEXT` | Next scheduled occurrence in UTC. |

Validation requires a nonblank name/topic, unique runnable Provider IDs,
`search_limit >= recommendation_limit >= 1`, `frequency=weekly`, a valid
weekday/time, and a resolvable IANA timezone. Disabling a subscription keeps
all rows and prevents new scheduled claims. Re-enabling recomputes the next
occurrence without deleting history.

### Existing `papers`

The existing table remains the canonical metadata store:

- `canonical_id` remains the primary key and comes from the existing Provider
  normalization/deduplication path;
- richer abstracts and missing metadata may enrich an existing row;
- source provenance is unioned rather than replaced;
- an enrichment never changes a paper into a new paper; and
- Provider/LLM guesses must not create factual metadata.

Stage 3 must add repository behavior needed for conservative enrichment. It
must not introduce `subscription_papers.paper_id`, a second hash identity, or a
second Paper table.

### `subscription_papers`

| Column | Meaning |
|---|---|
| `subscription_id TEXT NOT NULL` | References `subscriptions(id)`. |
| `canonical_id TEXT NOT NULL` | References existing `papers(canonical_id)`. |
| `first_seen_at TEXT NOT NULL` | First UTC observation for this subscription. |
| `last_seen_at TEXT NOT NULL` | Most recent UTC observation for this subscription. |
| `first_recommended_at TEXT` | First recommendation time, null until recommended. |
| `last_run_id TEXT NOT NULL` | Most recent subscription run that observed it. |
| `seen_count INTEGER NOT NULL` | Number of completed observations. |

Primary key: `(subscription_id, canonical_id)`.

This table defines per-subscription novelty. Global `papers.first_seen_at` is
not sufficient because the same paper can be new to one subscription and old
to another.

### `subscription_runs`

| Column | Meaning |
|---|---|
| `id TEXT PRIMARY KEY` | Stable run identifier. |
| `subscription_id TEXT NOT NULL` | Owning subscription. |
| `run_key TEXT NOT NULL UNIQUE` | Durable idempotency key. |
| `trigger TEXT NOT NULL` | `scheduled`, `catch_up`, or `manual`. |
| `scheduled_for_at TEXT` | UTC scheduled occurrence; null for manual runs. |
| `period_key TEXT` | Local weekly period, for diagnostics. |
| `status TEXT NOT NULL` | `pending`, `running`, `success`, `partial_success`, `failed`, or `stale`. |
| `attempt_count INTEGER NOT NULL` | Claim/recovery attempts for this same run row. |
| `lease_owner TEXT` | Opaque process instance identifier, not a credential. |
| `lease_expires_at TEXT` | UTC concurrency lease expiry. |
| `started_at`, `heartbeat_at`, `finished_at` | UTC lifecycle timestamps. |
| count columns | Raw, unique, previously seen, new, and recommended counts. |
| `provider_status_json TEXT NOT NULL` | Safe `ProviderSearchStatus` summaries. |
| `error_code TEXT` | Stable sanitized category, never raw secret-bearing text. |

Scheduled and catch-up work use a deterministic `run_key` derived from the
subscription ID and exact scheduled UTC occurrence. A manual run uses a fresh
opaque request ID. Failed/stale retries reclaim the same scheduled row and
increment `attempt_count`; they do not create a second occurrence.

### `recommendations`

| Column | Meaning |
|---|---|
| `id TEXT PRIMARY KEY` | Stable recommendation record. |
| `subscription_id TEXT NOT NULL` | Owning subscription. |
| `canonical_id TEXT NOT NULL` | Recommended existing paper. |
| `subscription_run_id TEXT NOT NULL` | First run that recommended it. |
| `rank INTEGER NOT NULL` | Stable order within that run. |
| `score REAL NOT NULL` | Existing deterministic rank score snapshot. |
| `score_detail_json TEXT NOT NULL` | Non-secret score explanation snapshot. |
| `recommended_at TEXT NOT NULL` | UTC creation time. |

Unique constraint: `(subscription_id, canonical_id)`. This is the final
idempotency barrier against recommending the same paper again by default.

### `deliveries`

| Column | Meaning |
|---|---|
| `id TEXT PRIMARY KEY` | Stable delivery record. |
| `subscription_id TEXT NOT NULL` | Owning subscription. |
| `subscription_run_id TEXT NOT NULL` | Source run. |
| `channel TEXT NOT NULL` | v1.6 core uses `dashboard`. |
| `status TEXT NOT NULL` | `pending`, `delivered`, or `failed`. |
| `digest_json TEXT NOT NULL` | Render-independent, non-secret digest snapshot. |
| `created_at`, `delivered_at` | UTC timestamps. |
| `error_code TEXT` | Sanitized channel error category. |

Unique constraint: `(subscription_run_id, channel)`. Rebuilding the page does
not create a second delivery. Email, if implemented later, uses `channel=email`
and separate environment-only SMTP secrets.

## Historical deduplication

v1.6 has two distinct deduplication layers.

### Search-time deduplication

The existing `LiteratureSearchService` retrieves Provider candidates, then the
existing deduplication service merges duplicate DOI/canonical-ID/title groups
and deterministic ranking orders the merged Papers. For example, an OpenAlex
and Crossref representation of the same DOI becomes one `Paper` whose
`sources` records both Providers.

### Historical deduplication

Inside one SQLite transaction, the run engine:

1. loads existing `(subscription_id, canonical_id)` rows for the ranked result;
2. classifies IDs absent from that set as new;
3. upserts/enriches the global `papers` rows;
4. inserts or updates `subscription_papers` timestamps and counts;
5. attempts recommendation inserts only for new IDs, in current ranked order;
6. relies on `UNIQUE(subscription_id, canonical_id)` in `recommendations`; and
7. commits paper history, recommendations, delivery snapshot, and final counts
   atomically.

If a previously seen DOI later gains an abstract, venue, source, or other real
metadata, the global Paper is enriched and `last_seen_at` advances. It remains
historically seen and is not recommended again.

## New paper definition

For v1.6:

```text
new paper = canonical_id has never been seen for this subscription
```

Publication year is not a novelty signal. `year == current year` is explicitly
invalid as the definition of this week's new papers.

`subscription_papers.first_seen_at`, `last_seen_at`, and
`first_recommended_at` provide the auditable lifecycle. A new paper beyond the
recommendation limit is marked seen but not recommended; v1.6 does not silently
carry it into a later week because that would make recommendation timing
non-deterministic. The run/digest counts still expose that it was new but not
selected. A future explicit backlog policy would require a separate design.

## Scheduler and timezone semantics

The v1.6 scheduler supports only weekly frequency:

- `weekday`: Monday `0` through Sunday `6`;
- `local_time`: `HH:MM`;
- `timezone`: an IANA `zoneinfo.ZoneInfo` name;
- `next_run_at`: the computed UTC instant persisted in SQLite.

Schedule calculation occurs from local wall time and converts to UTC for
storage and comparison. Display converts UTC back through the saved timezone.
For an ambiguous daylight-saving time, choose the earlier valid instant
(`fold=0`). For a nonexistent local time, advance to the first valid local
minute on that date. These rules must be unit-tested even though the initial
target timezone `Asia/Shanghai` has no current DST transition.

The scheduler is an in-process coordinator started by the existing FastAPI
lifespan. It uses a bounded polling interval and has explicit start/stop hooks
for tests and shutdown. It reads only enabled, due subscriptions and delegates
execution to `SubscriptionService`. It must not perform network calls while
holding a SQLite write transaction.

Manual **Run Now** uses the same orchestration but a manual run key. It does not
move or consume the next scheduled occurrence. Historical and recommendation
idempotency rules still apply.

## Missed-run catch-up

At startup and on each scheduler poll:

1. find enabled subscriptions with `next_run_at <= now_utc`;
2. derive the deterministic run key for that missed occurrence;
3. atomically insert/claim its one `subscription_runs` row;
4. run it with trigger `catch_up` when no successful/partial-success completion
   exists for that occurrence; and
5. advance `next_run_at` to the first weekly occurrence after `now_utc` only
   after the due occurrence has been durably accounted for.

If the computer starts Monday after a Sunday 08:00 schedule, that Sunday
occurrence runs once. Multiple scheduler polls or process restarts cannot
create duplicate runs because the run key is unique. Older missed weeks are not
replayed as an unbounded backlog in v1.6; one latest due occurrence is caught
up, and the schedule advances to the next future occurrence.

An all-Provider failure keeps `last_success_at` unchanged and leaves the same
scheduled run eligible for bounded later retry. It does not create another
weekly occurrence.

## Concurrency and stale-run recovery

Claims use a short `BEGIN IMMEDIATE` transaction:

- insert the deterministic run row or load the existing row;
- skip a `running` row whose lease is still valid;
- claim `pending`, `failed`, or expired `running` work with a new
  `lease_owner`, expiry, and incremented attempt count; and
- commit before external Provider requests begin.

Only the lease owner may heartbeat or finalize the run. A unique run key and
conditional status/lease update prevent two scheduler threads, Web requests,
or LitWatch processes from executing the same scheduled occurrence
concurrently.

If a process exits while a run is `running`, another process marks it `stale`
after the lease expires and reclaims that same row. Final persistence is one
transaction. If a crash happens after recommendations are committed but before
an acknowledgement reaches the caller, uniqueness constraints make recovery a
no-op for already recommended papers and delivery channels.

Waits and retry attempts are bounded. The scheduler never spins indefinitely
and never holds a process-only lock as the sole correctness mechanism.

## Idempotency

Example:

```text
Run 1 result: A B C
new/recommended: A B C

Run 2 result: A B C D E
previously seen: A B C
new/recommended: D E
```

Correctness is enforced at three levels:

1. one `subscription_runs.run_key` per scheduled occurrence;
2. one `subscription_papers` row per subscription/canonical ID; and
3. one `recommendations` row per subscription/canonical ID.

The service may recompute the same sets during recovery, but database
constraints and transactional writes keep observable history idempotent.
v1.6 has no override for recommending A/B/C again.

## Failure model

Provider outcomes come from the existing safe `ProviderSearchStatus` values.

| Retrieval outcome | Run status | Persist papers/digest | Update `last_success_at` |
|---|---|---|---|
| All selected Providers succeed or return empty | `success` | Yes | Yes |
| At least one succeeds/empty and at least one fails | `partial_success` | Yes | Yes |
| All selected Providers fail | `failed` | No paper/recommendation delivery; persist safe run diagnostics | No |

A partial-success run still stores successful results, applies historical
deduplication, recommends new papers, and creates the Dashboard digest. The
digest clearly lists unavailable/rate-limited Providers without raw exception
text or upstream response bodies.

An all-Provider empty result is a successful run with a zero-new-paper digest.
An all-Provider failure remains retryable and never masquerades as an empty
successful search.

## Delivery model

Dashboard delivery is the v1.6 required channel. The digest snapshot contains:

- subscription identity and schedule display;
- run status and safe Provider diagnostics;
- raw candidate, unique, previously seen, new, and recommended counts;
- ordered recommendation canonical IDs and score snapshots; and
- generated/delivered UTC timestamps.

The Dashboard renders the persisted snapshot and joins current Paper metadata
for cards. It does not re-run retrieval merely because a user opens a page.

Email is **optional and deferred**. The core release must be complete without
SMTP. If a later Stage 8 explicitly enables it, SMTP credentials remain in
environment variables, email failures do not roll back Dashboard delivery,
and the existing recommendation/delivery idempotency constraints still apply.

## Web and Dashboard design

Extend the existing FastAPI/Jinja2/vanilla JavaScript application with:

- **Subscriptions** list: saved topics, enabled state, schedule, last/next run,
  recent counts, and actions for View, Run Now, Edit, and Disable;
- **Subscription detail**: configuration, Provider selection, paper history,
  first/last seen timestamps, and first recommendation time;
- **Run history**: status, trigger, attempts, safe Provider diagnostics, counts,
  and timestamps; and
- **Weekly Digest**: the persisted recommendation cards and run summary.

Example summary:

```text
TDOA Weekly
Every Sunday 08:00
Asia/Shanghai

30 candidates
27 unique
19 previously seen
8 new
5 recommended

[View Digest] [Run Now] [Edit] [Disable]
```

Disable is the primary removal behavior. v1.6 does not expose hard deletion of
a subscription with history. POST actions use normal validation and safe error
messages. Run Now must return busy/already-running semantics rather than start
a concurrent duplicate.

The existing Manual Search remains `/`. Existing `/provider-settings` and
`/dashboard` remain available. Route names for new pages and APIs are finalized
in Stage 6 only after service contracts and tests exist.

## Security

Subscription, scheduler, run, recommendation, delivery, and diagnostic data
must not contain:

- Provider API keys or credential values;
- SMTP or institution passwords;
- Authorization/Bearer headers;
- `.env` content;
- raw upstream bodies or URLs containing credentials; or
- unsanitized exception text.

Subscriptions reference Provider IDs and reuse the existing Registry/Profile
credential boundary at execution time. Provider Base URL SSRF validation stays
authoritative. UI/API serializers expose only safe status/error categories.
Logs use subscription/run IDs and redacted Provider diagnostics.

## Stage plan

### Stage 0 - Branch and baseline

- preserve `dify-v1.5` and all historical tags;
- retain the old v1.4-only weekly branch as
  `backup/weekly-recommendations-v14-baseline`;
- create `feat/v1.6-weekly-recommendations` from `dify-v1.5`; and
- pass the v1.5 regression gate.

### Stage 1 - Design and persistence architecture

- freeze this scope, schema, state machine, scheduling, security, and test plan;
- record the latest stable/current development handoff; and
- implement no subscription business code.

### Stage 2 - Subscription persistence

- add additive schema migrations and subscription repository/model validation;
- add CRUD, enable/disable, and restart-persistence tests; and
- leave scheduling and retrieval inactive.

### Stage 3 - Historical paper tracking

- add conservative global Paper enrichment and `subscription_papers` history;
- prove canonical-ID reuse and per-subscription novelty; and
- test richer repeat metadata without repeat novelty.

Implementation completed on `feat/v1.6-weekly-recommendations`:

- migration 2 adds `papers.normalized_title` and the composite-key
  `subscription_papers` relation without replacing or rebuilding existing
  paper/subscription data;
- `HistoricalPaperService.observe_papers_for_subscription(...)` performs
  search-result deduplication first, then delegates one atomic paper/history
  observation to `HistoricalPaperRepository`;
- historical matching reuses the v1.4 DOI normalization, canonical ID,
  normalized-title, conservative near-title, and deterministic metadata merge
  primitives; conflicting non-empty DOIs remain separate;
- global and per-subscription `first_seen_at` values are preserved while
  `last_seen_at` advances on later real observations, and novelty is scoped to
  `(subscription_id, canonical_id)`;
- repeat metadata can enrich a stored paper without changing its established
  historical canonical ID or making it new again; and
- the relation persists `seen`/`recommended` state and recommendation score
  fields for Stage 4, but Stage 3 does not execute recommendations, runs,
  scheduling, delivery, or UI behavior.

The Stage 3 gate is 216 passed tests, Ruff PASS, `git diff --check` PASS, and
unchanged v1.0/v1.1 Dify DSL files.

### Stage 4 - Subscription run engine

- orchestrate `LiteratureSearchService`, historical filtering,
  RecommendationService, and Dashboard DeliveryService;
- implement success, partial-success, failed, and zero-new outcomes; and
- prove recommendation idempotency transactionally.

### Stage 5 - Scheduler, catch-up, and concurrency

- implement UTC/IANA weekly calculation, due polling, Run Now, leases,
  heartbeats, stale recovery, and one-occurrence catch-up;
- integrate bounded startup/shutdown with FastAPI lifespan; and
- add deterministic clock and concurrent-claim tests.

### Stage 6 - Subscription Web UI

- add list, create/edit, detail, Run Now, enable/disable, and run-history views;
- preserve Manual Search and Provider Settings; and
- add responsive/accessibility and safe-error tests.

### Stage 7 - Dashboard Delivery and Weekly Digest

- render persisted digest snapshots and recommendation cards;
- expose partial Provider diagnostics and count arithmetic; and
- verify page loads never trigger retrieval.

### Stage 8 - Optional Email

- deferred by default;
- begin only after the Dashboard release path is complete and an explicit
  scope review confirms SMTP will not delay v1.6.

Stage 8 decision: **DEFERRED**. The legacy notifier reads SMTP credentials
directly from environment-backed Settings and is not integrated with the v1.6
subscription/delivery model. A safe product implementation would additionally
require write-only credential configuration, isolated delivery retries, safe
error reporting, and dedicated UI/tests. Dashboard Delivery is the complete
v1.6 delivery path; no SMTP secret is persisted in SQLite, returned by an API,
embedded in HTML/DSL, or written to logs.

### Stage 9 - Regression and real E2E

- run full offline tests, Ruff, diff checks, restart persistence, catch-up,
  concurrency, stale recovery, partial failure, and real Provider searches;
- perform browser E2E for subscription creation, Run Now, repeat run,
  disable/enable, run history, and Weekly Digest; and
- verify existing Search, Settings, Dify, BYOK, SSRF, ranking, and DSL behavior.

### Stage 10 - Release Candidate

- update release evidence without claiming unverified outcomes;
- push the RC branch for manual acceptance; and
- create no Stable tag until final human E2E approval.

## Stable implementation status

Stages 0 through 10 are complete on
`feat/v1.6-weekly-recommendations` as independent checkpoints:

- subscription persistence and per-subscription historical paper tracking;
- a `SubscriptionRunService` that reuses `LiteratureSearchService`, preserves
  existing ranking order, records provider-safe status, and persists
  idempotent runs and recommendations;
- weekly IANA-timezone scheduling, one-occurrence catch-up, active-run leases,
  stale-run recovery, and bounded FastAPI background lifecycle;
- subscription create/edit/disable/detail/Run Now Web UI in the existing
  FastAPI/Jinja2/vanilla JavaScript application;
- immutable, idempotent Dashboard deliveries and historical Weekly Digests;
- real TDOA, OFDM, partial-provider-failure, second-run suppression, and
  restart-persistence E2E evidence; and
- regression protection for Manual Search, Provider Settings, Dify, BYOK,
  SSRF, and the stable v1.0/v1.1 DSL files.

The UI additionally defaults to Simplified Chinese (`zh-CN`) and supports an
English (`en`) switch through the non-sensitive `litwatch.locale` browser
preference. Localization is restricted to templates, static JavaScript, and
CSS. Provider names and paper title/abstract/authors/venue/DOI remain original
metadata, while Provider/run enums and database contracts remain unchanged.

The final Stable gate has 250 passing tests, Ruff PASS, and
`git diff --check` PASS. Dashboard delivery is complete. Optional email
delivery remains deferred because a safe product implementation requires
write-only SMTP configuration and isolated retry/error handling. Final manual
acceptance passed for Manual Search, Research Subscription, Run Now, Run
History, Weekly Digest, historical deduplication, immediate duplicate
suppression, restart persistence, and post-restart historical deduplication.

## Test strategy

Offline tests must use injected clocks and fake `LiteratureSearchService`
results. They must cover:

- additive migration of an existing v1.5 SQLite database;
- subscription validation and restart persistence;
- global Paper enrichment and per-subscription first/last seen state;
- repeat-run and crash-recovery idempotency;
- recommendation-limit behavior;
- success, empty, partial-success, and all-failed run transitions;
- UTC conversion, DST ambiguity/nonexistence, and next-run calculation;
- Sunday-to-Monday catch-up exactly once;
- simultaneous scheduler/manual claims and expired-lease recovery;
- Dashboard delivery uniqueness and zero-new digests;
- secret-free rows, API responses, diagnostics, and logs; and
- unchanged Manual Search, Provider Settings, Dify API, BYOK, SSRF,
  deduplication, ranking, and partial-failure tests.

Real E2E must demonstrate:

1. create a weekly subscription and retain it across LitWatch restart;
2. Run Now returns real literature and a Dashboard digest;
3. running the same result set again produces no repeat recommendations;
4. a later new canonical ID is the only new recommendation;
5. one Provider failure yields partial success and a useful digest;
6. all Provider failure leaves `last_success_at` unchanged;
7. a missed weekly occurrence catches up once after restart;
8. concurrent triggers do not create duplicate runs/recommendations; and
9. disabling prevents scheduled work without removing history.

## Acceptance criteria

Stack v1.6 cannot become Stable until all of the following pass:

- saved weekly subscriptions persist across restart;
- Scheduler and Run Now both call `LiteratureSearchService`, never Providers
  directly;
- `canonical_id` is the only paper identity across search and history;
- historical enrichment does not produce repeat recommendations;
- recommendation rows are idempotent under repeat, concurrent, and recovered
  execution;
- weekly UTC/IANA schedule, catch-up exactly once, and stale recovery pass;
- partial Provider failure saves results/digest, while all failure does not
  update `last_success_at`;
- Dashboard Weekly Digest is complete without email configuration;
- Manual Search and Weekly Subscription coexist in the same Web application;
- existing Provider Registry, Provider Settings, BYOK, SSRF, deduplication,
  ranking, partial failure, and Dify integration regressions pass;
- `dify/workflows/literature-search-v1.0.yml` and
  `dify/workflows/literature-search-v1.1.yml` remain unchanged; and
- release documentation clearly distinguishes automated, real E2E, and manual
  verification.
