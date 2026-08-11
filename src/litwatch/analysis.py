from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from litwatch.config import Settings, Topic
from litwatch.llm import LLMBudget, LLMGateway, LLMGatewayError, LLMRequest
from litwatch.llm.security import LLMSecurityError
from litwatch.models import Paper


class PaperAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    one_liner: str = "LLM 未返回 one_liner"
    motivation: str = "LLM 未返回 motivation"
    methods: list[str] = Field(default_factory=list)
    results: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    relevance: str = "LLM 未返回 relevance"
    paper_type: Literal[
        "theory", "method", "experiment", "application", "review"
    ] = "method"
    research_gap: str = "LLM 未返回 research_gap"
    reading_priority: int = Field(default=3, ge=1, le=5)
    workflow_output: dict[str, object] = Field(default_factory=dict)
    evidence_level: Literal["abstract", "fulltext_excerpt"] = "abstract"
    confidence: float = Field(default=0.5, ge=0, le=1)


_SYSTEM_INSTRUCTION = """你是严谨的科研文献筛选助手。只能依据提供的论文证据，不得补充未出现的事实、论文或引用。
返回单个 JSON 对象，只能包含以下字段，并遵守各字段的证据规则：
- one_liner：一句话中文结论。
- motivation：研究动机；证据未说明时明确写“原文未明确说明”。
- methods：核心方法，字符串数组；证据未说明时返回空数组。
- results：主要结果，字符串数组；无定量或可核实结果时明确写“摘要未报告”。
- limitations：局限，字符串数组；证据未说明时明确写“原文未明确说明”。
- relevance：与研究主题的具体关系，只能依据当前证据。
- paper_type：只能是 theory/method/experiment/application/review 之一。
- research_gap：本文暴露或试图填补的研究空白；证据不足时明确说明，不得猜测。
- reading_priority：1 到 5 的整数。
- workflow_output：严格根据用户消息中的分析工作流及其要求生成 JSON 对象。
- evidence_level：只能与调用方声明的 abstract 或 fulltext_excerpt 证据范围一致。
- confidence：0 到 1；仅反映当前 evidence_level 支持程度。"""


class PaperAnalyzer:
    def __init__(
        self,
        settings: Settings,
        *,
        gateway: LLMGateway | None = None,
        budget_factory: Callable[[LLMRequest], LLMBudget] | None = None,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.budget_factory = budget_factory

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.llm_api_key
            and self.gateway is not None
            and self.budget_factory is not None
        )

    def analyze(
        self,
        paper: Paper,
        topic: Topic,
        fulltext: str = "",
    ) -> dict[str, object]:
        if not self.enabled:
            return self._extractive_fallback(paper, topic)
        evidence = fulltext or paper.abstract
        if not evidence:
            return {
                "status": "skipped",
                "reason": "无摘要或可用全文",
                "evidence_level": "none",
            }

        modes = {mode.id: mode for mode in self.settings.load_analysis_modes()}
        mode = modes.get(topic.analysis_mode) or modes["quick_scan"]
        evidence_scope: Literal["abstract", "fulltext_excerpt"] = (
            "fulltext_excerpt" if fulltext else "abstract"
        )
        if self.gateway is None or self.budget_factory is None:  # pragma: no cover
            return self._extractive_fallback(paper, topic)
        request = LLMRequest(
            model=self.settings.llm_model,
            system_instruction=_SYSTEM_INSTRUCTION,
            user_instruction=(
                f"研究主题：{topic.name}\n"
                f"关注点：{', '.join(topic.include)}\n"
                f"分析工作流：{mode.name}\n"
                f"工作流要求：{mode.instruction}\n"
                f"论文标题：{paper.title}\n"
                f"证据范围：{evidence_scope}"
            ),
            untrusted_evidence=evidence[:36_000],
            provider_kind=self.gateway.provider_kind,
            evidence_scope=evidence_scope,
            max_output_tokens=self.settings.llm_max_output_tokens,
        )
        try:
            response = self.gateway.complete_structured(
                request,
                PaperAnalysisResponse,
                self.budget_factory(request),
            )
        except (LLMGatewayError, LLMSecurityError) as exc:
            return {
                "status": "error",
                "reason": str(exc),
                "evidence_level": evidence_scope,
            }

        value = response.value
        result = value.model_dump()
        result["status"] = "ok"
        result["evidence_level"] = evidence_scope
        expected_fields = set(PaperAnalysisResponse.model_fields) - {"evidence_level"}
        if not expected_fields.issubset(value.model_fields_set):
            result["confidence"] = min(float(result["confidence"]), 0.3)
        return result

    @staticmethod
    def _extractive_fallback(paper: Paper, topic: Topic) -> dict[str, object]:
        text = " ".join(paper.abstract.split())
        if not text:
            return {
                "status": "skipped",
                "reason": "无摘要或可用全文",
                "evidence_level": "none",
            }

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
            if sentence.strip()
        ]
        method_words = (
            "propose",
            "method",
            "framework",
            "model",
            "algorithm",
            "develop",
            "technique",
            "approach",
            "architecture",
            "design",
            "implement",
            "scheme",
            "strategy",
            "solution",
            "present",
            "introduce",
            "devise",
            "formulate",
            "construct",
            "establish",
            "derive",
        )
        result_words = (
            "result",
            "show",
            "demonstrate",
            "achieve",
            "improve",
            "outperform",
            "obtain",
            "reach",
            "yield",
            "exhibit",
            "reveal",
            "indicate",
            "suggest",
            "confirm",
            "validate",
            "verify",
            "prove",
            "evidence",
        )
        limitation_words = (
            "limit",
            "challenge",
            "however",
            "remain",
            "future work",
            "shortcoming",
            "drawback",
            "weakness",
            "constraint",
            "restrict",
            "assume",
            "caveat",
            "open question",
            "further",
            "need",
        )
        conclusion_words = (
            "conclude",
            "demonstrate",
            "show",
            "propose",
            "result",
            "find",
        )

        def select(keywords: tuple[str, ...], limit: int = 3) -> list[str]:
            matches = [
                sentence
                for sentence in sentences
                if any(keyword in sentence.casefold() for keyword in keywords)
            ]
            return matches[:limit]

        methods = select(method_words)
        results = select(result_words)
        limitations = select(limitation_words)
        one_liner_sentences = [
            sentence
            for sentence in sentences
            if any(keyword in sentence.casefold() for keyword in conclusion_words)
        ]
        one_liner = (
            one_liner_sentences[0][:500]
            if one_liner_sentences
            else sentences[0][:500]
        )

        folded = text.casefold()
        type_scores = {
            "theory": sum(
                word in folded
                for word in ("theorem", "proof", "theoretical", "bound", "derive")
            ),
            "method": sum(
                word in folded
                for word in (
                    "propose",
                    "method",
                    "framework",
                    "algorithm",
                    "architecture",
                    "technique",
                    "design",
                )
            ),
            "experiment": sum(
                word in folded
                for word in (
                    "experiment",
                    "simulation",
                    "measure",
                    "benchmark",
                    "dataset",
                    "evaluat",
                )
            ),
            "application": sum(
                word in folded
                for word in (
                    "apply",
                    "deploy",
                    "real-world",
                    "implement",
                    "system",
                    "field test",
                )
            ),
            "review": sum(
                word in folded
                for word in ("survey", "review", "overview", "taxonomy", "compar")
            ),
        }
        paper_type = max(type_scores, key=type_scores.get) if methods else "unknown"
        relevance_terms = [
            term
            for term in topic.include
            if term.casefold() in f"{paper.title} {paper.abstract}".casefold()
        ]
        return {
            "status": "extractive",
            "one_liner": one_liner,
            "motivation": sentences[0][:800],
            "methods": methods or ["摘要未明确给出可自动提取的方法句"],
            "results": results or ["摘要未报告可自动识别的结果句"],
            "limitations": limitations or ["摘要未明确说明局限"],
            "relevance": (
                f"命中主题短语：{', '.join(relevance_terms)}"
                if relevance_terms
                else "需结合全文人工判断与主题的具体关系"
            ),
            "paper_type": paper_type,
            "research_gap": "基础提炼模式不推断摘要未明确陈述的研究空白",
            "reading_priority": max(1, min(5, round(paper.score * 5))),
            "workflow_output": {
                "mode": topic.analysis_mode,
                "note": "这是无需 LLM 的摘要抽取结果；配置模型后可生成深度综述矩阵。",
            },
            "evidence_level": "abstract",
            "confidence": 0.35,
        }
