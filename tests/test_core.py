from datetime import date

from litwatch.analysis import PaperAnalyzer
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.export import rows_to_bibtex
from litwatch.models import Paper
from litwatch.pipeline import merge_papers
from litwatch.ranking import score_paper
from litwatch.text import abstract_from_inverted_index, canonical_id


def topic() -> Topic:
    return Topic(
        id="underwater",
        name="水声通信",
        query="underwater acoustic communication",
        include=["underwater acoustic", "channel estimation"],
        exclude=["medical ultrasound"],
    )


def test_canonical_id_prefers_doi_and_removes_arxiv_version():
    assert canonical_id(doi="10.1234/ABC", title="Anything") == "doi:10.1234/abc"
    assert canonical_id(arxiv_id="2401.12345v3", title="Anything") == "arxiv:2401.12345"


def test_openalex_abstract_reconstruction():
    assert abstract_from_inverted_index({"world": [1], "Hello": [0]}) == "Hello world"


def test_ranking_is_explainable_and_exclusions_win():
    paper = Paper(
        canonical_id="x",
        title="Underwater acoustic channel estimation",
        abstract="A new method for underwater acoustic communication.",
        publication_date=date(2026, 7, 31),
        is_open_access=True,
    )
    ranked = score_paper(paper, topic(), today=date(2026, 7, 31))
    assert ranked.score > 0.5
    assert ranked.score_detail["relevance"] > 0

    paper.abstract += " Evaluated for medical ultrasound."
    excluded = score_paper(paper, topic(), today=date(2026, 7, 31))
    assert excluded.score == 0
    assert excluded.score_detail == {"excluded": 1.0}


def test_keyword_ranking_is_not_penalized_when_semantic_model_is_unavailable(monkeypatch):
    monkeypatch.setattr("litwatch.ranking._semantic_relevance", lambda text, terms: None)
    paper = Paper(
        canonical_id="x",
        title="Underwater acoustic channel estimation",
        abstract="A method for underwater acoustic channel estimation.",
        publication_date=date(2026, 7, 31),
    )

    ranked = score_paper(paper, topic(), today=date(2026, 7, 31))

    assert ranked.score_detail["relevance"] == 1.0


def test_merge_keeps_richer_metadata():
    first = Paper(canonical_id="x", title="A", sources=["arxiv"], abstract="short")
    second = Paper(
        canonical_id="x",
        title="A",
        sources=["openalex"],
        abstract="a much longer abstract",
        doi="10/x",
    )
    merged = merge_papers(first, second)
    assert merged.sources == ["arxiv", "openalex"]
    assert merged.abstract == "a much longer abstract"
    assert merged.doi == "10/x"


def test_database_round_trip(tmp_path):
    database = Database(tmp_path / "litwatch.db")
    run_id = database.start_run()
    paper = Paper(
        canonical_id="doi:10/x", title="Paper", topic_id="t", topic_name="Topic", score=0.75
    )
    database.upsert(paper, run_id)
    database.finish_run(run_id, fetched=1, deduplicated=1, accepted=1, analyzed=0, errors=[])
    rows = database.list_papers()
    assert rows[0]["title"] == "Paper"
    assert rows[0]["score"] == 0.75
    assert database.latest_run()["accepted"] == 1
    assert database.list_topics() == [{"id": "t", "name": "Topic"}]


def test_bibtex_export_uses_verified_metadata():
    rendered = rows_to_bibtex(
        [
            {
                "title": "Underwater {Acoustics}",
                "authors": [{"name": "Ada Lovelace"}],
                "publication_date": "2026-07-31",
                "venue": "Ocean Engineering",
                "doi": "10.1234/example",
                "url": "https://doi.org/10.1234/example",
                "abstract": "A verified abstract.",
            }
        ]
    )
    assert "@article{Lovelace2026" in rendered
    assert "doi = {10.1234/example}" in rendered
    assert "Underwater \\{Acoustics\\}" in rendered


def test_analyzer_has_no_key_extractive_fallback():
    analyzer = PaperAnalyzer(Settings(llm_api_key=""))
    paper = Paper(
        canonical_id="x",
        title="Underwater acoustic detection",
        abstract=(
            "Underwater target detection remains challenging. "
            "We propose a sonar detection framework. Results show improved accuracy."
        ),
        score=0.8,
    )
    result = analyzer.analyze(paper, topic())
    assert result["status"] == "extractive"
    assert result["methods"] == ["We propose a sonar detection framework."]
    assert result["reading_priority"] == 4
