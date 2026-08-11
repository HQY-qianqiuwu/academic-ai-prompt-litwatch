from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from litwatch.analysis import PaperAnalysisResponse, PaperAnalyzer
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.llm import (
    LLMBudget,
    LLMErrorCode,
    LLMGatewayError,
    LLMResult,
    LLMUsage,
)
from litwatch.models import Paper
from litwatch.pipeline import Pipeline


def _paper(*, abstract: str = "An abstract reports a verified result.") -> Paper:
    return Paper(
        canonical_id="paper:1",
        title="Underwater acoustic localization",
        abstract=abstract,
        score=0.8,
    )


def _topic() -> Topic:
    return Topic(
        id="underwater",
        name="Underwater localization",
        query="underwater acoustic localization",
        include=["TDOA", "localization"],
    )


def _budget(_request) -> LLMBudget:
    return LLMBudget(
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
        estimated_tokens=1_000,
        estimated_cost=0.0,
    )


class FakeGateway:
    provider_kind = "cloud"

    def __init__(self) -> None:
        self.requests = []
        self.budgets = []

    def complete_structured(self, request, response_model, budget):
        self.requests.append(request)
        self.budgets.append(budget)
        value = response_model.model_validate(
            {
                "one_liner": "A grounded result.",
                "motivation": "A grounded motivation.",
                "methods": ["TDOA"],
                "results": ["Lower error"],
                "limitations": ["Abstract evidence only"],
                "relevance": "Directly relevant",
                "paper_type": "method",
                "research_gap": "Requires broader validation",
                "reading_priority": 4,
                "workflow_output": {"decision": "read"},
                "evidence_level": request.evidence_scope,
                "confidence": 0.8,
            }
        )
        return LLMResult(
            value=value,
            usage=LLMUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            cost_usd=0.0,
            provider_request_id="safe-request-id",
            model="test-model",
        )


def test_analyzer_uses_injected_gateway_without_direct_http_client():
    gateway = FakeGateway()
    analyzer = PaperAnalyzer(
        Settings(llm_api_key="configured", _env_file=None),
        gateway=gateway,
        budget_factory=_budget,
    )

    result = analyzer.analyze(_paper(), _topic())

    assert result["status"] == "ok"
    assert result["one_liner"] == "A grounded result."
    assert len(gateway.requests) == 1
    assert not hasattr(analyzer, "client")


def test_analyzer_without_credentials_uses_extractive_fallback_and_no_gateway():
    gateway = FakeGateway()
    analyzer = PaperAnalyzer(
        Settings(llm_api_key="", _env_file=None),
        gateway=gateway,
        budget_factory=_budget,
    )

    result = analyzer.analyze(_paper(), _topic())

    assert result["status"] == "extractive"
    assert gateway.requests == []


def test_analyzer_preserves_abstract_and_fulltext_evidence_scope():
    gateway = FakeGateway()
    analyzer = PaperAnalyzer(
        Settings(llm_api_key="configured", _env_file=None),
        gateway=gateway,
        budget_factory=_budget,
    )

    abstract_result = analyzer.analyze(_paper(), _topic())
    fulltext_result = analyzer.analyze(
        _paper(), _topic(), fulltext="Verified full-text excerpt."
    )

    assert gateway.requests[0].evidence_scope == "abstract"
    assert abstract_result["evidence_level"] == "abstract"
    assert gateway.requests[1].evidence_scope == "fulltext_excerpt"
    assert fulltext_result["evidence_level"] == "fulltext_excerpt"


class FailingGateway(FakeGateway):
    def complete_structured(self, request, response_model, budget):
        self.requests.append(request)
        try:
            raise RuntimeError("credential=must-not-escape")
        except RuntimeError as cause:
            raise LLMGatewayError(
                LLMErrorCode.UPSTREAM,
                "LLM provider unavailable",
            ) from cause


def test_analyzer_returns_normalized_safe_gateway_failure():
    gateway = FailingGateway()
    analyzer = PaperAnalyzer(
        Settings(llm_api_key="configured", _env_file=None),
        gateway=gateway,
        budget_factory=_budget,
    )

    result = analyzer.analyze(_paper(), _topic())

    assert result == {
        "status": "error",
        "reason": "LLM provider unavailable",
        "evidence_level": "abstract",
    }
    assert "must-not-escape" not in repr(result)


def test_analysis_prompt_preserves_field_specific_evidence_rules():
    gateway = FakeGateway()
    analyzer = PaperAnalyzer(
        Settings(llm_api_key="configured", _env_file=None),
        gateway=gateway,
        budget_factory=_budget,
    )

    analyzer.analyze(_paper(), _topic())

    request = gateway.requests[0]
    assert "摘要未报告" in request.system_instruction
    assert "原文未明确说明" in request.system_instruction
    assert "theory/method/experiment/application/review" in request.system_instruction
    assert "workflow_output" in request.system_instruction
    assert "证据范围：abstract" in request.user_instruction


def test_analysis_schema_rejects_unknown_paper_type():
    with pytest.raises(ValidationError):
        PaperAnalysisResponse.model_validate(
            {
                "paper_type": "hallucinated-category",
                "evidence_level": "abstract",
            }
        )


def test_pipeline_wires_production_gateway_when_credentials_are_configured(tmp_path):
    database = Database(tmp_path / "pipeline.db")
    pipeline = Pipeline(
        Settings(
            llm_api_key="configured",
            llm_cloud_egress_consent=True,
            _env_file=None,
        ),
        database,
    )

    assert pipeline.analyzer.enabled is True
    assert pipeline.analyzer.gateway is not None
    assert pipeline.analyzer.gateway.provider_kind == "cloud"
    runtime_client = pipeline._llm_runtime.client

    pipeline.close()
    assert runtime_client.is_closed is True
    database.connection.close()


def test_pipeline_without_credentials_keeps_extractive_analyzer(tmp_path):
    database = Database(tmp_path / "pipeline-no-key.db")
    pipeline = Pipeline(Settings(llm_api_key="", _env_file=None), database)

    assert pipeline.analyzer.enabled is False
    assert pipeline.analyzer.gateway is None

    pipeline.close()
    database.connection.close()


def test_production_gateway_denies_cloud_egress_before_http(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    database = Database(tmp_path / "pipeline-denied.db")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = Pipeline(
        Settings(
            llm_api_key="configured",
            llm_cloud_egress_consent=False,
            _env_file=None,
        ),
        database,
        llm_http_client=client,
    )

    result = pipeline.analyzer.analyze(_paper(), _topic())

    assert result["status"] == "error"
    assert result["reason"] == "Cloud LLM data egress is not authorized"
    assert requests == []

    pipeline.close()
    assert client.is_closed is False
    client.close()
    database.connection.close()
