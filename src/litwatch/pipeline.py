from __future__ import annotations

from datetime import UTC, datetime, timedelta

from litwatch.analysis import PaperAnalyzer
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.fulltext import FullTextExtractor
from litwatch.models import Paper, RunSummary
from litwatch.ranking import score_paper
from litwatch.sources import ArxivSource, OpenAlexSource, SemanticScholarSource


def merge_papers(existing: Paper, incoming: Paper) -> Paper:
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
    def __init__(self, settings: Settings, database: Database | None = None) -> None:
        self.settings = settings
        self.database = database or Database(settings.database_path)
        timeout = settings.request_timeout_seconds
        self.sources = [
            OpenAlexSource(email=settings.openalex_email, timeout=timeout),
            ArxivSource(timeout=timeout),
        ]
        if settings.semantic_scholar_api_key or settings.semantic_scholar_anonymous:
            self.sources.append(
                SemanticScholarSource(
                    api_key=settings.semantic_scholar_api_key,
                    timeout=timeout,
                )
            )
        self.analyzer = PaperAnalyzer(settings)
        self.fulltext = FullTextExtractor(timeout=max(45, timeout))

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
            unique: dict[str, Paper] = {}
            for source in self.sources:
                try:
                    papers = source.search(
                        topic, start_date, end_date, self.settings.max_results_per_source
                    )
                    fetched += len(papers)
                    for paper in papers:
                        if paper.canonical_id in unique:
                            unique[paper.canonical_id] = merge_papers(
                                unique[paper.canonical_id], paper
                            )
                        else:
                            unique[paper.canonical_id] = paper
                except Exception as exc:  # noqa: BLE001 - one failed source must not stop a scan
                    errors.append(f"{topic.id}/{source.name}: {type(exc).__name__}: {exc}")

            deduplicated += len(unique)
            ranked = self._rank_topic(unique.values(), topic)
            for index, paper in enumerate(ranked[: self.settings.analyze_top_n]):
                existing = self.database.paper_analysis(paper.canonical_id, topic.id)
                if existing and existing.get("status") in {"ok", "extractive"} and existing.get("evidence_level") == "fulltext_excerpt":
                    paper.analysis = existing
                    analyzed += 1
                    continue
                fulltext = ""
                if self.analyzer.enabled and index < self.settings.fulltext_top_n and paper.pdf_url:
                    try:
                        fulltext = self.fulltext.extract(paper.pdf_url)
                    except Exception as exc:  # noqa: BLE001 - PDF extraction is optional
                        errors.append(
                            f"{topic.id}/pdf/{paper.canonical_id}: {type(exc).__name__}: {exc}"
                        )
                try:
                    paper.analysis = self.analyzer.analyze(paper, topic, fulltext)
                    analyzed += int(paper.analysis.get("status") in {"ok", "extractive"})
                except Exception as exc:  # noqa: BLE001 - LLM analysis is optional
                    paper.analysis = {"status": "error", "reason": str(exc)}
                    errors.append(
                        f"{topic.id}/llm/{paper.canonical_id}: {type(exc).__name__}: {exc}"
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
    def _rank_topic(papers, topic: Topic) -> list[Paper]:
        ranked: list[Paper] = []
        for paper in papers:
            paper.topic_id = topic.id
            paper.topic_name = topic.name
            score_paper(paper, topic)
            if paper.score >= topic.min_score:
                ranked.append(paper)
        return sorted(ranked, key=lambda item: (item.score, item.citation_count), reverse=True)
