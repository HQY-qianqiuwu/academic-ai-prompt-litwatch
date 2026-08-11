from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from time import monotonic, sleep

import pytest

from litwatch.db import Database
from litwatch.job_repository import JobRepository
from litwatch.services.jobs import JobWorker


def _enqueue(repository: JobRepository, *, key: str = "one", attempts: int = 2, timeout: int = 1):
    return repository.enqueue(
        job_type="analysis",
        idempotency_key=key,
        input_hash=f"hash:{key}",
        payload={"paper_id": key},
        max_attempts=attempts,
        timeout_seconds=timeout,
    )


def _wait_for(repository: JobRepository, job_id: str, statuses: set[str], timeout: float = 2.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job = repository.get(job_id)
        if job is not None and job.status.value in statuses:
            return job
        sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def test_worker_runs_registered_handler_and_persists_result(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    job = _enqueue(repository)
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)
    seen: list[str] = []
    worker.register("analysis", lambda context, record: seen.append(record.job_id) or "result:one")

    worker.run_once()

    completed = _wait_for(repository, job.job_id, {"completed"})
    assert seen == [job.job_id]
    assert completed.result_reference == "result:one"
    worker.stop()
    database.connection.close()


def test_worker_retries_only_to_max_attempts_and_records_safe_error(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2)
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)
    calls = 0

    def fail(_context, _record):
        nonlocal calls
        calls += 1
        raise TimeoutError("provider secret=must-not-leak")

    worker.register("analysis", fail)
    worker.run_once()
    _wait_for(repository, job.job_id, {"queued"})
    worker.run_once()
    failed = _wait_for(repository, job.job_id, {"failed"})

    assert calls == 2
    assert failed.attempt == 2
    assert failed.safe_error_code == "timeout"
    assert "must-not-leak" not in (failed.safe_error_message or "")
    worker.stop()
    database.connection.close()


def test_worker_marks_expired_handler_retryable_timeout(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2, timeout=1)
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)
    worker.register("analysis", lambda _context, _record: (sleep(1.05), "late")[1])

    worker.run_once()

    queued = _wait_for(repository, job.job_id, {"queued"}, timeout=2.5)
    assert queued.safe_error_code == "timeout"
    worker.stop()
    database.connection.close()


def test_timeout_watchdog_persists_timeout_without_spawning_extra_handlers(tmp_path):
    database = Database(tmp_path / "watchdog.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2, timeout=1)
    release = Event()
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)

    def stuck(_context, _record):
        release.wait(5)
        return "late"

    worker.register("analysis", stuck)

    worker.run_once()
    sleep(1.05)
    worker.run_once()

    timed_out = _wait_for(repository, job.job_id, {"queued"})
    assert timed_out.safe_error_code == "timeout"
    assert worker.active_count == 1
    started = monotonic()
    worker.stop()
    assert monotonic() - started < 0.5
    with pytest.raises(RuntimeError, match="active handlers"):
        worker.start()
    release.set()
    deadline = monotonic() + 1
    while worker.active_count and monotonic() < deadline:
        sleep(0.01)
    assert worker.active_count == 0
    database.connection.close()


def test_worker_skips_pre_start_cancel_and_cooperates_with_active_cancel(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    cancelled = _enqueue(repository, key="cancelled")
    repository.request_cancel(cancelled.job_id)
    active = _enqueue(repository, key="active")
    entered = Event()
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)

    def cooperative(context, _record):
        entered.set()
        while not context.cancelled():
            sleep(0.01)
        return "must-not-persist"

    worker.register("analysis", cooperative)
    worker.run_once()
    assert entered.wait(1)
    repository.request_cancel(active.job_id)

    active_result = _wait_for(repository, active.job_id, {"cancelled"})
    assert active_result.result_reference is None
    assert repository.get(cancelled.job_id).status.value == "cancelled"
    worker.stop()
    database.connection.close()


def test_worker_enforces_concurrency_and_clean_stop(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    jobs = [_enqueue(repository, key=str(index)) for index in range(3)]
    entered = Event()
    release = Event()
    active = 0
    maximum = 0
    lock = Lock()
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=2)

    def handler(_context, _record):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                entered.set()
        release.wait(1)
        with lock:
            active -= 1
        return "done"

    worker.register("analysis", handler)
    worker.run_once()
    assert entered.wait(1)
    assert worker.active_count == 2
    release.set()
    for job in jobs[:2]:
        _wait_for(repository, job.job_id, {"completed"})
    assert maximum == 2
    worker.stop()
    assert worker.is_running is False
    database.connection.close()


def test_worker_start_is_idempotent_and_stop_stops_background_thread(tmp_path):
    database = Database(tmp_path / "background.db")
    repository = JobRepository(database)
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)

    worker.start()
    worker.start()

    assert worker.is_running is True
    worker.stop()
    assert worker.is_running is False
    database.connection.close()


def test_worker_recovers_stale_job_for_requeue_then_exhaustion(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    job = repository.enqueue(
        job_type="analysis", idempotency_key="stale", input_hash="stale", payload={},
        max_attempts=1, timeout_seconds=1,
    )
    now = datetime.now(UTC)
    claimed = repository.claim_next("old-worker", lease_seconds=1, now=now)
    assert claimed is not None
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)

    recovered = worker.recover_stale(now + timedelta(seconds=2))

    assert recovered[0].job_id == job.job_id
    assert recovered[0].status.value == "failed"
    assert recovered[0].safe_error_code == "restart_recovery_exhausted"
    worker.stop()
    database.connection.close()
