from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import litwatch.pipeline as pipeline_module
from litwatch.analysis import PaperAnalyzer
from litwatch.analysis_models import EvidenceScope, PaperAnalysis
from litwatch.analysis_repository import AnalysisRepository
from litwatch.config import AnalysisMode, Settings, Topic
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


class CachingRepository(RecordingRepository):
    def __init__(self) -> None:
        super().__init__()
        self.records: dict[tuple[str, str, str, str], PaperAnalysis] = {}

    def get(self, **identity):
        return self.records.get(
            (
                identity["canonical_id"],
                identity["analysis_version"],
                identity["evidence_hash"],
                identity["model_config_hash"],
            )
        )

    def upsert(self, analysis: PaperAnalysis) -> PaperAnalysis:
        self.persisted.append(analysis)
        self.records[
            (
                analysis.canonical_id,
                analysis.analysis_version,
                analysis.evidence_hash,
                analysis.model_config_hash,
            )
        ] = analysis
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


def test_extractive_analysis_keeps_missing_facts_none_or_empty():
    repository = RecordingRepository()
    analyzer = PaperAnalyzer(Settings(llm_api_key="", _env_file=None))
    context = AnalysisContext(
        paper=_paper(abstract="A neutral abstract sentence."),
        topic=_topic(),
        evidence="A neutral abstract sentence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )

    result = PaperAnalysisService(analyzer=analyzer, repository=repository).analyze(
        context
    )

    assert result.status.value == "extractive"
    assert result.methods == []
    assert result.main_results == []
    assert result.limitations == []
    assert result.research_question is None
    assert repository.persisted == [result]


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


def test_invalid_context_adds_safe_failed_validation_trace():
    paper = _paper()
    paper.canonical_id = ""
    context = AnalysisContext(
        paper=paper,
        topic=_topic(),
        evidence="Evidence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )
    service = PaperAnalysisService(
        analyzer=FakeAnalyzer({}, enabled=True), repository=RecordingRepository()
    )

    with pytest.raises(ValueError, match="canonical_id"):
        service.analyze(context)

    assert context.trace[-1].step == "validate_paper"
    assert context.trace[-1].status == "failed"
    assert context.trace[-1].safe_error == "invalid_paper"


def test_persistence_failure_adds_safe_failed_trace():
    class FailingRepository:
        def get(self, **_identity):
            return None

        def upsert(self, _analysis):
            raise RuntimeError("Authorization=secret-value")

    context = AnalysisContext(
        paper=_paper(),
        topic=_topic(),
        evidence="Evidence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )
    service = PaperAnalysisService(
        analyzer=FakeAnalyzer({"status": "ok"}, enabled=True),
        repository=FailingRepository(),
    )

    with pytest.raises(RuntimeError, match="secret-value"):
        service.analyze(context)

    assert context.trace[-1].step == "persist_paper_analysis"
    assert context.trace[-1].status == "failed"
    assert context.trace[-1].safe_error == "persistence_failed"
    assert "secret-value" not in repr(context.trace)


def test_analysis_cache_identity_includes_request_affecting_configuration(monkeypatch):
    repository = CachingRepository()
    analyzer = FakeAnalyzer(
        {"status": "ok", "methods": [], "results": [], "limitations": []},
        enabled=True,
    )
    analyzer.settings = Settings(
        llm_api_key="configured",
        llm_max_output_tokens=128,
        _env_file=None,
    )
    mode = AnalysisMode(
        id="quick_scan",
        name="Initial mode name",
        description="A test mode",
        instruction="Initial mode instruction",
    )
    monkeypatch.setattr(Settings, "load_analysis_modes", lambda _settings: [mode])
    service = PaperAnalysisService(analyzer=analyzer, repository=repository)
    context = AnalysisContext(
        paper=_paper(),
        topic=_topic(),
        evidence="Evidence.",
        evidence_scope=EvidenceScope.ABSTRACT,
    )

    service.analyze(context)
    service.analyze(
        AnalysisContext(
            paper=_paper(),
            topic=_topic().model_copy(update={"name": "Changed topic name"}),
            evidence="Evidence.",
            evidence_scope=EvidenceScope.ABSTRACT,
        )
    )
    analyzer.settings = analyzer.settings.model_copy(update={"llm_max_output_tokens": 256})
    service.analyze(context)
    mode = mode.model_copy(
        update={"name": "Changed mode name", "instruction": "Changed instruction"}
    )
    service.analyze(context)

    assert analyzer.calls == 4


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


def test_pipeline_persists_typed_analysis_for_restart_consumers(tmp_path):
    database = Database(tmp_path / "pipeline.db")
    search = FakeSearchService([_paper(canonical_id="paper:persisted")])
    analysis = FakeAnalysisService()
    pipeline = Pipeline(
        Settings(
            llm_api_key="",
            analyze_top_n=1,
            fulltext_top_n=0,
            _env_file=None,
        ),
        database,
        literature_search_service=search,
        paper_analysis_service=analysis,
    )

    pipeline.run(days=7, topics=[_topic()])

    assert database.list_papers(topic_id=_topic().id)[0]["analysis"]["status"] == "extractive"
    pipeline.close()
    database.connection.close()


def test_pipeline_close_closes_its_fulltext_client(tmp_path):
    database = Database(tmp_path / "pipeline.db")
    pipeline = Pipeline(
        Settings(llm_api_key="", analyze_top_n=0, _env_file=None),
        database,
        literature_search_service=FakeSearchService([]),
    )
    fulltext_client = pipeline.fulltext.client

    pipeline.close()

    assert fulltext_client.is_closed
    database.connection.close()


def test_pipeline_persists_first_discovered_paper_before_real_analysis_repository(
    tmp_path,
):
    database = Database(tmp_path / "pipeline.db")
    pipeline = Pipeline(
        Settings(
            llm_api_key="",
            analyze_top_n=1,
            fulltext_top_n=0,
            _env_file=None,
        ),
        database,
        literature_search_service=FakeSearchService([_paper(canonical_id="paper:first")]),
    )

    summary, returned = pipeline.run(days=7, topics=[_topic()])

    assert summary.errors == []
    assert summary.analyzed == 1
    assert returned[0].analysis["status"] == "extractive"
    persisted = database.list_papers(topic_id=_topic().id)[0]["analysis"]
    assert persisted["status"] == "extractive"
    assert AnalysisRepository(database).get(
        canonical_id="paper:first",
        analysis_version="v2.0",
        evidence_hash=returned[0].analysis["evidence_hash"],
        model_config_hash=returned[0].analysis["model_config_hash"],
    ).status.value == "extractive"
    pipeline.close()
    database.connection.close()


def test_pipeline_restores_topic_exclusions_and_domain_gate(tmp_path):
    database = Database(tmp_path / "pipeline.db")
    accepted = _paper(canonical_id="paper:accepted")
    accepted.title = "Underwater acoustic channel estimation"
    accepted.abstract = "A channel estimation method for a hydrophone array."
    excluded = _paper(canonical_id="paper:excluded")
    excluded.title = "Underwater acoustic channel estimation for medical ultrasound"
    excluded.abstract = "A channel estimation method."
    off_domain = _paper(canonical_id="paper:off-domain")
    off_domain.title = "mmWave channel estimation"
    off_domain.abstract = "A channel estimation method."
    topic = Topic(
        id="gated",
        name="Underwater acoustics",
        query="underwater acoustic channel estimation",
        include=["underwater acoustic", "channel estimation"],
        exclude=["medical ultrasound"],
        domain_anchors=["underwater acoustic", "hydrophone"],
        method_terms=["channel estimation"],
        require_domain_anchor=True,
        min_score=0.1,
    )
    pipeline = Pipeline(
        Settings(llm_api_key="", analyze_top_n=0, _env_file=None),
        database,
        literature_search_service=FakeSearchService([accepted, excluded, off_domain]),
    )

    _summary, returned = pipeline.run(days=7, topics=[topic])

    assert [paper.canonical_id for paper in returned] == ["paper:accepted"]
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
