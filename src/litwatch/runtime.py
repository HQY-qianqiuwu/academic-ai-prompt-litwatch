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
        startup_hooks: Sequence[Callable[[], None]] = (),
        shutdown_hooks: Sequence[Callable[[], None]] = (),
    ) -> None:
        self._database_preflight = database_preflight
        self._scheduler_start = scheduler_start
        self._scheduler_stop = scheduler_stop
        self._startup_hooks = tuple(startup_hooks)
        self._shutdown_hooks = tuple(shutdown_hooks)
        self._started = False
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._database_preflight()
            for hook in self._startup_hooks:
                hook()
            self._scheduler_start()
            self._started = True

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            try:
                self._scheduler_stop()
                for hook in reversed(self._shutdown_hooks):
                    hook()
            finally:
                self._started = False
