# Task 1 Report: Python-default navigation and runtime behavior

## Scope expansion

The original task called for Python Analysis and Jobs navigation, but the
application had no local pages for those destinations. The reviewed scope was
expanded to add minimal local `/analysis` and `/jobs` workspaces. These pages
use only the existing Python paper-analysis/jobs APIs and do not implement a
workflow editor or move business logic into the browser.

## RED / GREEN evidence

- RED: `pytest tests/test_ui_localization.py tests/test_local_ui_navigation.py -q`
  initially failed as expected: navigation labels and local pages were absent,
  the Dify `http://localhost` link remained, and `GET /api/v2/jobs` returned
  405.
- GREEN: the same focused command passed with `10 passed` after the minimal
  routes, navigation, and safe job-list projection were added.

## Delivered behavior

- Every dynamic primary navigation includes local `/analysis` and `/jobs`
  links, keeps Search/Radar/Subscriptions/Digests/Provider Settings, and no
  longer requires the Dify localhost link.
- `/analysis` submits a typed `paper_analysis` job with canonical paper ID,
  topic ID, and allowed evidence scope to `POST /api/v2/jobs`, then displays
  the job and result-reference state.
- `/jobs` uses `GET /api/v2/jobs` to show safe job projections, refreshes the
  list, and cancels queued/running jobs through the existing cancel endpoint.
- The added list endpoint returns `JobResponse` projections only; payloads,
  idempotency keys, and credential material remain excluded.
- zh-CN and English labels were added while keeping the existing locale switch.

## Verification

- `pytest tests/test_job_api.py tests/test_paper_analysis_api.py tests/test_web_static.py tests/test_ui_localization.py tests/test_local_ui_navigation.py -q` — 30 passed.
- `pytest -q` — 544 passed (one pre-existing TestClient deprecation warning).
- `ruff check src tests` — passed.
- `git diff --check` — passed.

## Constraints / concerns

- No Dify/DSL/stable/.env/protected/.learnings files were changed.
- `.learnings/` remains an unrelated untracked workspace item and is excluded
  from staging.
- The analysis workspace intentionally accepts existing identifiers as text;
  the application has no reviewed general paper/topic picker API to expose.

## G1 reliability fix — round 1/5

### RED / GREEN evidence

- RED: focused tests demonstrated that `GET /api/v2/jobs` returned an
  unbounded array (with a fixed repository cap), accepted invalid pagination,
  the analysis form bypassed native required validation, and a second submit
  could start another request while the first was pending.
- GREEN: pagination, submission, and cancellation focused tests passed after
  the minimal changes. The final focused command passed with 35 tests; the full
  test suite passed with 549 tests.

### Delivered reliability changes

- `GET /api/v2/jobs` now accepts validated `limit` (1–100, default 25) and
  non-negative `offset`, returning deterministic `created_at DESC, job_id DESC`
  pages with `items`, `total`, and `has_more`. Older jobs remain reachable and
  every item remains a safe `JobResponse` projection.
- The Jobs workspace loads pages and exposes previous/next controls.
- Analysis submission uses a normalized submission fingerprint to retain one
  idempotency key for retries. It disables the submit control while in flight,
  clears the retained key after confirmed success or input changes, and uses
  browser-native required-field validation.
- A pending cancellation is shown as requested and has no repeat cancel
  control; the cancel button disables immediately on the first action.

### Verification

- `pytest tests/test_job_api.py tests/test_analysis_workspace.py tests/test_local_ui_navigation.py tests/test_ui_localization.py tests/test_paper_analysis_api.py tests/test_web_static.py -q` — 35 passed.
- `pytest -q` — 549 passed (one TestClient deprecation warning).
- `ruff check src tests` — passed.
- `git diff --check` — passed.
