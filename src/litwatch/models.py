from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Author(BaseModel):
    name: str


class Paper(BaseModel):
    canonical_id: str
    source_ids: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    title: str
    abstract: str = ""
    authors: list[Author] = Field(default_factory=list)
    publication_date: date | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    pdf_url: str = ""
    is_open_access: bool = False
    citation_count: int = 0
    topic_id: str = ""
    topic_name: str = ""
    score: float = 0.0
    score_detail: dict[str, float] = Field(default_factory=dict)
    analysis: dict[str, object] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: int
    started_at: str
    finished_at: str
    fetched: int
    deduplicated: int
    accepted: int
    analyzed: int
    errors: list[str] = Field(default_factory=list)
