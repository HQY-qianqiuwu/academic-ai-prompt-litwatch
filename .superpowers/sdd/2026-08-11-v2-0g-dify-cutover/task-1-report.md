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
