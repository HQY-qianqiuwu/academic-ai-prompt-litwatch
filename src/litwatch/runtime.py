from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from threading import Lock


class RuntimeMode(str, Enum):
    LEGACY = "legacy"
    DUAL = "dual"
    PYTHON_DEFAULT = "python_default"
    DIFY_FREE = "dify_free"


class RuntimeLifecycleError(RuntimeError):
    """Safe public signal that one or more lifecycle resources failed to stop."""


@dataclass(frozen=True)
class RuntimeStatus:
    mode: RuntimeMode
    python_primary: bool
    requires_dify: bool
    requires_docker: bool
    requires_ssrf_proxy: bool

    @classmethod
    def from_mode(cls, mode: RuntimeMode) -> RuntimeStatus:
        if mode is RuntimeMode.LEGACY:
            return cls(mode, False, True, True, True)
        if mode is RuntimeMode.DUAL:
            return cls(mode, True, True, True, True)
        return cls(mode, True, False, False, False)


class ApplicationRuntime:
    """Own application-owned lifecycle resources with idempotent transitions."""

    def __init__(
        self,
        *,
        database_preflight: Callable[[], None] = lambda: None,
        scheduler_start: Callable[[], None],
        scheduler_stop: Callable[[], None],
        worker_start: Callable[[], None] = lambda: None,
        worker_stop: Callable[[], None] = lambda: None,
        startup_hooks: Sequence[Callable[[], None]] = (),
        shutdown_hooks: Sequence[Callable[[], None]] = (),
    ) -> None:
        self._database_preflight = database_preflight
        self._scheduler_start = scheduler_start
        self._scheduler_stop = scheduler_stop
        self._worker_start = worker_start
        self._worker_stop = worker_stop
        self._startup_hooks = tuple(startup_hooks)
        self._shutdown_hooks = tuple(shutdown_hooks)
        self._started = False
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._database_preflight()
            worker_started = False
            try:
                for hook in self._startup_hooks:
                    hook()
                self._worker_start()
                worker_started = True
                self._scheduler_start()
            except Exception:
                if worker_started:
                    try:
                        self._worker_stop()
                    except Exception:  # noqa: BLE001, S110 - preserve startup error
                        pass
                raise
            else:
                self._started = True

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            failures: list[Exception] = []
            try:
                self._scheduler_stop()
            except Exception as error:  # noqa: BLE001 - continue shutdown sequence
                failures.append(error)
            try:
                self._worker_stop()
            except Exception as error:  # noqa: BLE001 - continue shutdown sequence
                failures.append(error)
            for hook in reversed(self._shutdown_hooks):
                try:
                    hook()
                except Exception as error:  # noqa: BLE001 - continue shutdown sequence
                    failures.append(error)
            self._started = False
            if failures:
                raise RuntimeLifecycleError(
                    "application runtime shutdown failed"
                ) from failures[0]
