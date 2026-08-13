from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from time import sleep as default_sleep

import httpx

from litwatch.llm.models import (
    LLMErrorCode,
    LLMGatewayError,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)
from litwatch.security import redact_sensitive_text


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OpenAICompatibleProvider:
    """Minimal OpenAI-compatible transport with finite, normalized retries."""

    __slots__ = (
        "_api_key",
        "_backoff_seconds",
        "_base_url",
        "_client",
        "_max_attempts",
        "_max_retry_delay_seconds",
        "_now",
        "_sleep",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        api_key: str,
        max_attempts: int = 3,
        timeout_seconds: float = 30,
        backoff_seconds: float = 1,
        max_retry_delay_seconds: float = 10,
        sleep: Callable[[float], None] = default_sleep,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if timeout_seconds <= 0 or backoff_seconds < 0 or max_retry_delay_seconds < 0:
            raise ValueError("LLM retry timing must be non-negative and timeout positive")
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._max_attempts = max_attempts
        self._timeout_seconds = timeout_seconds
        self._backoff_seconds = backoff_seconds
        self._max_retry_delay_seconds = max_retry_delay_seconds
        self._sleep = sleep
        self._now = now

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": redact_sensitive_text(request.system_instruction),
                },
                {
                    "role": "user",
                    "content": request.user_message_content,
                },
            ],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, self._max_attempts + 1):
            response: httpx.Response | None = None
            timed_out = False
            transport_failed = False
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except httpx.TimeoutException:
                timed_out = True
            except httpx.HTTPError:
                transport_failed = True

            if timed_out:
                if attempt < self._max_attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                raise LLMGatewayError(
                    LLMErrorCode.TIMEOUT,
                    "LLM request timed out",
                    attempts=attempt,
                ) from None

            if transport_failed:
                raise LLMGatewayError(
                    LLMErrorCode.UPSTREAM,
                    "LLM transport failed",
                    attempts=attempt,
                ) from None

            if response is None:  # pragma: no cover - guarded transport invariant
                raise LLMGatewayError(
                    LLMErrorCode.UPSTREAM, "LLM request failed", attempts=attempt
                )
            if response.status_code in {401, 403}:
                raise LLMGatewayError(
                    LLMErrorCode.AUTHENTICATION,
                    "LLM authentication failed",
                    attempts=attempt,
                ) from None
            if response.status_code == 429:
                if attempt < self._max_attempts:
                    self._sleep(self._retry_after(response, attempt))
                    continue
                raise LLMGatewayError(
                    LLMErrorCode.RATE_LIMITED,
                    "LLM provider rate limit exceeded",
                    attempts=attempt,
                ) from None
            if 500 <= response.status_code <= 599:
                if attempt < self._max_attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                raise LLMGatewayError(
                    LLMErrorCode.UPSTREAM,
                    "LLM provider unavailable",
                    attempts=attempt,
                ) from None
            if response.status_code >= 400:
                raise LLMGatewayError(
                    LLMErrorCode.UPSTREAM,
                    "LLM request was rejected",
                    attempts=attempt,
                ) from None
            return self._decode_success(response, attempt)

        raise AssertionError("finite LLM retry loop exhausted unexpectedly")

    def _decode_success(self, response: httpx.Response, attempt: int) -> LLMResponse:
        document: object | None = None
        malformed = False
        try:
            document = response.json()
            content = document["choices"][0]["message"]["content"]
            usage_document = document.get("usage") or {}
            input_tokens = usage_document.get("prompt_tokens", 0)
            output_tokens = usage_document.get("completion_tokens", 0)
            total_tokens = usage_document.get("total_tokens")
            usage = LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=(
                    total_tokens
                    if total_tokens is not None
                    else input_tokens + output_tokens
                ),
            )
            provider_request_id = document.get("id")
            model = document.get("model")
            if not isinstance(content, str):
                malformed = True
        except (KeyError, IndexError, TypeError, ValueError):
            malformed = True
        if malformed or document is None:
            raise LLMGatewayError(
                LLMErrorCode.PARSE,
                "LLM provider returned an invalid response envelope",
                attempts=attempt,
            ) from None
        return LLMResponse(
            content=content,
            usage=usage,
            provider_request_id=(
                provider_request_id if isinstance(provider_request_id, str) else None
            ),
            model=model if isinstance(model, str) else None,
        )

    def _backoff(self, attempt: int) -> float:
        return min(
            self._backoff_seconds * (2 ** (attempt - 1)),
            self._max_retry_delay_seconds,
        )

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "")
        delay: float | None = None
        try:
            delay = float(raw)
        except ValueError:
            retry_at: datetime | None = None
            try:
                retry_at = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                pass
            if retry_at is not None and retry_at.tzinfo is not None:
                current = self._now()
                if current.tzinfo is not None:
                    delay = (retry_at.astimezone(UTC) - current.astimezone(UTC)).total_seconds()
        if delay is None or not isfinite(delay):
            delay = self._backoff(attempt)
        return min(max(0, delay), self._max_retry_delay_seconds)
