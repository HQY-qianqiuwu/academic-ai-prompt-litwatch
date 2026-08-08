from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from litwatch.config import Topic
from litwatch.models import Paper
from litwatch.services import LiteratureSearchService
from litwatch.services import literature_search as literature_search_module


class FakeSource:
    name = "fake"

    def __init__(self, papers: list[Paper] | None = None, error: Exception | None = None) -> None:
        self.papers = papers or []
        self.error = error
        self.calls: list[tuple[Topic, date, date, int]] = []

    def search(
        self,
        topic: Topic,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[Paper]:
        self.calls.append((topic, start_date, end_date, limit))
        if self.error is not None:
            raise self.error
        return self.papers


def paper(canonical_id: str) -> Paper:
    return Paper(
        canonical_id=canonical_id,
        title=f"Paper {canonical_id}",
        sources=["openalex"],
    )


def test_search_normalizes_topic_passes_limit_and_returns_papers():
    source = FakeSource([paper("one"), paper("two")])
    service = LiteratureSearchService(source, current_date=lambda: date(2026, 8, 8))

    result = service.search(topic="  underwater acoustic TDOA localization  ", limit=1)

    provider_topic, start_date, end_date, provider_limit = source.calls[0]
    assert provider_topic.query == "underwater acoustic TDOA localization"
    assert provider_topic.name == "underwater acoustic TDOA localization"
    assert start_date == date(1900, 1, 1)
    assert end_date == date(2026, 8, 8)
    assert provider_limit == 1
    assert result.query == "underwater acoustic TDOA localization"
    assert result.paper_count == len(result.papers) == 1
    assert all(isinstance(item, Paper) for item in result.papers)
    assert result.model_dump()["paper_count"] == 1


def test_search_supports_an_injected_historical_start_date():
    source = FakeSource([paper("one")])
    service = LiteratureSearchService(
        source,
        historical_start_date=date(1950, 1, 1),
        current_date=lambda: date(2026, 8, 8),
    )

    service.search(topic="underwater acoustics", limit=10)

    _, start_date, end_date, _ = source.calls[0]
    assert start_date == date(1950, 1, 1)
    assert end_date == date(2026, 8, 8)


def test_search_propagates_provider_exceptions():
    error = RuntimeError("upstream unavailable")
    service = LiteratureSearchService(FakeSource(error=error))

    with pytest.raises(RuntimeError, match="upstream unavailable") as raised:
        service.search(topic="underwater acoustics", limit=10)

    assert raised.value is error


@pytest.mark.parametrize(
    ("topic", "limit", "message"),
    [
        ("   ", 10, "topic must not be blank"),
        ("underwater acoustics", 0, "limit must be a positive integer"),
        ("underwater acoustics", -1, "limit must be a positive integer"),
    ],
)
def test_search_rejects_invalid_service_inputs(topic: str, limit: int, message: str):
    source = FakeSource()
    service = LiteratureSearchService(source)

    with pytest.raises(ValueError, match=message):
        service.search(topic=topic, limit=limit)

    assert source.calls == []


def test_service_has_no_forbidden_framework_or_pipeline_imports():
    module_path = Path(literature_search_module.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    forbidden = {
        "fastapi",
        "litwatch.analysis",
        "litwatch.db",
        "litwatch.pipeline",
        "litwatch.ranking",
        "litwatch.zotero",
    }
    assert imports.isdisjoint(forbidden)
