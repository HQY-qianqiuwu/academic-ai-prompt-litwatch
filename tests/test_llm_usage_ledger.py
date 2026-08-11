from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

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
)
from litwatch.llm.security import (
    CostGuard,
    DataEgressPolicy,
    LLMSecurityError,
    LLMSecurityErrorCode,
    LLMUsageLedger,
)


class Result(BaseModel):
    answer: str


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current


def _guard(*, daily: float = 1.0, concurrent: int = 2) -> CostGuard:
    return CostGuard(
        max_tokens_per_job=10_000,
        max_cost_per_job=1.0,
        max_daily_cost=daily,
        max_concurrent_llm_jobs=concurrent,
    )


def _request() -> LLMRequest:
    return LLMRequest(
        model="test-model",
        system_instruction="Return JSON.",
        user_instruction="Analyze.",
        untrusted_evidence="Evidence.",
        provider_kind="cloud",
        evidence_scope="abstract",
    )


def _budget(*, estimate: float = 0.1) -> LLMBudget:
    return LLMBudget(
        input_cost_per_million=1_000.0,
        output_cost_per_million=0.0,
        estimated_tokens=100,
        estimated_cost=estimate,
    )


def _policy() -> DataEgressPolicy:
    return DataEgressPolicy(
        cloud_egress_consent=True,
        fulltext_egress_consent=True,
        max_payload_chars=10_000,
    )


def test_second_request_is_denied_after_cumulative_actual_spend():
    ledger = LLMUsageLedger(_guard(daily=0.15), now=MutableClock())
    first = ledger.reserve(estimated_tokens=100, estimated_cost=0.05)
    ledger.settle(first, actual_cost=0.10)

    with pytest.raises(LLMSecurityError) as error:
        ledger.reserve(estimated_tokens=100, estimated_cost=0.10)

    assert error.value.code is LLMSecurityErrorCode.DAILY_COST_LIMIT_EXCEEDED
    assert ledger.daily_spend == pytest.approx(0.10)
    assert ledger.active_jobs == 0


def test_concurrent_reservations_are_authorized_and_reserved_atomically():
    ledger = LLMUsageLedger(_guard(concurrent=1), now=MutableClock())

    def reserve_once():
        try:
            return ledger.reserve(estimated_tokens=100, estimated_cost=0.01)
        except LLMSecurityError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: reserve_once(), range(2)))

    reservations = [item for item in outcomes if not isinstance(item, LLMSecurityErrorCode)]
    denials = [item for item in outcomes if isinstance(item, LLMSecurityErrorCode)]
    assert len(reservations) == 1
    assert denials == [LLMSecurityErrorCode.CONCURRENCY_LIMIT_EXCEEDED]
    assert ledger.active_jobs == 1
    ledger.release(reservations[0])
    assert ledger.active_jobs == 0


def test_pending_estimates_are_reserved_against_the_daily_limit():
    ledger = LLMUsageLedger(_guard(daily=0.15, concurrent=2), now=MutableClock())
    first = ledger.reserve(estimated_tokens=100, estimated_cost=0.10)

    with pytest.raises(LLMSecurityError) as error:
        ledger.reserve(estimated_tokens=100, estimated_cost=0.10)

    assert error.value.code is LLMSecurityErrorCode.DAILY_COST_LIMIT_EXCEEDED
    ledger.release(first)


def test_settlement_rejects_negative_actual_cost_without_releasing_reservation():
    ledger = LLMUsageLedger(_guard(), now=MutableClock())
    reservation = ledger.reserve(estimated_tokens=100, estimated_cost=0.10)

    with pytest.raises(ValueError, match="actual_cost"):
        ledger.settle(reservation, actual_cost=-0.01)

    assert ledger.active_jobs == 1
    assert ledger.daily_spend == 0
    ledger.release(reservation)


class FailingProvider:
    calls = 0

    def complete(self, _request: LLMRequest) -> LLMResponse:
        self.calls += 1
        raise LLMGatewayError(LLMErrorCode.UPSTREAM, "LLM provider unavailable")


def test_gateway_releases_active_reservation_on_provider_failure():
    ledger = LLMUsageLedger(_guard(concurrent=1), now=MutableClock())
    gateway = LLMGateway(
        FailingProvider(),
        provider_kind="cloud",
        data_egress_policy=_policy(),
        usage_ledger=ledger,
    )

    with pytest.raises(LLMGatewayError):
        gateway.complete_structured(_request(), Result, _budget())

    assert ledger.active_jobs == 0
    assert ledger.daily_spend == 0


class SuccessfulProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, _request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content='{"answer":"grounded"}',
            usage=LLMUsage(input_tokens=100, output_tokens=0, total_tokens=100),
        )


def test_gateway_settles_actual_response_cost_before_next_authorization():
    provider = SuccessfulProvider()
    ledger = LLMUsageLedger(_guard(daily=0.15), now=MutableClock())
    gateway = LLMGateway(
        provider,
        provider_kind="cloud",
        data_egress_policy=_policy(),
        usage_ledger=ledger,
    )

    result = gateway.complete_structured(_request(), Result, _budget(estimate=0.05))
    assert result.cost_usd == pytest.approx(0.10)

    with pytest.raises(LLMSecurityError):
        gateway.complete_structured(_request(), Result, _budget(estimate=0.10))

    assert provider.calls == 1
    assert ledger.daily_spend == pytest.approx(0.10)
    assert ledger.active_jobs == 0


def test_daily_spend_rolls_over_using_injected_utc_clock():
    clock = MutableClock()
    ledger = LLMUsageLedger(_guard(daily=1.0), now=clock)
    first = ledger.reserve(estimated_tokens=100, estimated_cost=0.9)
    ledger.settle(first, actual_cost=0.9)

    clock.current += timedelta(days=1)
    second = ledger.reserve(estimated_tokens=100, estimated_cost=0.2)

    assert ledger.daily_spend == 0
    ledger.release(second)


def test_budget_rejects_caller_supplied_usage_ledger_state():
    with pytest.raises(ValidationError):
        LLMBudget(
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
            estimated_tokens=100,
            estimated_cost=0.0,
            daily_spend=0.0,
            active_jobs=0,
        )
