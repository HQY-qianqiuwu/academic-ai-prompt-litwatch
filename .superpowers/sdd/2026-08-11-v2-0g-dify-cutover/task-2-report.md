# Task 2 Report: Dify-free lifecycle scripts

## RED / GREEN evidence

- Initial controlled PowerShell shim run: `12 failed, 1 passed`. The failures
  proved that default start called Docker before inspecting the port, default
  stop resolved Dify after stopping LitWatch, default status required
  Docker/Dify/SSRF proxy, the Python browser URL was unreachable, and explicit
  legacy scripts and launchers did not exist.
- Initial GREEN: `13 passed` after the default lifecycle became Python-only and
  the old full-stack behavior moved to explicit legacy files.
- Smoke exposed a Windows PowerShell REST-array projection defect in Provider
  Registry detail. A focused regression test first failed with
  `runnable=True False`; explicit provider enumeration fixed it.
- Final lifecycle test command: `python -m pytest tests/test_lifecycle_scripts.py -q`
  passed with `14 passed`.

## Delivered behavior

- `start-stack.ps1`, `status-stack.ps1`, and `stop-stack.ps1` contain no Docker,
  Dify, compose, or SSRF-proxy calls. Controlled command shims fail immediately
  if any default script reaches those legacy dependencies.
- Default start binds LitWatch to `127.0.0.1`, opens
  `http://127.0.0.1:8000/`, validates Python-default runtime mode, validates the
  Provider Registry/OpenAlex adapter, and reports the in-process Job
  Worker/Scheduler lifecycle.
- Python resolution is fail-closed: use explicit `LITWATCH_PYTHON` first,
  otherwise only the current repository `.venv\Scripts\python.exe`. PATH and
  other checkouts are never implicit fallbacks. Before launch, `litwatch.web`
  must resolve exactly to the current v2.0 worktree `src\litwatch\web.py`.
- Each port has a repository-local managed PID record. Warm start accepts only
  that PID with the exact current-repository LitWatch command. Start and stop
  reject missing, stale, mismatched, or foreign ownership and never stop an
  unknown process. A failed cold start cleans up only the PID it just launched,
  after revalidating its command.
- Status reports Migration Mode, Python Runtime, LitWatch, Provider Registry,
  Job Worker/Scheduler, and `System READY` without legacy probes.
- The previous full Docker/Dify/SSRF-proxy lifecycle remains opt-in in
  `start-legacy-dify-stack.ps1` and `stop-legacy-dify-stack.ps1`, with explicit
  root Chinese launchers. Legacy stop continues to use `docker compose stop`;
  volumes and historical assets are preserved.

## Safe smoke evidence

- Default port 8000 was already owned by PID `37408`, whose command invokes
  `D:\DIfy文献自动查找\academic-ai-prompt-litwatch\.venv\Scripts\litwatch.exe` from
  the protected main v1.7 checkout. This task classified the real default-port
  smoke as **BLOCKED SMOKE**, failed closed, and did not stop or modify that
  process.
- Default status on port 8000 returned `System NOT READY`; default stop returned
  nonzero with `Refusing to stop it`. A post-check confirmed PID `37408` and its
  original command were unchanged.
- No virtual environment or dependencies were installed. An explicit trusted
  Python (`C:\Users\19075\miniconda3\python.exe`) passed the exact v2 import-path
  validation for guarded alternate-port smoke on free port 18080.
- Cold start PID `24884`: ready; warm start: same PID and idempotent; status:
  all five checks PASS and System READY; stop: PID `24884` only; restart PID
  `51928`: ready; final stop: PID `51928` only.
- Final post-check: port 18080 had zero listeners and
  `data\litwatch-stack-18080.pid` was absent.

## Verification

- `python -m pytest -q`: `563 passed`, with one pre-existing Starlette/httpx
  deprecation warning.
- `python -m ruff check src tests`: passed.
- PowerShell parser: all six changed/created `.ps1` lifecycle scripts passed.
- `git diff --check`: passed.
- Stable Dify DSL diff: empty.
- No `.env`, Dify asset, stable release document, or protected file was changed.
  The unrelated untracked `.learnings/` directory remained untouched and is
  excluded from staging.

## Concern

- Port 8000 remains intentionally unavailable to the v2.0 lifecycle while the
  protected v1.7 process owns it. A real v2.0 default-port cold start can be run
  only after that process is stopped by its owner through an authorized v1.7
  lifecycle action.
