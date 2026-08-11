from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
