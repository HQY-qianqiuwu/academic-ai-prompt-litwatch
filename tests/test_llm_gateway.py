from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import Mock

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from litwatch.llm import (
    LLMBudget,
    LLMErrorCode,
    LLMGateway,
    LLMGatewayError,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    OpenAICompatibleProvider,
)
from litwatch.llm.security import CostGuard, DataEgressPolicy, LLMSecurityError


class Summary(BaseModel):
    title: str
    score: float


def _request() -> LLMRequest:
    return LLMRequest(
        model="test-model",
        system_instruction="Return grounded JSON only.",
        user_instruction="Summarize the paper.",
        untrusted_evidence="Untrusted abstract text.",
        provider_kind="cloud",
        evidence_scope="abstract",
        max_output_tokens=200,
    )


def _budget(**overrides) -> LLMBudget:
    values = {
        "input_cost_per_million": 0,
        "output_cost_per_million": 0,
        "estimated_tokens": 300,
        "estimated_cost": 0,
        "daily_spend": 0,
        "active_jobs": 0,
    }
    values.update(overrides)
    return LLMBudget(**values)


def _success(content: str = '{"title":"Grounded","score":0.8}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "request-safe-id",
            "model": "test-model",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            },
        },
    )


def test_request_and_budget_fail_closed_without_security_context():
    with pytest.raises(ValidationError):
        LLMRequest(
            model="test-model",
            system_instruction="Return JSON.",
        )
    with pytest.raises(ValidationError):
        LLMBudget()


@pytest.mark.parametrize(
    "field", ["input_cost_per_million", "output_cost_per_million"]
)
def test_budget_rejects_non_finite_pricing(field):
    with pytest.raises(ValidationError):
        _budget(**{field: float("inf")})


@pytest.mark.parametrize(
    "field",
    [
        "input_cost_per_million",
        "output_cost_per_million",
        "estimated_cost",
        "daily_spend",
    ],
)
@pytest.mark.parametrize("value", [True, "0.5"])
def test_budget_float_measurements_reject_bool_and_strings(field, value):
    with pytest.raises(ValidationError):
        _budget(**{field: value})


def _gateway(
    handler,
    *,
    sleeps: list[float] | None = None,
    attempts: int = 3,
    now=None,
):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        client=client,
        base_url="https://llm.example.test/v1",
        api_key="top-secret-api-key",
        max_attempts=attempts,
        timeout_seconds=2,
        backoff_seconds=0.1,
        sleep=(sleeps.append if sleeps is not None else lambda _seconds: None),
        **({"now": now} if now is not None else {}),
    )
    return (
        LLMGateway(
            provider,
            provider_kind="cloud",
            data_egress_policy=DataEgressPolicy(
                cloud_egress_consent=True,
                fulltext_egress_consent=True,
                max_payload_chars=10_000,
            ),
            cost_guard=CostGuard(
                max_tokens_per_job=10_000,
                max_cost_per_job=10,
                max_daily_cost=100,
                max_concurrent_llm_jobs=10,
            ),
        ),
        client,
    )


def test_structured_success_tracks_usage_cost_and_separates_evidence():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return _success()

    gateway, client = _gateway(handler)
    try:
        result = gateway.complete_structured(
            _request(),
            Summary,
            _budget(input_cost_per_million=2, output_cost_per_million=8),
        )
    finally:
        client.close()

    assert result.value == Summary(title="Grounded", score=0.8)
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 30
    assert result.usage.total_tokens == 150
    assert result.cost_usd == pytest.approx((120 * 2 + 30 * 8) / 1_000_000)
    payload = captured["payload"]
    assert payload["messages"][0] == {
        "role": "system",
        "content": "Return grounded JSON only.",
    }
    assert payload["messages"][1]["role"] == "user"
    assert "Untrusted abstract text." in payload["messages"][1]["content"]
    assert captured["authorization"] == "Bearer top-secret-api-key"
    assert "top-secret-api-key" not in repr(result)


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("not-json", LLMErrorCode.PARSE),
        ('{"title":"missing score"}', LLMErrorCode.VALIDATION),
    ],
)
def test_structured_parse_and_validation_errors_are_normalized(content, code):
    gateway, client = _gateway(lambda _request: _success(content))
    try:
        with pytest.raises(LLMGatewayError) as error:
            gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert error.value.code is code
    assert content not in str(error.value)


def test_timeout_retries_finitely_then_succeeds():
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("secret timeout detail", request=request)
        return _success()

    gateway, client = _gateway(handler, sleeps=sleeps, attempts=3)
    try:
        result = gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert result.value.title == "Grounded"
    assert calls == 3
    assert sleeps == [0.1, 0.2]


def test_429_honors_bounded_retry_after_then_succeeds():
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0.25"},
                text="secret quota body",
            )
        return _success()

    gateway, client = _gateway(handler, sleeps=sleeps)
    try:
        gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert calls == 2
    assert sleeps == [0.25]


def test_429_caps_excessive_retry_after():
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "999999"})
        return _success()

    gateway, client = _gateway(handler, sleeps=sleeps)
    try:
        gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert sleeps == [10]


@pytest.mark.parametrize(
    ("offset_seconds", "expected_delay"),
    [(3, 3), (-5, 0)],
)
def test_429_parses_http_date_against_injected_clock(offset_seconds, expected_delay):
    current = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    retry_at = format_datetime(current + timedelta(seconds=offset_seconds), usegmt=True)
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": retry_at})
        return _success()

    gateway, client = _gateway(handler, sleeps=sleeps, now=lambda: current)
    try:
        gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert sleeps == [expected_delay]


def test_429_invalid_http_date_falls_back_to_exponential_backoff():
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "not-a-date"})
        return _success()

    gateway, client = _gateway(handler, sleeps=sleeps)
    try:
        gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert sleeps == [0.1]


def test_5xx_uses_finite_exponential_backoff():
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="secret upstream") if calls < 3 else _success()

    gateway, client = _gateway(handler, sleeps=sleeps, attempts=3)
    try:
        gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert calls == 3
    assert sleeps == [0.1, 0.2]


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failures_do_not_retry_or_disclose_secrets(status):
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="top-secret-api-key")

    gateway, client = _gateway(handler, attempts=3)
    try:
        with pytest.raises(LLMGatewayError) as error:
            gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert calls == 1
    assert error.value.code is LLMErrorCode.AUTHENTICATION
    assert "top-secret-api-key" not in str(error.value)


def test_exhausted_timeout_returns_redacted_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("token=top-secret-api-key", request=request)

    gateway, client = _gateway(handler, attempts=2)
    try:
        with pytest.raises(LLMGatewayError) as error:
            gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert error.value.code is LLMErrorCode.TIMEOUT
    assert error.value.attempts == 2
    assert str(error.value) == "LLM request timed out"
    assert error.value.__cause__ is None


def test_non_timeout_transport_error_does_not_retry_or_leak_details():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("Authorization=top-secret-api-key", request=request)

    gateway, client = _gateway(handler, attempts=3)
    try:
        with pytest.raises(LLMGatewayError) as error:
            gateway.complete_structured(_request(), Summary, _budget())
    finally:
        client.close()

    assert calls == 1
    assert error.value.code is LLMErrorCode.UPSTREAM
    assert str(error.value) == "LLM transport failed"
    assert error.value.__cause__ is None


class SpyProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, _request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content='{"title":"Grounded","score":0.8}',
            usage=LLMUsage(),
        )


def test_egress_denial_occurs_before_provider_dispatch():
    provider = SpyProvider()
    gateway = LLMGateway(
        provider,
        provider_kind="cloud",
        data_egress_policy=DataEgressPolicy(
            cloud_egress_consent=False,
            fulltext_egress_consent=False,
            max_payload_chars=10_000,
        ),
        cost_guard=CostGuard(
            max_tokens_per_job=10_000,
            max_cost_per_job=10,
            max_daily_cost=100,
            max_concurrent_llm_jobs=10,
        ),
    )

    with pytest.raises(LLMSecurityError):
        gateway.complete_structured(_request(), Summary, _budget())

    assert provider.calls == 0


def test_cost_denial_occurs_before_provider_dispatch():
    provider = SpyProvider()
    gateway = LLMGateway(
        provider,
        provider_kind="cloud",
        data_egress_policy=DataEgressPolicy(
            cloud_egress_consent=True,
            fulltext_egress_consent=True,
            max_payload_chars=10_000,
        ),
        cost_guard=CostGuard(
            max_tokens_per_job=100,
            max_cost_per_job=10,
            max_daily_cost=100,
            max_concurrent_llm_jobs=10,
        ),
    )

    with pytest.raises(LLMSecurityError):
        gateway.complete_structured(_request(), Summary, _budget(estimated_tokens=101))

    assert provider.calls == 0


def test_trusted_provider_kind_mismatch_is_rejected_before_dispatch():
    provider = SpyProvider()
    policy = Mock(spec=DataEgressPolicy)
    guard = Mock(spec=CostGuard)
    gateway = LLMGateway(
        provider,
        provider_kind="cloud",
        data_egress_policy=policy,
        cost_guard=guard,
    )
    mismatched = _request().model_copy(update={"provider_kind": "local"})

    with pytest.raises(LLMSecurityError) as error:
        gateway.complete_structured(mismatched, Summary, _budget())

    assert error.value.code.value == "provider_kind_mismatch"
    policy.authorize.assert_not_called()
    guard.authorize.assert_not_called()
    assert provider.calls == 0
