from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
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

    def cancelled(self) -> bool:
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
class JobWorker:
    """Small, bounded in-process executor backed by durable SQLite job leases."""

    repository: JobRepository
    poll_seconds: float
    lease_seconds: int
    concurrency: int
    default_timeout_seconds: int = 300
    worker_id: str = field(default_factory=lambda: f"litwatch-{uuid4().hex}")
    _handlers: dict[str, JobHandler] = field(default_factory=dict, init=False)
    _futures: dict[str, Future[None]] = field(default_factory=dict, init=False)
    _deadlines: dict[str, float] = field(default_factory=dict, init=False)
    _executor: ThreadPoolExecutor | None = field(default=None, init=False)
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
            return len(self._futures)

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
            if self._futures:
                raise RuntimeError("worker still has active handlers")
            self._stopping.clear()
            self._ensure_executor()
            self._thread = Thread(
                target=self._run_loop,
                name="litwatch-job-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=max(1.0, self.poll_seconds * 2))
        with self._lock:
            executor = self._executor
            self._executor = None
            self._thread = None
        if executor is not None:
            # Python cannot safely kill a running thread.  Never wait forever:
            # the fixed-size pool keeps any non-cooperative handler bounded, and
            # start() rejects a replacement pool until it has drained.
            executor.shutdown(wait=False, cancel_futures=True)

    def run_once(self) -> int:
        """Recover stale work and submit up to the configured free slots."""

        self.recover_stale()
        submitted = 0
        with self._lock:
            self._prune_completed()
            self._expire_timed_out()
            capacity = self.concurrency - len(self._futures)
            if capacity <= 0 or self._stopping.is_set():
                return submitted
            executor = self._ensure_executor()
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
                future = executor.submit(self._execute, claimed, handler)
                self._futures[claimed.job_id] = future
                self._deadlines[claimed.job_id] = monotonic() + claimed.timeout_seconds
                submitted += 1
        return submitted

    def recover_stale(self, now: datetime | None = None) -> list[JobRecord]:
        return self.repository.recover_stale(now)

    def _run_loop(self) -> None:
        while not self._stopping.is_set():
            self.run_once()
            self._stopping.wait(self.poll_seconds)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.concurrency,
                thread_name_prefix="litwatch-job",
            )
        return self._executor

    def _prune_completed(self) -> None:
        completed = [job_id for job_id, future in self._futures.items() if future.done()]
        for job_id in completed:
            self._futures.pop(job_id, None)
            self._deadlines.pop(job_id, None)

    def _expire_timed_out(self) -> None:
        now = monotonic()
        for job_id, deadline in tuple(self._deadlines.items()):
            if now < deadline:
                continue
            job = self.repository.get(job_id)
            if job is None or job.status.value != "running":
                continue
            self._fail(job, "timeout", "job exceeded its execution time limit", retryable=True)

    def _execute(self, job: JobRecord, handler: JobHandler) -> None:
        deadline = monotonic() + job.timeout_seconds
        context = JobContext(
            repository=self.repository,
            job_id=job.job_id,
            lease_owner=self.worker_id,
            lease_seconds=self.lease_seconds,
            _deadline=deadline,
        )
        try:
            if context.cancelled():
                self.repository.complete(job.job_id, self.worker_id, result_reference=None)
                return
            result_reference = handler(context, job)
            if context.remaining_seconds() <= 0:
                self._fail(job, "timeout", "job exceeded its execution time limit", retryable=True)
                return
            self.repository.complete(job.job_id, self.worker_id, result_reference=result_reference)
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
