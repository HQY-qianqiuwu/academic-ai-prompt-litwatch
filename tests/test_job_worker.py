from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from time import monotonic, sleep

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

    timed_out = repository.get(job.job_id)
    assert timed_out.status.value == "running"
    assert timed_out.safe_error_code == "timeout"
    assert timed_out.safe_error_message == "job exceeded its execution time limit"
    assert worker.active_count == 1
    release.set()
    timed_out = _wait_for(repository, job.job_id, {"queued"})
    assert timed_out.safe_error_code == "timeout"
    worker.stop()
    database.connection.close()


def test_timeout_never_requeues_while_original_physical_attempt_is_active(tmp_path):
    database = Database(tmp_path / "no-duplicate-timeout.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2, timeout=1)
    entered = Event()
    release = Event()
    calls = 0
    active = 0
    maximum = 0
    lock = Lock()
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=2)

    def slow(_context, _record):
        nonlocal calls, active, maximum
        with lock:
            calls += 1
            active += 1
            maximum = max(maximum, active)
        entered.set()
        release.wait(5)
        with lock:
            active -= 1
        return "late"

    worker.register("analysis", slow)
    worker.run_once()
    assert entered.wait(1)
    sleep(1.05)

    for _ in range(3):
        worker.run_once()
        sleep(0.02)

    timed_out = repository.get(job.job_id)
    assert timed_out.status.value == "running"
    assert timed_out.safe_error_code == "timeout"
    assert timed_out.safe_error_message == "job exceeded its execution time limit"
    assert calls == 1
    assert maximum == 1
    assert worker.active_count == 1

    release.set()
    _wait_for(repository, job.job_id, {"queued"})
    worker.stop()
    database.connection.close()


def test_background_worker_heartbeats_long_running_attempt_without_duplicate(tmp_path):
    database = Database(tmp_path / "automatic-heartbeat.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2, timeout=3)
    entered = Event()
    release = Event()
    calls = 0
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=1, concurrency=2)

    def slow(_context, _record):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(5)
        return "done"

    worker.register("analysis", slow)
    worker.start()
    assert entered.wait(1)
    sleep(1.15)

    running = repository.get(job.job_id)
    assert running.status.value == "running"
    assert running.heartbeat_at is not None
    assert running.heartbeat_at > running.started_at
    assert calls == 1
    assert worker.active_count == 1

    release.set()
    _wait_for(repository, job.job_id, {"completed"})
    worker.stop()
    database.connection.close()


def test_timed_out_attempt_renews_lease_across_multiple_intervals(tmp_path):
    database = Database(tmp_path / "timed-out-heartbeat.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2, timeout=1)
    entered = Event()
    release = Event()
    calls = 0
    owner = JobWorker(repository, poll_seconds=0.01, lease_seconds=1, concurrency=1)
    contender = JobWorker(
        repository, poll_seconds=0.01, lease_seconds=1, concurrency=1
    )

    def slow(_context, _record):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(8)
        return "late"

    owner.register("analysis", slow)
    contender.register("analysis", slow)
    owner.start()
    try:
        assert entered.wait(1)
        marker_deadline = monotonic() + 2
        while monotonic() < marker_deadline:
            current = repository.get(job.job_id)
            if current.safe_error_code == "timeout":
                break
            sleep(0.02)
        else:
            raise AssertionError("durable timeout marker was not recorded")

        # Keep probing from another worker beyond two complete lease intervals.
        probe_deadline = monotonic() + 2.2
        while monotonic() < probe_deadline:
            contender.run_once()
            sleep(0.05)

        active = repository.get(job.job_id)
        assert active.status.value == "running"
        assert active.attempt == 1
        assert active.safe_error_code == "timeout"
        assert calls == 1
        assert owner.active_count == 1
        assert contender.active_count == 0
    finally:
        owner.stop()
        contender.stop()
        release.set()
        deadline = monotonic() + 1
        while owner.active_count and monotonic() < deadline:
            sleep(0.01)
        database.connection.close()


def test_stop_signals_cooperative_handler_and_prevents_post_stop_completion(tmp_path):
    database = Database(tmp_path / "cooperative-stop.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2, timeout=5)
    entered = Event()
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)

    def cooperative(context, _record):
        entered.set()
        while not context.cancelled():
            sleep(0.01)
        return "must-not-complete"

    worker.register("analysis", cooperative)
    worker.start()
    assert entered.wait(1)
    worker.stop()

    stopped = repository.get(job.job_id)
    assert stopped.status.value != "completed"
    assert stopped.result_reference is None
    assert worker.active_count == 0
    database.connection.close()


def test_stop_is_bounded_and_seals_non_cooperative_attempt_before_return(tmp_path):
    database = Database(tmp_path / "non-cooperative-stop.db")
    repository = JobRepository(database)
    job = _enqueue(repository, attempts=2, timeout=5)
    entered = Event()
    release = Event()
    worker = JobWorker(repository, poll_seconds=0.01, lease_seconds=3, concurrency=1)

    def non_cooperative(_context, _record):
        entered.set()
        release.wait(5)
        return "must-not-complete"

    worker.register("analysis", non_cooperative)
    worker.start()
    assert entered.wait(1)

    started = monotonic()
    worker.stop()
    assert monotonic() - started < 0.5
    sealed = repository.get(job.job_id)
    assert sealed.status.value in {"failed", "cancelled"}
    assert sealed.result_reference is None

    release.set()
    deadline = monotonic() + 1
    while worker.active_count and monotonic() < deadline:
        sleep(0.01)
    after_release = repository.get(job.job_id)
    assert after_release.status == sealed.status
    assert after_release.result_reference is None
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
