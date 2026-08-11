from __future__ import annotations

import json
from threading import Event, Thread
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from litwatch.llm.models import (
    LLMBudget,
    LLMErrorCode,
    LLMGatewayError,
    LLMRequest,
    LLMResponse,
    LLMResult,
)
from litwatch.llm.security import (
    DataEgressPolicy,
    LLMSecurityError,
    LLMSecurityErrorCode,
    LLMUsageLedger,
)


class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


StructuredValue = TypeVar("StructuredValue", bound=BaseModel)


class LLMGateway:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        provider_kind: Literal["local", "cloud"],
        data_egress_policy: DataEgressPolicy,
        usage_ledger: LLMUsageLedger,
    ) -> None:
        self.provider = provider
        if provider_kind not in {"local", "cloud"}:
            raise ValueError("provider_kind must be 'local' or 'cloud'")
        self.provider_kind = provider_kind
        self.data_egress_policy = data_egress_policy
        self.usage_ledger = usage_ledger

    def complete_structured(
        self,
        request: LLMRequest,
        response_model: type[StructuredValue],
        budget: LLMBudget,
    ) -> LLMResult[StructuredValue]:
        if request.provider_kind != self.provider_kind:
            raise LLMSecurityError(
                LLMSecurityErrorCode.PROVIDER_KIND_MISMATCH,
                "LLM provider classification does not match trusted configuration",
            )
        self.data_egress_policy.authorize(
            self.provider_kind,
            request.evidence_scope,
            request.payload_chars,
        )
        reservation = self.usage_ledger.reserve(
            estimated_tokens=budget.estimated_tokens,
            estimated_cost=budget.estimated_cost,
        )
        heartbeat_stop = Event()

        def renew_reservation() -> None:
            while not heartbeat_stop.wait(
                self.usage_ledger.heartbeat_interval_seconds
            ):
                try:
                    self.usage_ledger.renew(reservation)
                except Exception:  # noqa: BLE001 - background renewal stays redacted
                    return

        heartbeat = Thread(
            target=renew_reservation,
            name=(
                "litwatch-llm-usage-heartbeat-"
                f"{reservation.reservation_id[:8]}"
            ),
            daemon=True,
        )
        heartbeat.start()
        actual_cost = 0.0
        try:
            response = self.provider.complete(request)
            actual_cost = (
                response.usage.input_tokens * budget.input_cost_per_million
                + response.usage.output_tokens * budget.output_cost_per_million
            ) / 1_000_000

            parsed: object | None = None
            parse_failed = False
            try:
                parsed = json.loads(response.content)
            except (TypeError, json.JSONDecodeError):
                parse_failed = True
            if parse_failed:
                raise LLMGatewayError(
                    LLMErrorCode.PARSE, "LLM response was not valid JSON"
                ) from None

            value: StructuredValue | None = None
            validation_failed = False
            try:
                value = response_model.model_validate(parsed)
            except ValidationError:
                validation_failed = True
            if validation_failed or value is None:
                raise LLMGatewayError(
                    LLMErrorCode.VALIDATION,
                    "LLM response did not match the required schema",
                ) from None

            return LLMResult(
                value=value,
                usage=response.usage,
                cost_usd=actual_cost,
                provider_request_id=response.provider_request_id,
                model=response.model,
            )
        finally:
            heartbeat_stop.set()
            heartbeat.join()
            self.usage_ledger.settle(reservation, actual_cost=actual_cost)
