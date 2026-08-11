# V2.0C Background Job Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute long Python work outside FastAPI requests through durable, idempotent SQLite jobs.

**Architecture:** Typed jobs persist through `JobRepository`; a single-machine `JobWorker` claims leases and invokes registered handlers with cooperative cancellation.

**Tech Stack:** Python threads, sqlite3, Pydantic, FastAPI, pytest.

## Global Constraints

- No Celery, Kafka, RabbitMQ, or distributed coordination.
- Payloads store credential references, never secrets.
- API creation returns 202 and never performs long work inline.

---

### Task 1: Job model and repository

**Files:**
- Create: `src/litwatch/jobs.py`
- Create: `src/litwatch/job_repository.py`
- Modify: `src/litwatch/db.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- `JobStatus`: queued/running/completed/failed/cancelled.
- `JobRecord` fields exactly match the design specification.
- `JobRepository.enqueue`, `get`, `claim_next`, `heartbeat`, `complete`, `fail`, `request_cancel`, `recover_stale`.

- [ ] **Step 1: Add failing repository tests for enqueue, unique idempotency, atomic claim, status transitions, cancellation, and restart recovery.**
- [ ] **Step 2: Verify RED because tables/types are absent.**
- [ ] **Step 3: Add migration 7 for `jobs`, unique `(job_type,idempotency_key)`, claim/status indexes, and implement transactionally guarded methods.**
- [ ] **Step 4: Run `python -m pytest tests/test_jobs.py tests/test_database_migrations.py -q`; verify PASS.**
- [ ] **Step 5: Commit with `feat(jobs): add durable job repository`.**

### Task 2: Worker, retries, timeout, and concurrency

**Files:**
- Create: `src/litwatch/services/jobs.py`
- Modify: `src/litwatch/config.py`
- Test: `tests/test_job_worker.py`

**Interfaces:**
- `JobContext.cancelled()`, `.heartbeat()`, `.remaining_seconds()`.
- `JobWorker.register(job_type, handler)`, `.start()`, `.stop()`, `.run_once()`.
- Settings: `job_poll_seconds`, `job_lease_seconds`, `job_concurrency`, `job_default_timeout_seconds`.

- [ ] **Step 1: Add failing tests for one successful handler, bounded retry, timeout, pre-start cancellation, active cancellation, concurrency ceiling, clean stop, and stale requeue/exhaustion.**
- [ ] **Step 2: Verify RED for missing worker behavior.**
- [ ] **Step 3: Implement a bounded thread worker with repository leases and safe normalized errors.**
- [ ] **Step 4: Run `python -m pytest tests/test_job_worker.py tests/test_jobs.py -q`; verify PASS.**
- [ ] **Step 5: Commit with `feat(jobs): add bounded background worker`.**

### Task 3: Job API and application lifecycle

**Files:**
- Modify: `src/litwatch/api_models.py`
- Modify: `src/litwatch/runtime.py`
- Modify: `src/litwatch/web.py`
- Test: `tests/test_job_api.py`

**Interfaces:**
- `POST /api/v2/jobs` -> 202.
- `GET /api/v2/jobs/{job_id}` -> safe projection.
- `POST /api/v2/jobs/{job_id}/cancel` -> idempotent projection.

- [ ] **Step 1: Add failing API tests for 202 creation, identical idempotency reuse, unknown job type 422, get 404, cancellation, and absence of payload/secrets in responses.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement models/routes, register worker in `ApplicationRuntime`, and ensure request handlers only enqueue.**
- [ ] **Step 4: Run job API/worker/runtime tests and full suite; verify PASS.**
- [ ] **Step 5: Commit with `feat(api): expose persistent background jobs`.**

