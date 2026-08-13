from __future__ import annotations

import re
from collections.abc import Collection

_URL_CREDENTIALS = re.compile(r"\b(https?://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_BEARER_CREDENTIAL = re.compile(r"\b(Bearer)\s+[^\s,;]+", re.IGNORECASE)
_COOKIE_HEADER = re.compile(r"\b(Cookie)\s*:\s*[^\r\n]+", re.IGNORECASE)
_NAMED_CREDENTIAL = re.compile(
    r"\b(api[-_ ]?key|authorization|token|secret|password|credential)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)


def redact_sensitive_text(text: str) -> str:
    """Remove common credentials before text crosses a persistence or LLM boundary."""

    redacted = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    redacted = _BEARER_CREDENTIAL.sub(r"\1 [REDACTED]", redacted)
    redacted = _COOKIE_HEADER.sub(r"\1: [REDACTED]", redacted)
    return _NAMED_CREDENTIAL.sub(r"\1=[REDACTED]", redacted)


def allowlisted_safe_error(
    message: str,
    *,
    allowed_messages: Collection[str],
    fallback: str,
) -> str:
    """Return only a reviewed safe error phrase, never a raw upstream detail."""

    return message if message in allowed_messages else fallback
