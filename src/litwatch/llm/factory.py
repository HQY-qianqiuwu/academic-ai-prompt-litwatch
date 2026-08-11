from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

import httpx

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.llm.gateway import LLMGateway
from litwatch.llm.models import LLMBudget, LLMRequest
from litwatch.llm.openai_compatible import OpenAICompatibleProvider
from litwatch.llm.security import CostGuard, DataEgressPolicy, LLMUsageLedger


@dataclass(slots=True)
class LLMRuntime:
    gateway: LLMGateway
    budget_factory: Callable[[LLMRequest], LLMBudget]
    client: httpx.Client
    owns_client: bool

    def close(self) -> None:
        if self.owns_client:
            self.client.close()


def build_llm_runtime(
    settings: Settings,
    *,
    database: Database,
    client: httpx.Client | None = None,
) -> LLMRuntime | None:
    """Build the production LLM boundary; no credential means no model runtime."""
    if not settings.llm_api_key:
        return None
    owns_client = client is None
    transport_client = client or httpx.Client()
    provider = OpenAICompatibleProvider(
        client=transport_client,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.request_timeout_seconds,
    )
    gateway = LLMGateway(
        provider,
        provider_kind=settings.llm_provider_kind,
        data_egress_policy=DataEgressPolicy(
            cloud_egress_consent=settings.llm_cloud_egress_consent,
            fulltext_egress_consent=settings.llm_fulltext_egress_consent,
            max_payload_chars=settings.llm_max_payload_chars,
        ),
        usage_ledger=LLMUsageLedger(
            database,
            CostGuard(
                max_tokens_per_job=settings.max_tokens_per_job,
                max_cost_per_job=settings.max_cost_per_job,
                max_daily_cost=settings.max_daily_cost,
                max_concurrent_llm_jobs=settings.max_concurrent_llm_jobs,
            ),
            lease_seconds=max(
                settings.job_default_timeout_seconds,
                ceil(settings.request_timeout_seconds * 3 + 30),
            ),
        ),
    )

    def budget_factory(request: LLMRequest) -> LLMBudget:
        input_tokens = ceil(
            (len(request.system_instruction) + request.payload_chars) / 4
        )
        estimated_tokens = input_tokens + request.max_output_tokens
        estimated_cost = (
            input_tokens * settings.llm_input_cost_per_million
            + request.max_output_tokens * settings.llm_output_cost_per_million
        ) / 1_000_000
        return LLMBudget(
            input_cost_per_million=float(settings.llm_input_cost_per_million),
            output_cost_per_million=float(settings.llm_output_cost_per_million),
            estimated_tokens=estimated_tokens,
            estimated_cost=float(estimated_cost),
        )

    return LLMRuntime(
        gateway=gateway,
        budget_factory=budget_factory,
        client=transport_client,
        owns_client=owns_client,
    )
