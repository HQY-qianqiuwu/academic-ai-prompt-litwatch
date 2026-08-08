"""HTTP API schemas for LitWatch literature search."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from litwatch.models import Paper
from litwatch.services import LiteratureSearchResult


class LiteratureSearchRequest(BaseModel):
    """Validated input for the unified literature search endpoint."""

    topic: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("topic", mode="before")
    @classmethod
    def strip_topic(cls, value: object) -> object:
        """Normalize surrounding whitespace before length validation."""
        if isinstance(value, str):
            return value.strip()
        return value


class LiteraturePaperResponse(BaseModel):
    """Stable public projection of provider-backed paper metadata."""

    canonical_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    url: str | None
    abstract: str | None
    sources: list[str]

    @classmethod
    def from_paper(cls, paper: Paper) -> LiteraturePaperResponse:
        """Project a validated Paper without inventing missing metadata."""
        return cls(
            canonical_id=paper.canonical_id,
            title=paper.title,
            authors=[author.name for author in paper.authors],
            year=paper.publication_date.year if paper.publication_date else None,
            venue=paper.venue or None,
            doi=paper.doi or None,
            url=paper.url or None,
            abstract=paper.abstract or None,
            sources=list(paper.sources),
        )


class LiteratureSearchResponse(BaseModel):
    """Response envelope for a unified literature search."""

    query: str
    paper_count: int
    papers: list[LiteraturePaperResponse]

    @classmethod
    def from_result(cls, result: LiteratureSearchResult) -> LiteratureSearchResponse:
        """Serialize the service result through the explicit API contract."""
        return cls(
            query=result.query,
            paper_count=result.paper_count,
            papers=[LiteraturePaperResponse.from_paper(paper) for paper in result.papers],
        )
