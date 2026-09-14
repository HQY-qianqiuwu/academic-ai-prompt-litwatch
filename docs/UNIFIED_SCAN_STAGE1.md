# Unified literature scan: stage 1

This stage introduces one in-memory scan outcome without moving subscription
history, email, AI analysis, or publishing into the scan layer.

## Call paths

- FastAPI `POST /api/v1/literature/search` → `ScanService.scan` →
  `LiteratureSearchService.search` → configured Providers → normalization,
  same-scan deduplication and ranking → `ScanResult` → HTTP response.
- FastAPI scheduler → `SubscriptionRunService.run` → the same `ScanService` →
  historical observation and recommendation policy → `DeliveryService` → email.
- Legacy CLI `litwatch scan` → `Pipeline.run` → `ScanService` → legacy topic
  policy, persistence, and independent `PaperAnalysisService`.

`ScanService` holds no SQLite connection and performs no delivery or AI call.
`LiteratureSearchService` remains the only Provider search implementation;
existing normalization, deduplication, and ranking helpers are reused rather
than copied into each entry point. Search never requires an AI key.

## Status contract

| Scan status | Meaning | HTTP / CLI behavior |
| --- | --- | --- |
| `success` | A Provider worked and selected papers exist | HTTP 200 / CLI 0 |
| `success_empty` | A Provider worked but no papers were selected | HTTP 200 / CLI 0 |
| `partial_success` | A Provider worked and another attempted Provider failed | HTTP 200 / CLI 0 |
| `all_providers_failed` | No attempted Provider worked | HTTP 502, or 504 if all attempts timed out / CLI 1 |

An enabled Provider requiring a missing credential is marked
`skipped_unconfigured` when another selected Provider can run. A skipped
Provider is not counted as a successful or failed attempt. If none of the
selected Providers can be built, the existing configuration error is preserved
(HTTP 422). Unknown or disabled explicit selections remain configuration
errors. By default, the three anonymous-capable Providers OpenAlex, arXiv, and
Crossref are selected; Semantic Scholar remains opt-in.

The default profile and `/api/v1/providers` capability metadata agree, so the
interactive UI selects the same fallback set. The UI reports skipped Providers
without treating them as partial failures.

## Persistence and compatibility

The `ScanResult` is intentionally in-memory in this stage. Existing SQLite
repositories retain ownership of runs, subscriptions, historical papers, and
analysis. The FastAPI scheduler and request handlers share the application's
existing `Database` instance, its transaction lock, and WAL mode; the CLI uses
its own `Database` instance. This stage introduces no new shared connection or
schema migration.

The legacy `Pipeline` keeps its topic-specific policy and analysis adapter for
compatibility; it does not implement Provider retrieval. The subscription
service keeps historical deduplication, recommendation limits, and email
delivery, but consumes scan scores and status instead of recalculating them.

## Deferred work

Workflow cleanup (`weekly.yml` and the future role of `pages.yml`), persistent
`scan_id` / `paper_id` linkage for Search and Analyze, BYOK documentation and
API refinement, and any broader legacy Pipeline decomposition belong to a
later stage. Docker is not part of the current deployment path. Do not merge
this branch into `main` before review.
