from __future__ import annotations

import re
from collections.abc import Collection

_URL_CREDENTIALS = re.compile(r"\b(https?://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_BEARER_CREDENTIAL = re.compile(r"\b(Bearer)\s+[^\s,;]+", re.IGNORECASE)
_COOKIE_HEADER = re.compile(r"\b(Cookie)\s*:\s*[^\r\n]+", re.IGNORECASE)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"\b(api[-_ ]?key|access[-_ ]?token|auth[-_ ]?token|client[-_ ]?secret|"
    r"password|credential)\s*[:=]\s*(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;]+)",
    re.IGNORECASE,
)
_ENVIRONMENT_CREDENTIAL = re.compile(
    r"\b[A-Z][A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|PASSWORD|SECRET|TOKEN)"
    r"\s*=\s*[^\s,;]+"
)
_JSON_CREDENTIAL = re.compile(
    r'"(api[-_ ]?key|authorization|cookie|credentials?|password|secret|token)"'
    r'\s*:\s*"(?:\\.|[^"\\])*"',
    re.IGNORECASE,
)


def redact_sensitive_text(text: str) -> str:
    """Remove common credentials before text crosses a persistence or LLM boundary."""

    redacted = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    redacted = _BEARER_CREDENTIAL.sub(r"\1 [REDACTED]", redacted)
    redacted = _COOKIE_HEADER.sub(r"\1: [REDACTED]", redacted)
    redacted = _ENVIRONMENT_CREDENTIAL.sub("[REDACTED]", redacted)
    redacted = _JSON_CREDENTIAL.sub(r'"\1":"[REDACTED]"', redacted)
    return _CREDENTIAL_ASSIGNMENT.sub(r"\1=[REDACTED]", redacted)


def allowlisted_safe_error(
    message: str,
    *,
    allowed_messages: Collection[str],
    fallback: str,
) -> str:
    """Return only a reviewed safe error phrase, never a raw upstream detail."""

    return message if message in allowed_messages else fallback
