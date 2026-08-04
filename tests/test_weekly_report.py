from datetime import date

from litwatch.config import Topic
from litwatch.weekly_report import apply_current_topic_rules, build_weekly_report, enrich_papers


def test_weekly_report_aggregates_topics_analysis_and_open_access():
    papers = [
        {
            "canonical_id": "synthetic:1",
            "title": "Underwater acoustic channel estimation with sparse recovery",
            "abstract": "We propose a sparse channel estimator. Results show improved accuracy.",
            "publication_date": date(2026, 8, 1).isoformat(),
            "topic_id": "underwater_acoustics",
            "topic_name": "水声通信",
            "score": 0.88,
            "citation_count": 3,
            "is_open_access": 1,
            "sources": ["openalex", "arxiv"],
            "url": "https://example.test/synthetic-1",
            "analysis": {
                "status": "extractive",
                "one_liner": "提出稀疏水声信道估计方法。",
                "relevance": "聚焦水声信道估计与稀疏恢复。",
                "methods": ["Sparse recovery"],
                "results": ["Improved accuracy"],
                "paper_type": "method",
            },
        },
        {
            "canonical_id": "synthetic:2",
            "title": "Hydrophone array processing in shallow water",
            "abstract": "A field experiment evaluates a hydrophone array.",
            "publication_date": date(2026, 7, 30).isoformat(),
            "topic_id": "underwater_acoustics",
            "topic_name": "水声通信",
            "score": 0.72,
            "citation_count": 0,
            "is_open_access": 0,
            "sources": ["openalex"],
            "url": "https://example.test/synthetic-2",
            "analysis": {},
        },
    ]
    topic = Topic(
        id="underwater_acoustics",
        name="水声通信",
        query="underwater acoustic communication",
        include=["underwater acoustic", "hydrophone", "channel estimation"],
    )

    report = build_weekly_report(
        papers,
        [topic],
        {"id": 7, "finished_at": "2026-08-03T00:00:00+00:00"},
    )

    assert report["period_label"] == "2026-08-03 自动周报"
    assert report["paper_count"] == 2
    assert report["analyzed_count"] == 1
    assert report["analysis_rate"] == 50
    assert report["open_access_rate"] == 50
    assert report["topics"][0]["focus_terms"] == [
        "underwater acoustic",
        "hydrophone",
        "channel estimation",
    ]
    assert report["topics"][0]["highlights"][0]["core_summary"].startswith("提出稀疏")


def test_enrich_papers_adds_safe_fallback_theme_and_core_summary():
    [paper] = enrich_papers(
        [
            {
                "title": "A synthetic sonar study",
                "abstract": "The first verified sentence. The second sentence.",
                "topic_name": "水声通信",
                "analysis": {},
            }
        ]
    )

    assert paper["core_summary"] == "The first verified sentence."
    assert "水声通信" in paper["theme_statement"]
    assert paper["paper_type_label"] == "待人工判断"


def test_current_topic_rules_hide_legacy_false_positives_without_deleting_rows():
    topic = Topic(
        id="underwater_acoustics",
        name="水声通信",
        query="underwater acoustic channel estimation",
        include=["underwater acoustic", "channel estimation"],
        domain_anchors={"any": ["underwater acoustic", "sonar"]},
        method_terms={"any": ["channel estimation"]},
        require_domain_anchor=True,
        min_score=0.3,
    )
    rows = [
        {
            "canonical_id": "synthetic:accepted",
            "title": "Underwater acoustic channel estimation",
            "abstract": "A sonar communication experiment.",
            "topic_id": topic.id,
            "topic_name": topic.name,
            "score": 0.4,
            "analysis": {},
        },
        {
            "canonical_id": "synthetic:rejected",
            "title": "Satellite channel estimation",
            "abstract": "A LEO wireless link.",
            "topic_id": topic.id,
            "topic_name": topic.name,
            "score": 0.7,
            "analysis": {},
        },
    ]

    visible = apply_current_topic_rules(rows, [topic])

    assert [row["canonical_id"] for row in visible] == ["synthetic:accepted"]
    assert len(rows) == 2
