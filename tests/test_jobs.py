from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from litwatch.db import Database
from litwatch.job_repository import JobRepository, JobTransitionError
from litwatch.jobs import JobRecord, JobStatus

NOW = datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)


def _enqueue(repository: JobRepository, **overrides: object) -> JobRecord:
    arguments: dict[str, object] = {
        "job_type": "paper_analysis",
        "idempotency_key": "paper:doi:10.1000/example",
        "input_hash": "sha256:input",
        "payload": {
            "paper_id": "doi:10.1000/example",
            "credential_reference": "provider:openai-compatible",
        },
        "max_attempts": 2,
        "timeout_seconds": 90,
        "now": NOW,
    }
    arguments.update(overrides)
    return repository.enqueue(**arguments)


def test_enqueue_persists_typed_queued_job(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)

    job = _enqueue(repository)

    assert isinstance(job, JobRecord)
    assert job.status is JobStatus.QUEUED
    assert job.attempt == 0
    assert job.created_at == NOW
    assert job.payload == {
        "paper_id": "doi:10.1000/example",
        "credential_reference": "provider:openai-compatible",
    }
    assert repository.get(job.job_id) == job
    database.connection.close()


def test_enqueue_reuses_unique_job_type_and_idempotency_key(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    first = _enqueue(repository)

    repeated = _enqueue(
        repository,
        input_hash="sha256:different",
        payload={"paper_id": "must-not-replace-original"},
    )

    assert repeated.job_id == first.job_id
    assert repeated.input_hash == "sha256:input"
    assert repeated.payload == first.payload
    assert database.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    database.connection.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "do-not-store"},
        {"nested": {"authorization": "Bearer do-not-store"}},
        {"password": "do-not-store"},
    ],
)
def test_enqueue_rejects_inline_credentials(tmp_path, payload):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)

    with pytest.raises(ValueError, match="credential references"):
        _enqueue(repository, payload=payload)

    assert database.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    database.connection.close()


def test_claim_next_is_atomic_and_increments_attempt(tmp_path):
    database = Database(tmp_path / "jobs.db")
    first_repository = JobRepository(database)
    second_repository = JobRepository(database)
    queued = _enqueue(first_repository)

    claimed = first_repository.claim_next("worker-a", lease_seconds=30, now=NOW)
    second_claim = second_repository.claim_next("worker-b", lease_seconds=30, now=NOW)

    assert claimed is not None
    assert claimed.job_id == queued.job_id
    assert claimed.status is JobStatus.RUNNING
    assert claimed.attempt == 1
    assert claimed.started_at == NOW
    assert claimed.heartbeat_at == NOW
    assert claimed.lease_owner == "worker-a"
    assert claimed.lease_expires_at == NOW + timedelta(seconds=30)
    assert second_claim is None
    database.connection.close()


def test_guarded_running_transitions_require_lease_owner(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    queued = _enqueue(repository)

    with pytest.raises(JobTransitionError):
        repository.complete(queued.job_id, "worker-a", result_reference="result:1", now=NOW)

    running = repository.claim_next("worker-a", lease_seconds=30, now=NOW)
    assert running is not None
    with pytest.raises(JobTransitionError):
        repository.heartbeat(running.job_id, "worker-b", lease_seconds=30, now=NOW)

    heartbeat_at = NOW + timedelta(seconds=5)
    heartbeated = repository.heartbeat(
        running.job_id, "worker-a", lease_seconds=30, now=heartbeat_at
    )
    completed = repository.complete(
        running.job_id,
        "worker-a",
        result_reference="analysis:doi:10.1000/example",
        now=heartbeat_at,
    )

    assert heartbeated.heartbeat_at == heartbeat_at
    assert completed.status is JobStatus.COMPLETED
    assert completed.finished_at == heartbeat_at
    assert completed.result_reference == "analysis:doi:10.1000/example"
    assert completed.lease_owner is None
    database.connection.close()


def test_failure_can_requeue_with_bound_and_then_finishes_failed(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    _enqueue(repository)
    first = repository.claim_next("worker-a", lease_seconds=30, now=NOW)
    assert first is not None

    requeued = repository.fail(
        first.job_id,
        "worker-a",
        safe_error_code="upstream_timeout",
        safe_error_message="provider timed out",
        retryable=True,
        now=NOW + timedelta(seconds=1),
    )
    second = repository.claim_next(
        "worker-b", lease_seconds=30, now=NOW + timedelta(seconds=2)
    )
    assert second is not None
    failed = repository.fail(
        second.job_id,
        "worker-b",
        safe_error_code="upstream_timeout",
        safe_error_message="provider timed out",
        retryable=True,
        now=NOW + timedelta(seconds=3),
    )

    assert requeued.status is JobStatus.QUEUED
    assert second.attempt == 2
    assert failed.status is JobStatus.FAILED
    assert failed.finished_at == NOW + timedelta(seconds=3)
    assert failed.safe_error_code == "upstream_timeout"
    database.connection.close()


def test_cancellation_is_idempotent_and_cooperative_for_running_job(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = JobRepository(database)
    queued = _enqueue(repository)

    cancelled = repository.request_cancel(queued.job_id, now=NOW)
    repeated = repository.request_cancel(queued.job_id, now=NOW + timedelta(seconds=1))
    assert cancelled.status is JobStatus.CANCELLED
    assert repeated.cancellation_requested_at == NOW

    active = _enqueue(repository, idempotency_key="active")
    running = repository.claim_next("worker-a", lease_seconds=30, now=NOW)
    assert running is not None and running.job_id == active.job_id
    requested = repository.request_cancel(running.job_id, now=NOW + timedelta(seconds=2))
    finished = repository.complete(
        running.job_id, "worker-a", result_reference=None, now=NOW + timedelta(seconds=3)
    )

    assert requested.status is JobStatus.RUNNING
    assert requested.cancellation_requested_at == NOW + timedelta(seconds=2)
    assert finished.status is JobStatus.CANCELLED
    assert finished.result_reference is None
    database.connection.close()


def test_restart_recovery_requeues_once_then_exhausts_stale_job(tmp_path):
    path = tmp_path / "jobs.db"
    database = Database(path)
    repository = JobRepository(database)
    queued = _enqueue(repository)
    repository.claim_next("worker-a", lease_seconds=5, now=NOW)
    database.connection.close()

    reopened = Database(path)
    restarted = JobRepository(reopened)
    recovered = restarted.recover_stale(NOW + timedelta(seconds=6))
    assert [job.job_id for job in recovered] == [queued.job_id]
    assert recovered[0].status is JobStatus.QUEUED

    claimed = restarted.claim_next(
        "worker-b", lease_seconds=5, now=NOW + timedelta(seconds=7)
    )
    assert claimed is not None
    exhausted = restarted.recover_stale(NOW + timedelta(seconds=13))

    assert exhausted[0].status is JobStatus.FAILED
    assert exhausted[0].safe_error_code == "restart_recovery_exhausted"
    assert exhausted[0].finished_at == NOW + timedelta(seconds=13)
    reopened.connection.close()
