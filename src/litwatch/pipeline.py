from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from litwatch.analysis import PaperAnalyzer
from litwatch.analysis_models import AnalysisStatus, EvidenceScope
from litwatch.analysis_repository import AnalysisRepository
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.fulltext import FullTextExtractor
from litwatch.llm.factory import LLMRuntime, build_llm_runtime
from litwatch.models import Paper, RunSummary
from litwatch.ranking import score_paper
from litwatch.services.literature_search import (
    AllProvidersFailedError,
    LiteratureSearchService,
)
from litwatch.services.paper_analysis import AnalysisContext, PaperAnalysisService


def merge_papers(existing: Paper, incoming: Paper) -> Paper:
    """Preserve the legacy merge helper while retrieval owns deduplication."""
    existing.sources = sorted(set(existing.sources + incoming.sources))
    existing.source_ids.update(incoming.source_ids)
    if len(incoming.abstract) > len(existing.abstract):
        existing.abstract = incoming.abstract
    if not existing.authors and incoming.authors:
        existing.authors = incoming.authors
    if not existing.publication_date or (
        incoming.publication_date and incoming.publication_date < existing.publication_date
    ):
        existing.publication_date = incoming.publication_date
    for field in ("venue", "doi", "url", "pdf_url"):
        if not getattr(existing, field) and getattr(incoming, field):
            setattr(existing, field, getattr(incoming, field))
    existing.is_open_access = existing.is_open_access or incoming.is_open_access
    existing.citation_count = max(existing.citation_count, incoming.citation_count)
    return existing


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        database: Database | None = None,
        *,
        llm_http_client: httpx.Client | None = None,
        literature_search_service: LiteratureSearchService | None = None,
        paper_analysis_service: PaperAnalysisService | None = None,
    ) -> None:
        self.settings = settings
        self.database = database or Database(settings.database_path)
        timeout = settings.request_timeout_seconds
        self.literature_search_service = (
            literature_search_service or LiteratureSearchService.from_settings(settings)
        )
        self._llm_runtime: LLMRuntime | None = build_llm_runtime(
            settings,
            database=self.database,
            client=llm_http_client,
        )
        self.analyzer = PaperAnalyzer(
            settings,
            gateway=(self._llm_runtime.gateway if self._llm_runtime else None),
            budget_factory=(
                self._llm_runtime.budget_factory if self._llm_runtime else None
            ),
        )
        self.paper_analysis_service = paper_analysis_service or PaperAnalysisService(
            analyzer=self.analyzer,
            repository=AnalysisRepository(self.database),
        )
        self.fulltext = FullTextExtractor(timeout=max(45, timeout))

    def close(self) -> None:
        if self._llm_runtime is not None:
            self._llm_runtime.close()

    def run(
        self, *, days: int | None = None, topics: list[Topic] | None = None
    ) -> tuple[RunSummary, list[Paper]]:
        run_id = self.database.start_run()
        started = datetime.now(UTC)
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=days or self.settings.lookback_days)
        fetched = 0
        deduplicated = 0
        analyzed = 0
        errors: list[str] = []
        accepted_papers: list[Paper] = []

        for topic in topics if topics is not None else self.settings.load_topics():
            try:
                search_result = self.literature_search_service.search(
                    topic=topic.query,
                    limit=self.settings.max_results_per_source,
                    start_date=start_date,
                    end_date=end_date,
                )
            except AllProvidersFailedError as error:
                errors.append(
                    f"{topic.id}/search: all_providers_failed:"
                    f"{','.join(item.status.value for item in error.provider_status)}"
                )
                continue
            except Exception:  # noqa: BLE001 - runtime summary stays redacted
                errors.append(f"{topic.id}/search: search_failed")
                continue

            fetched += search_result.diagnostics.raw_count
            deduplicated += search_result.diagnostics.dedup_count
            ranked = self._rank_topic(search_result.papers, topic)
            for paper in ranked:
                self.database.upsert(paper, run_id)

            for index, paper in enumerate(ranked[: self.settings.analyze_top_n]):
                fulltext = ""
                if self.analyzer.enabled and index < self.settings.fulltext_top_n and paper.pdf_url:
                    try:
                        fulltext = self.fulltext.extract(paper.pdf_url)
                    except Exception:  # noqa: BLE001 - summary remains redacted
                        errors.append(f"{topic.id}/pdf/{paper.canonical_id}: extraction_failed")
                evidence = fulltext or paper.abstract
                evidence_scope = (
                    EvidenceScope.FULLTEXT_EXCERPT
                    if fulltext
                    else (
                        EvidenceScope.ABSTRACT
                        if paper.abstract
                        else EvidenceScope.METADATA_ONLY
                    )
                )
                try:
                    analysis = self.paper_analysis_service.analyze(
                        AnalysisContext(
                            paper=paper,
                            topic=topic,
                            evidence=evidence,
                            evidence_scope=evidence_scope,
                        )
                    )
                    paper.analysis = analysis.model_dump(mode="json")
                    analyzed += int(
                        analysis.status
                        in {AnalysisStatus.COMPLETED, AnalysisStatus.EXTRACTIVE}
                    )
                    if analysis.status is AnalysisStatus.FAILED:
                        errors.append(
                            f"{topic.id}/analysis/{paper.canonical_id}: analysis_failed"
                        )
                except Exception:  # noqa: BLE001 - summary remains redacted
                    paper.analysis = {"status": "failed"}
                    errors.append(
                        f"{topic.id}/analysis/{paper.canonical_id}: analysis_failed"
                    )
            for paper in ranked:
                self.database.upsert(paper, run_id)
            accepted_papers.extend(ranked)

        finished = datetime.now(UTC)
        self.database.finish_run(
            run_id,
            fetched=fetched,
            deduplicated=deduplicated,
            accepted=len(accepted_papers),
            analyzed=analyzed,
            errors=errors,
        )
        summary = RunSummary(
            run_id=run_id,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            fetched=fetched,
            deduplicated=deduplicated,
            accepted=len(accepted_papers),
            analyzed=analyzed,
            errors=errors,
        )
        return summary, sorted(accepted_papers, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _rank_topic(papers: list[Paper], topic: Topic) -> list[Paper]:
        ranked: list[Paper] = []
        for paper in papers:
            paper.topic_id = topic.id
            paper.topic_name = topic.name
            score_paper(paper, topic)
            if paper.score >= topic.min_score:
                ranked.append(paper)
        return sorted(ranked, key=lambda item: (item.score, item.citation_count), reverse=True)
