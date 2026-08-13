from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import litwatch.pipeline as pipeline_module
from litwatch.analysis_models import EvidenceScope, PaperAnalysis
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.models import Paper
from litwatch.pipeline import Pipeline
from litwatch.services.literature_search import (
    LiteratureSearchDiagnostics,
    LiteratureSearchResult,
)
from litwatch.services.paper_analysis import AnalysisContext, PaperAnalysisService


def _paper(*, canonical_id: str = "paper:1", abstract: str = "Evidence.") -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title="Underwater acoustic localization",
        abstract=abstract,
        score=0.8,
        score_detail={
            "rank_score": 0.8,
            "relevance_score": 0.8,
            "quality_score": 0.8,
        },
    )


def _topic() -> Topic:
    return Topic(
        id="underwater",
        name="Underwater localization",
        query="underwater acoustic localization",
        include=["TDOA"],
        min_score=0,
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.persisted: list[PaperAnalysis] = []

    def get(self, **_identity):
        return None

    def upsert(self, analysis: PaperAnalysis) -> PaperAnalysis:
        self.persisted.append(analysis)
        return analysis


class FakeAnalyzer:
    def __init__(self, result: dict[str, object] | Exception, *, enabled: bool) -> None:
        self.result = result
        self.enabled = enabled
        self.calls = 0
        self.settings = Settings(llm_api_key=("configured" if enabled else ""), _env_file=None)
        self.gateway = SimpleNamespace(provider_kind="cloud") if enabled else None

    def analyze(self, _paper, _topic, _fulltext=""):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_paper_analysis_service_runs_typed_steps_in_order_and_persists_once():
    repository = RecordingRepository()
    analyzer = FakeAnalyzer(
        {
            "status": "ok",
            "motivation": "A grounded motivation.",
            "methods": ["TDOA"],
            "results": ["Lower error"],
            "limitations": [],
        },
        enabled=True,
    )
    service = PaperAnalysisService(analyzer=analyzer, repository=repository)
    context = AnalysisContext(
        paper=_paper(),
        topic=_topic(),
        evidence="Evidence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )

    result = service.analyze(context)

    assert isinstance(result, PaperAnalysis)
    assert result.status.value == "completed"
    assert result.main_results == ["Lower error"]
    assert [entry.step for entry in context.trace] == [
        "validate_paper",
        "prepare_analysis_input",
        "analyze_with_gateway",
        "validate_paper_analysis",
        "persist_paper_analysis",
    ]
    assert all(entry.status == "completed" for entry in context.trace)
    assert repository.persisted == [result]
    assert analyzer.calls == 1


def test_service_skips_model_without_evidence_and_persists_skipped_result():
    repository = RecordingRepository()
    analyzer = FakeAnalyzer(AssertionError("must not call analyzer"), enabled=True)
    context = AnalysisContext(
        paper=_paper(abstract=""),
        topic=_topic(),
        evidence="",
        evidence_scope=EvidenceScope.METADATA_ONLY,
    )

    result = PaperAnalysisService(analyzer=analyzer, repository=repository).analyze(
        context
    )

    assert result.status.value == "skipped"
    assert result.research_question is None
    assert result.methods == []
    assert analyzer.calls == 0
    assert len(repository.persisted) == 1
    assert "analyze_with_gateway" not in [entry.step for entry in context.trace]


def test_service_uses_extractive_fallback_without_credentials():
    repository = RecordingRepository()
    analyzer = FakeAnalyzer(
        {
            "status": "extractive",
            "motivation": "Evidence sentence.",
            "methods": [],
            "results": [],
            "limitations": [],
        },
        enabled=False,
    )
    context = AnalysisContext(
        paper=_paper(),
        topic=_topic(),
        evidence="Evidence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )

    result = PaperAnalysisService(analyzer=analyzer, repository=repository).analyze(
        context
    )

    assert result.status.value == "extractive"
    assert analyzer.calls == 1
    assert "extractive_fallback" in [entry.step for entry in context.trace]
    assert "analyze_with_gateway" not in [entry.step for entry in context.trace]


def test_analysis_failure_trace_is_safe_and_does_not_persist_raw_error():
    repository = RecordingRepository()
    analyzer = FakeAnalyzer(RuntimeError("Authorization=secret-value"), enabled=True)
    context = AnalysisContext(
        paper=_paper(),
        topic=_topic(),
        evidence="Evidence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )

    result = PaperAnalysisService(analyzer=analyzer, repository=repository).analyze(
        context
    )

    assert result.status.value == "failed"
    assert len(repository.persisted) == 1
    rendered_trace = repr(context.trace)
    assert "secret-value" not in rendered_trace
    assert "Authorization" not in rendered_trace
    assert context.trace[-3].safe_error == "analysis_failed"


def test_invalid_analyzer_output_becomes_safe_failed_analysis_and_persists_once():
    repository = RecordingRepository()
    analyzer = FakeAnalyzer(
        {
            "status": "ok",
            "methods": "not a list",
            "evidence": ["not typed evidence"],
        },
        enabled=True,
    )
    context = AnalysisContext(
        paper=_paper(),
        topic=_topic(),
        evidence="Evidence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )

    result = PaperAnalysisService(analyzer=analyzer, repository=repository).analyze(
        context
    )

    assert result.status.value == "failed"
    assert repository.persisted == [result]
    assert context.trace[-3].safe_error == "analysis_failed"
    assert "not typed evidence" not in repr(context.trace)


class FakeSearchService:
    def __init__(self, papers: list[Paper]) -> None:
        self.papers = papers
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs) -> LiteratureSearchResult:
        self.calls.append(kwargs)
        return LiteratureSearchResult(
            query=str(kwargs["topic"]),
            papers=[paper.model_copy(deep=True) for paper in self.papers],
            diagnostics=LiteratureSearchDiagnostics(
                raw_count=len(self.papers),
                dedup_count=len(self.papers),
            ),
        )


class FakeAnalysisService:
    def __init__(self) -> None:
        self.contexts: list[AnalysisContext] = []

    def analyze(self, context: AnalysisContext) -> PaperAnalysis:
        self.contexts.append(context)
        return PaperAnalysis(
            canonical_id=context.paper.canonical_id,
            analysis_version="v2.0",
            evidence_hash="a" * 64,
            model_config_hash="b" * 64,
            status="extractive",
            evidence_scope=context.evidence_scope,
            motivation=context.evidence,
        )


def test_pipeline_uses_injected_search_service_and_preserves_compatibility_return(
    tmp_path,
):
    database = Database(tmp_path / "pipeline.db")
    papers = [_paper(canonical_id="paper:ranked-1"), _paper(canonical_id="paper:ranked-2")]
    papers[0].score = 0.9
    papers[1].score = 0.8
    search = FakeSearchService(papers)
    analysis = FakeAnalysisService()
    pipeline = Pipeline(
        Settings(
            llm_api_key="",
            analyze_top_n=2,
            fulltext_top_n=0,
            _env_file=None,
        ),
        database,
        literature_search_service=search,
        paper_analysis_service=analysis,
    )

    summary, returned = pipeline.run(days=7, topics=[_topic()])

    assert summary.fetched == 2
    assert summary.deduplicated == 2
    assert summary.accepted == 2
    assert summary.analyzed == 2
    assert [paper.canonical_id for paper in returned] == [
        "paper:ranked-1",
        "paper:ranked-2",
    ]
    assert len(search.calls) == 1
    assert search.calls[0]["topic"] == _topic().query
    assert len(analysis.contexts) == 2
    assert all(paper.analysis["status"] == "extractive" for paper in returned)
    pipeline.close()
    database.connection.close()


def test_pipeline_module_does_not_construct_or_import_provider_classes():
    tree = ast.parse(Path(pipeline_module.__file__).read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert not any(module.startswith("litwatch.sources") for module in imports)
    assert {"OpenAlexSource", "ArxivSource", "SemanticScholarSource"}.isdisjoint(names)


def test_analysis_context_rejects_unknown_fields():
    with pytest.raises(TypeError):
        AnalysisContext(
            paper=_paper(),
            topic=_topic(),
            evidence="Evidence.",
            evidence_scope=EvidenceScope.ABSTRACT,
            raw_secret="not allowed",
        )
