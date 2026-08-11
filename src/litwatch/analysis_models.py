from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EvidenceScope(StrEnum):
    METADATA_ONLY = "metadata_only"
    ABSTRACT = "abstract"
    FULLTEXT_EXCERPT = "fulltext_excerpt"
    FULLTEXT = "fulltext"


class AnalysisStatus(StrEnum):
    COMPLETED = "completed"
    EXTRACTIVE = "extractive"
    SKIPPED = "skipped"
    FAILED = "failed"


class AnalysisEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: str = Field(min_length=1, max_length=100)
    excerpt: str = Field(min_length=1, max_length=2_000)
    evidence_scope: EvidenceScope = Field(strict=False)
    section: str | None = Field(default=None, min_length=1, max_length=200)
    page: int | None = Field(default=None, ge=1)


class PaperAnalysis(BaseModel):
    """Provider-independent analysis facts; canonical paper metadata is excluded."""

    model_config = ConfigDict(extra="forbid", strict=True)

    canonical_id: str = Field(min_length=1, max_length=1_000)
    analysis_version: str = Field(min_length=1, max_length=100)
    evidence_hash: str = Field(min_length=1, max_length=256)
    model_config_hash: str = Field(min_length=1, max_length=256)
    status: AnalysisStatus = Field(strict=False)
    evidence_scope: EvidenceScope = Field(strict=False)
    research_question: str | None = None
    motivation: str | None = None
    methods: list[str] = Field(default_factory=list)
    key_modules: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    experimental_setup: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    main_results: list[str] = Field(default_factory=list)
    contributions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    future_work: list[str] = Field(default_factory=list)
    evidence: list[AnalysisEvidence] = Field(default_factory=list)
