import fitz

from litwatch.email_digest import render_html, render_pdf

DIGEST = {
    "subscription": {"id": "sub-a", "name": "TDOA Weekly", "topic": "underwater acoustic TDOA"},
    "period": "2026-W33",
    "run": {"status": "success", "raw_count": 30, "new_count": 2, "recommended_count": 1},
    "papers": [
        {
            "canonical_id": "doi:10.1000/tdoa",
            "title": "Underwater Acoustic TDOA Paper",
            "authors": ["Alice"],
            "year": 2026,
            "venue": "JASA",
            "abstract": "Provider-backed abstract.",
            "title_zh": "水下声学 TDOA 论文",
            "abstract_zh": "基于文献来源的摘要。",
            "methods_zh": ["采用到达时间差定位方法。"],
            "recommendation_reason_zh": "主题高度相关，且摘要与来源信息完整。",
            "sources": ["openalex"],
            "doi": "10.1000/tdoa",
            "url": "https://example.org/tdoa",
            "rank_position": 1,
            "rank_score": 0.9,
            "relevance_score": 0.8,
            "quality_score": 0.7,
        }
    ],
}


def test_render_html_contains_paper_fields():
    html = render_html(DIGEST)
    assert "Underwater Acoustic TDOA Paper" in html
    assert "10.1000/tdoa" in html
    assert "0.90" in html
    assert "水下声学 TDOA 论文" in html
    assert "中文摘要" in html
    assert "主要方法" in html
    assert "采用到达时间差定位方法。" in html
    assert "推荐理由" in html
    assert "主题高度相关，且摘要与来源信息完整。" in html


def test_render_pdf_is_valid_pdf_with_text():
    payload = render_pdf(DIGEST)
    assert payload.startswith(b"%PDF")
    document = fitz.open(stream=payload, filetype="pdf")
    text = "".join(page.get_text() for page in document)
    assert "Underwater Acoustic TDOA Paper" in text
    assert "10.1000/tdoa" in text
    assert "水下声学" in text
    assert "主要方法" in text
    assert "推荐理由" in text


def test_render_pdf_handles_empty_papers():
    empty = {**DIGEST, "papers": []}
    payload = render_pdf(empty)
    assert payload.startswith(b"%PDF")
