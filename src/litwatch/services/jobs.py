from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, RLock, Thread, current_thread
from time import monotonic
from uuid import uuid4

from litwatch.job_repository import JobRepository, JobTransitionError
from litwatch.jobs import JobRecord

JobHandler = Callable[["JobContext", JobRecord], str | None]


@dataclass(slots=True)
class JobContext:
    """Cooperative controls exposed to one running durable job handler."""

    repository: JobRepository
    job_id: str
    lease_owner: str
    lease_seconds: int
    _deadline: float
    _shutdown: Event
    _attempt_cancelled: Event

    def cancelled(self) -> bool:
        if self._shutdown.is_set() or self._attempt_cancelled.is_set():
            return True
        job = self.repository.get(self.job_id)
        return job is None or job.cancellation_requested_at is not None

    def heartbeat(self) -> JobRecord:
        return self.repository.heartbeat(
            self.job_id,
            self.lease_owner,
            lease_seconds=self.lease_seconds,
        )

    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - monotonic())


@dataclass(slots=True)
class _ActiveAttempt:
    job: JobRecord
    future: Future[None]
    deadline: float
    cancelled: Event
    timed_out: bool = False


@dataclass(slots=True)
class JobWorker:
    """Small, bounded in-process executor backed by durable SQLite job leases."""

    repository: JobRepository
    poll_seconds: float
    lease_seconds: int
    concurrency: int
    default_timeout_seconds: int = 300
    worker_id: str = field(default_factory=lambda: f"litwatch-{uuid4().hex}")
    _handlers: dict[str, JobHandler] = field(default_factory=dict, init=False)
    _attempts: dict[tuple[str, int], _ActiveAttempt] = field(
        default_factory=dict, init=False
    )
    _thread: Thread | None = field(default=None, init=False)
    _stopping: Event = field(default_factory=Event, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)

    def __post_init__(self) -> None:
        if self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if self.concurrency <= 0:
            raise ValueError("concurrency must be positive")
        if self.default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")

    @property
    def active_count(self) -> int:
        with self._lock:
            self._prune_completed()
            return len(self._attempts)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def register(self, job_type: str, handler: JobHandler) -> None:
        normalized = job_type.strip()
        if not normalized:
            raise ValueError("job_type must not be blank")
        self._handlers[normalized] = handler

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            self._prune_completed()
            if self._attempts:
                raise RuntimeError("worker still has active handlers")
            self._stopping.clear()
            self._thread = Thread(
                target=self._run_loop,
                name="litwatch-job-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stopping.set()
            for attempt in self._attempts.values():
                attempt.cancelled.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=max(1.0, self.poll_seconds * 2))

        drain_deadline = monotonic() + max(0.1, min(0.4, self.poll_seconds * 2))
        while monotonic() < drain_deadline:
            with self._lock:
                self._prune_completed()
                if not self._attempts:
                    break
            self._stopping.wait(0.01)

        with self._lock:
            self._prune_completed()
            for attempt in self._attempts.values():
                try:
                    self.repository.abandon_active_attempt(
                        attempt.job.job_id,
                        self.worker_id,
                        safe_error_code="worker_shutdown",
                        safe_error_message="worker stopped before handler drained",
                    )
                except JobTransitionError:
                    pass
            self._thread = None

    def run_once(self) -> int:
        """Recover stale work and submit up to the configured free slots."""

        submitted = 0
        with self._lock:
            self._prune_completed()
            self._maintain_active()
            self.recover_stale()
            capacity = self.concurrency - len(self._attempts)
            if capacity <= 0 or self._stopping.is_set():
                return submitted
            for _ in range(capacity):
                claimed = self.repository.claim_next(
                    self.worker_id, lease_seconds=self.lease_seconds
                )
                if claimed is None:
                    break
                handler = self._handlers.get(claimed.job_type)
                if handler is None:
                    self._fail_unhandled(claimed)
                    continue
                cancelled = Event()
                deadline = monotonic() + claimed.timeout_seconds
                future = self._start_attempt(
                    claimed, handler, deadline, cancelled
                )
                attempt_key = (claimed.job_id, claimed.attempt)
                self._attempts[attempt_key] = _ActiveAttempt(
                    job=claimed,
                    future=future,
                    deadline=deadline,
                    cancelled=cancelled,
                )
                submitted += 1
        return submitted

    def recover_stale(self, now: datetime | None = None) -> list[JobRecord]:
        active_job_ids = tuple(
            sorted({attempt.job.job_id for attempt in self._attempts.values()})
        )
        return self.repository.recover_stale(now, exclude_job_ids=active_job_ids)

    def _run_loop(self) -> None:
        while not self._stopping.is_set():
            self.run_once()
            heartbeat_interval = max(0.05, self.lease_seconds / 3)
            self._stopping.wait(min(self.poll_seconds, heartbeat_interval))

    def _start_attempt(
        self,
        job: JobRecord,
        handler: JobHandler,
        deadline: float,
        cancelled: Event,
    ) -> Future[None]:
        future: Future[None] = Future()

        def run() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                self._execute(job, handler, deadline, cancelled)
            except Exception as error:  # noqa: BLE001  # pragma: no cover
                future.set_exception(error)
            else:
                future.set_result(None)

        # A handler may ignore cooperative cancellation. Daemon attempts keep
        # stop bounded and cannot hold the Python interpreter open at shutdown.
        Thread(
            target=run,
            name=f"litwatch-job-{job.job_id[:8]}-{job.attempt}",
            daemon=True,
        ).start()
        return future

    def _prune_completed(self) -> None:
        completed = [
            attempt_key
            for attempt_key, attempt in self._attempts.items()
            if attempt.future.done()
        ]
        for attempt_key in completed:
            self._attempts.pop(attempt_key, None)

    def _maintain_active(self) -> None:
        now = monotonic()
        for attempt in self._attempts.values():
            if attempt.future.done():
                continue
            if now >= attempt.deadline:
                attempt.cancelled.set()
                if not attempt.timed_out:
                    try:
                        self.repository.mark_active_timeout(
                            attempt.job.job_id,
                            self.worker_id,
                            lease_seconds=self.lease_seconds,
                            safe_error_message=(
                                "job exceeded its execution time limit"
                            ),
                        )
                    except JobTransitionError:
                        pass
                    else:
                        attempt.timed_out = True
            try:
                self.repository.heartbeat(
                    attempt.job.job_id,
                    self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
            except JobTransitionError:
                # A cancellation or externally sealed attempt is already durable.
                pass

    def _execute(
        self,
        job: JobRecord,
        handler: JobHandler,
        deadline: float,
        attempt_cancelled: Event,
    ) -> None:
        context = JobContext(
            repository=self.repository,
            job_id=job.job_id,
            lease_owner=self.worker_id,
            lease_seconds=self.lease_seconds,
            _deadline=deadline,
            _shutdown=self._stopping,
            _attempt_cancelled=attempt_cancelled,
        )
        try:
            if self._stopping.is_set():
                self._fail(
                    job,
                    "worker_shutdown",
                    "worker stopped before job execution",
                    retryable=True,
                )
                return
            if attempt_cancelled.is_set():
                self._fail(
                    job,
                    "timeout",
                    "job exceeded its execution time limit",
                    retryable=True,
                )
                return
            if context.cancelled():
                self.repository.complete(job.job_id, self.worker_id, result_reference=None)
                return
            result_reference = handler(context, job)
            if context.remaining_seconds() <= 0:
                self._fail(job, "timeout", "job exceeded its execution time limit", retryable=True)
                return
            with self._lock:
                if self._stopping.is_set():
                    self._fail(
                        job,
                        "worker_shutdown",
                        "worker stopped during job execution",
                        retryable=True,
                    )
                    return
                self.repository.complete(
                    job.job_id, self.worker_id, result_reference=result_reference
                )
        except TimeoutError:
            self._fail(job, "timeout", "job timed out", retryable=True)
        except ConnectionError:
            self._fail(job, "upstream_error", "upstream service unavailable", retryable=True)
        except JobTransitionError:
            # Lease loss or an external cancellation is already represented durably.
            return
        except Exception:  # noqa: BLE001 - registered handlers are an isolation boundary
            self._fail(job, "handler_error", "job handler failed", retryable=False)

    def _fail(self, job: JobRecord, code: str, message: str, *, retryable: bool) -> None:
        try:
            self.repository.fail(
                job.job_id,
                self.worker_id,
                safe_error_code=code,
                safe_error_message=message,
                retryable=retryable,
            )
        except JobTransitionError:
            return

    def _fail_unhandled(self, job: JobRecord) -> None:
        self._fail(job, "unsupported_job_type", "no handler is registered for this job", retryable=False)
