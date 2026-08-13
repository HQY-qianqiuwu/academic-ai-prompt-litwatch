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

## G2 review fix round 1

### RED / GREEN evidence

- Exact ownership, TOCTOU, and interpreter-policy regressions first produced
  `5 failed, 1 passed`. After the implementation, the lifecycle suite passed.
  The cases cover a foreign `src` path that merely contains the expected path,
  a port-prefix spoof, an owner that changes between inspection and stop, a
  default-port external interpreter, and a non-default external interpreter
  without the explicit smoke switch. A same-command/reused-PID regression also
  verifies that a different creation time is rejected.
- Live component-health regressions first produced `7 failed`. GREEN exposes
  and consumes `migration_verified`, `runtime_started`,
  `job_worker_running`, `job_worker_active`, `scheduler_running`, and the safe
  `scheduler_last_error`. Simulated migration failure, stopped worker, and
  stopped scheduler all keep `System` at `NOT READY`.
- Stand-alone status/stop interpreter resolution first produced `2 failed`,
  then `2 passed` after both scripts resolved the authorized interpreter before
  ownership checks. The explicit legacy stop hardening test also went RED then
  GREEN, and legacy stop now performs the same immediate identity recheck while
  retaining `docker compose stop` and volume preservation.

### Hardened lifecycle behavior

- The managed process record is now a versioned JSON identity containing PID,
  normalized creation time, and a SHA-256 fingerprint of the exact validated
  executable/app-directory/host/port contract. Windows arguments are parsed
  with `CommandLineToArgvW`; exact token count, module, canonical source path,
  host, and port are required. Substring and port-prefix matches are rejected.
- Immediately before every managed stop, the process is fetched again and its
  PID, creation time, executable, exact arguments, and fingerprint are
  revalidated. A missing, stale, changed, or reused PID fails closed.
- Port 8000 accepts only this worktree's `.venv\Scripts\python.exe`. An external
  `LITWATCH_PYTHON` is permitted only when both
  `LITWATCH_ALLOW_EXTERNAL_PYTHON=1` and a non-default port are explicit. Exact
  `litwatch.web` import-path validation remains mandatory.
- Scheduler health uses the service's public `is_running` property backed by
  its owned thread, plus the sanitized exception type in `last_error`; it does
  not inspect private thread state from the API or scripts. Worker health and
  active count come from the live `JobWorker` instance. Migration health comes
  from the completed application database preflight, and runtime health comes
  from `ApplicationRuntime.started`.

### Guarded smoke and final verification

- No virtual environment or dependency was created or installed. With
  `LITWATCH_ALLOW_EXTERNAL_PYTHON=1` on alternate port 18080, cold start PID
  `50028`, warm start on the same PID, live status, stop, restart PID `48276`,
  and final stop all passed. Every real component-health field was healthy;
  the final port had zero listeners and no identity file.
- Port 8000 remained owned by protected v1.7 PID `37408`, created
  `2026-08-13 23:22:43`, throughout the work. Its executable and command still
  point to the protected main checkout. It was never stopped or modified, so a
  real v2 default-port smoke remains **BLOCKED SMOKE** by design.
- Focused lifecycle/runtime/scheduler/job tests: `55 passed` (one pre-existing
  Starlette/httpx deprecation warning). Full suite: `576 passed` with the same
  single warning. Ruff, all six PowerShell parser checks, and
  `git diff --check` passed. Port 18080 was clear and its identity file absent
  after verification.

## G2 review fix round 2

### RED / GREEN evidence

- Three controlled regressions first failed against the round-1 lifecycle.
  A transient null CIM result received only one lookup and aborted; complete
  identity-capture exhaustion left the just-started process running; and
  command/identity construction failure also had no cleanup path because
  `$StartedIdentity` had never been assigned.
- GREEN retains the `Start-Process -PassThru` process object immediately,
  captures its `StartTime`, and retries CIM plus exact command identity at most
  20 times with a 100 ms interval. The transient-null case succeeds on the
  second capture. Exhaustion and construction failure both exit nonzero,
  terminate only through the retained handle, wait for confirmed process exit,
  leave the port free, and leave no managed identity file.
- The existing failed-health-start regression now also proves cleanup uses the
  retained handle rather than `Stop-Process -Id`; no uncertain naked-PID stop
  occurs on any just-started cleanup path.
- A cleanup-failure regression went RED when the script removed a valid
  identity record even though handle termination failed. GREEN retains that
  exact record whenever cleanup is not confirmed, so a still-running process
  cannot become untracked.

### Process-handle safety

- Handle cleanup re-reads `Process.StartTime`, verifies it against the captured
  UTC creation identity, checks `HasExited`, calls `Kill()` on the retained
  process object, and uses bounded `WaitForExit(5000)`. It does not rediscover a
  process by PID after identity uncertainty. StartTime comparison allows only
  the sub-microsecond precision truncation observed between
  `System.Diagnostics.Process` and Windows CIM (less than one microsecond).
- Once full command identity is captured, the versioned PID/creation/fingerprint
  record remains unchanged. If a later start validation fails, the record is
  removed only when it exactly equals the identity created by that start.
  Previous spoof, TOCTOU, PID-reuse, live-health, and interpreter restrictions
  remain in force.

### Smoke and verification

- On confirmed-free alternate port 18080, the explicit external-interpreter
  smoke cold-started PID `52320`, warm-started on the same PID, reported all
  five status checks PASS and `System READY`, then stopped that recorded
  process. The final port had zero listeners and no identity file.
- Protected v1.7 PID `37408` continued to own port 8000 with its original
  creation time and main-checkout command. It was read only and never stopped.
- Lifecycle tests: `28 passed`. Full suite: `580 passed` with one pre-existing
  Starlette/httpx deprecation warning. Ruff, all six PowerShell parser checks,
  and `git diff --check` passed. No dependency or virtual environment was
  installed.

## G2 review fix round 3

### RED / GREEN evidence

- Five required controlled regressions first failed against round 2. Identity
  capture exhaustion plus retained-handle `Kill()` failure had no provisional
  record; `Process.StartTime` failure had the same gap; a pre-existing
  provisional record produced only a generic invalid-record error; successful
  capture wrote no explicit final state; and successful cleanup could not prove
  that a provisional record existed before the handle was stopped.
- GREEN passed all five scenarios, then the complete lifecycle suite passed
  with `33 passed`. The controlled handle observes `state=provisional` before
  every failed-start cleanup attempt. Confirmed exit removes that exact record;
  a failed `Kill()` retains it. A successful exact identity capture exposes
  only `state=final` by the time health validation begins.

### Provisional ownership and atomic upgrade

- Immediately after `Start-Process -PassThru`, and before any CIM or command
  identity lookup, start writes a version-1 provisional JSON record. It carries
  a unique `launch_id`, PID, nullable retained-handle start time, and the
  expected executable/app-directory/host/port contract. Therefore both capture
  exhaustion and `StartTime` acquisition failure remain visibly tracked if the
  retained process handle cannot stop the process.
- A provisional record never authorizes normal start/status/stop ownership.
  `Get-ManagedStackIdentity` rejects it with an explicit fail-closed diagnostic,
  and controlled stop proves that `Stop-Process -Id` is never reached.
- Successful CIM plus exact command validation may upgrade only the same PID,
  creation time, and exact provisional `launch_id`/contract. The final JSON is
  written to a unique same-directory temporary file and atomically replaces the
  exact provisional record with `File.Replace`; its temporary backup is then
  removed. A legacy version-1 final record without a `state` field remains
  readable as final for compatibility.
- Failed-start cleanup continues to use only the retained process object. When
  `StartTime` is available it is revalidated; when retrieval itself failed, the
  original retained handle is still used directly. Only `HasExited` or
  `Kill()` plus bounded `WaitForExit(5000)` confirms cleanup. The exact
  provisional/final record is removed only after confirmation; otherwise it is
  retained for recovery and diagnosis.

### Verification

- New round-3 regression set: `5 passed`; lifecycle suite: `33 passed`; full
  suite: `585 passed` with one pre-existing Starlette/httpx deprecation warning.
- Ruff, all six PowerShell parser checks, and `git diff --check` passed. No new
  real smoke was run in round 3. Port 18080 remained unused, and protected v1.7
  PID `37408` on port 8000 remained read-only and unchanged.
- No virtual environment or dependency was installed. No Dify/DSL, `.env`,
  stable, protected, or `.learnings/` content was changed.
