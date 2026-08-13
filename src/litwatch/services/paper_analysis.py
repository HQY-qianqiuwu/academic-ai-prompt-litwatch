from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from litwatch.analysis import PaperAnalyzer
from litwatch.analysis_models import EvidenceScope, PaperAnalysis
from litwatch.analysis_repository import AnalysisRepository
from litwatch.config import Topic
from litwatch.db import Database
from litwatch.jobs import JobRecord
from litwatch.models import Paper

if TYPE_CHECKING:
    from litwatch.services.jobs import JobContext

AnalysisStep = Literal[
    "validate_paper",
    "prepare_analysis_input",
    "load_persisted_analysis",
    "analyze_with_gateway",
    "extractive_fallback",
    "skip_analysis",
    "validate_paper_analysis",
    "persist_paper_analysis",
]
StepStatus = Literal["completed", "skipped", "failed"]


@dataclass(frozen=True, slots=True)
class AnalysisTraceEntry:
    step: AnalysisStep
    status: StepStatus
    safe_error: str | None = None


@dataclass(slots=True)
class AnalysisContext:
    paper: Paper
    topic: Topic
    evidence: str
    evidence_scope: EvidenceScope
    trace: list[AnalysisTraceEntry] = field(default_factory=list)


class PaperAnalysisJobPayload(BaseModel):
    """Secret-free job input that references persisted provider-owned paper data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    canonical_id: str = Field(min_length=1, max_length=1_000)
    topic_id: str = Field(min_length=1, max_length=100)
    evidence_scope: EvidenceScope = Field(strict=False)
    evidence: str | None = Field(default=None, max_length=36_000)

    @field_validator("canonical_id", "topic_id", mode="before")
    @classmethod
    def strip_identifiers(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def evidence_matches_declared_scope(self) -> PaperAnalysisJobPayload:
        if self.evidence_scope is EvidenceScope.FULLTEXT:
            raise ValueError("complete full-text analysis is not supported")
        if (
            self.evidence_scope is EvidenceScope.FULLTEXT_EXCERPT
            and not (self.evidence or "").strip()
        ):
            raise ValueError("full-text evidence is required for the declared scope")
        if (
            self.evidence_scope is not EvidenceScope.FULLTEXT_EXCERPT
            and self.evidence is not None
        ):
            raise ValueError("evidence is only accepted for a full-text scope")
        return self


class AnalysisStore(Protocol):
    def get(
        self,
        *,
        canonical_id: str,
        analysis_version: str,
        evidence_hash: str,
        model_config_hash: str,
    ) -> PaperAnalysis | None: ...

    def upsert(self, analysis: PaperAnalysis) -> PaperAnalysis: ...


class PaperAnalysisService:
    ANALYSIS_VERSION = "v2.0"

    def __init__(
        self,
        *,
        analyzer: PaperAnalyzer,
        repository: AnalysisStore | AnalysisRepository,
    ) -> None:
        self.analyzer = analyzer
        self.repository = repository

    def analyze(
        self,
        context: AnalysisContext,
        *,
        should_abort: Callable[[], bool] = lambda: False,
    ) -> PaperAnalysis | None:
        try:
            self._validate_context(context)
        except ValueError:
            context.trace.append(
                AnalysisTraceEntry("validate_paper", "failed", safe_error="invalid_paper")
            )
            raise
        context.trace.append(AnalysisTraceEntry("validate_paper", "completed"))

        evidence = context.evidence.strip()
        evidence_hash = sha256(evidence.encode("utf-8")).hexdigest()
        model_config_hash = self._model_config_hash(context)
        context.trace.append(
            AnalysisTraceEntry("prepare_analysis_input", "completed")
        )

        identity = {
            "canonical_id": context.paper.canonical_id,
            "analysis_version": self.ANALYSIS_VERSION,
            "evidence_hash": evidence_hash,
            "model_config_hash": model_config_hash,
        }
        existing = self.repository.get(**identity)
        if existing is not None:
            context.trace.append(
                AnalysisTraceEntry("load_persisted_analysis", "completed")
            )
            return existing

        if should_abort():
            return None

        if not evidence:
            context.trace.append(AnalysisTraceEntry("skip_analysis", "skipped"))
            candidate = PaperAnalysis(
                **identity,
                status="skipped",
                evidence_scope=context.evidence_scope,
            )
        else:
            step: AnalysisStep = (
                "analyze_with_gateway" if self.analyzer.enabled else "extractive_fallback"
            )
            try:
                raw = self.analyzer.analyze(
                    context.paper,
                    context.topic,
                    evidence
                    if context.evidence_scope
                    in {EvidenceScope.FULLTEXT_EXCERPT, EvidenceScope.FULLTEXT}
                    else "",
                )
                candidate = self._from_analyzer_result(context, identity, raw)
            except Exception:  # noqa: BLE001 - persisted trace must remain redacted
                context.trace.append(
                    AnalysisTraceEntry(step, "failed", safe_error="analysis_failed")
                )
                candidate = PaperAnalysis(
                    **identity,
                    status="failed",
                    evidence_scope=context.evidence_scope,
                )
            else:
                context.trace.append(AnalysisTraceEntry(step, "completed"))

        if should_abort():
            return None

        validated = PaperAnalysis.model_validate(candidate)
        context.trace.append(
            AnalysisTraceEntry("validate_paper_analysis", "completed")
        )
        if should_abort():
            return None
        try:
            stored = self.repository.upsert(validated)
        except Exception:
            context.trace.append(
                AnalysisTraceEntry(
                    "persist_paper_analysis", "failed", safe_error="persistence_failed"
                )
            )
            raise
        context.trace.append(
            AnalysisTraceEntry("persist_paper_analysis", "completed")
        )
        return stored

    @staticmethod
    def _validate_context(context: AnalysisContext) -> None:
        if not context.paper.canonical_id.strip():
            raise ValueError("paper canonical_id must not be blank")
        if not context.paper.title.strip():
            raise ValueError("paper title must not be blank")

    def _model_config_hash(self, context: AnalysisContext) -> str:
        settings = self.analyzer.settings
        modes = {mode.id: mode for mode in settings.load_analysis_modes()}
        mode = modes.get(context.topic.analysis_mode) or modes["quick_scan"]
        document = {
            "analysis_version": self.ANALYSIS_VERSION,
            "analysis_mode": {
                "id": mode.id,
                "name": mode.name,
                "instruction": mode.instruction,
            },
            "evidence_scope": context.evidence_scope.value,
            "llm_enabled": self.analyzer.enabled,
            "llm_model": settings.llm_model if self.analyzer.enabled else None,
            "llm_max_output_tokens": settings.llm_max_output_tokens,
            "provider_kind": (
                self.analyzer.gateway.provider_kind
                if self.analyzer.enabled and self.analyzer.gateway is not None
                else "extractive"
            ),
            "topic_id": context.topic.id,
            "topic_name": context.topic.name,
            "topic_query": context.topic.query,
            "topic_include": list(context.topic.include),
        }
        serialized = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _from_analyzer_result(
        context: AnalysisContext,
        identity: dict[str, str],
        raw: dict[str, object],
    ) -> PaperAnalysis:
        raw_status = raw.get("status")
        status = {
            "ok": "completed",
            "completed": "completed",
            "extractive": "extractive",
            "skipped": "skipped",
            "error": "failed",
            "failed": "failed",
        }.get(raw_status, "failed")

        def scalar(name: str) -> str | None:
            value = raw.get(name)
            return value if isinstance(value, str) and value.strip() else None

        def items(name: str, *, legacy_name: str | None = None) -> list[str]:
            value = raw.get(name)
            if value is None and legacy_name is not None:
                value = raw.get(legacy_name)
            return value if isinstance(value, list) else []

        return PaperAnalysis.model_validate(
            {
                **identity,
                "status": status,
                "evidence_scope": context.evidence_scope,
                "research_question": scalar("research_question"),
                "motivation": scalar("motivation"),
                "methods": items("methods"),
                "key_modules": items("key_modules"),
                "baselines": items("baselines"),
                "datasets": items("datasets"),
                "experimental_setup": items("experimental_setup"),
                "metrics": items("metrics"),
                "main_results": items("main_results", legacy_name="results"),
                "contributions": items("contributions"),
                "limitations": items("limitations"),
                "future_work": items("future_work"),
                "evidence": raw.get("evidence", []),
            }
        )


@dataclass(slots=True)
class PaperAnalysisJobHandler:
    """Execute a typed analysis from immutable persisted paper metadata."""

    database: Database
    topics: Callable[[], list[Topic]]
    service: PaperAnalysisService

    def __call__(self, context: JobContext, record: JobRecord) -> str | None:
        payload = PaperAnalysisJobPayload.model_validate(record.payload)
        if context.cancelled():
            return None
        paper = self._load_paper(payload.canonical_id, payload.topic_id)
        topic = self._load_topic(payload.topic_id)
        evidence = (
            payload.evidence or ""
            if payload.evidence_scope
            in {EvidenceScope.FULLTEXT_EXCERPT, EvidenceScope.FULLTEXT}
            else paper.abstract
            if payload.evidence_scope is EvidenceScope.ABSTRACT
            else ""
        )
        actual_scope = (
            payload.evidence_scope
            if evidence.strip() or payload.evidence_scope is EvidenceScope.METADATA_ONLY
            else EvidenceScope.METADATA_ONLY
        )
        should_abort = lambda: context.cancelled() or context.remaining_seconds() <= 0
        analysis = self.service.analyze(
            AnalysisContext(
                paper=paper,
                topic=topic,
                evidence=evidence,
                evidence_scope=actual_scope,
            ),
            should_abort=should_abort,
        )
        if analysis is None or should_abort():
            return None
        return self.result_reference(analysis)

    def _load_topic(self, topic_id: str) -> Topic:
        for topic in self.topics():
            if topic.id == topic_id:
                return topic
        raise ValueError("analysis topic is not configured")

    def _load_paper(self, canonical_id: str, topic_id: str) -> Paper:
        with self.database.transaction_lock:
            row = self.database.connection.execute(
                """SELECT p.*, pt.topic_id, pt.topic_name, pt.score,
                          pt.score_detail_json, pt.analysis_json
                   FROM papers AS p JOIN paper_topics AS pt USING(canonical_id)
                   WHERE p.canonical_id=? AND pt.topic_id=?""",
                (canonical_id, topic_id),
            ).fetchone()
        if row is None:
            raise ValueError("canonical paper is not available for the selected topic")
        return Paper.model_validate(
            {
                "canonical_id": row["canonical_id"],
                "source_ids": json.loads(row["source_ids_json"]),
                "sources": json.loads(row["sources_json"]),
                "title": row["title"],
                "abstract": row["abstract"],
                "authors": json.loads(row["authors_json"]),
                "publication_date": row["publication_date"],
                "venue": row["venue"],
                "doi": row["doi"],
                "url": row["url"],
                "pdf_url": row["pdf_url"],
                "is_open_access": bool(row["is_open_access"]),
                "citation_count": row["citation_count"],
                "topic_id": row["topic_id"],
                "topic_name": row["topic_name"],
                "score": row["score"],
                "score_detail": json.loads(row["score_detail_json"]),
                "analysis": json.loads(row["analysis_json"]),
            }
        )

    @staticmethod
    def result_reference(analysis: PaperAnalysis) -> str:
        return (
            f"paper_analysis:{analysis.canonical_id}:{analysis.analysis_version}:"
            f"{analysis.evidence_hash}:{analysis.model_config_hash}"
        )
