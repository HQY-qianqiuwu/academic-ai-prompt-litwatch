from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from litwatch.config import Topic
from litwatch.models import Paper
from litwatch.ranking import score_paper

PAPER_TYPE_LABELS = {
    "theory": "理论研究",
    "method": "方法研究",
    "experiment": "实验验证",
    "application": "应用系统",
    "review": "综述论文",
    "unknown": "待人工判断",
}

STOP_WORDS = {
    "about",
    "across",
    "approach",
    "based",
    "deep",
    "from",
    "into",
    "method",
    "model",
    "paper",
    "study",
    "system",
    "that",
    "their",
    "this",
    "using",
    "with",
}


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _first_sentence(value: str, limit: int = 360) -> str:
    compact = " ".join(value.split())
    if not compact:
        return ""
    sentence = re.split(r"(?<=[。！？.!?])\s+", compact, maxsplit=1)[0]
    return sentence[:limit] + ("…" if len(sentence) > limit else "")


def enrich_papers(papers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add display-only summaries without altering persisted source metadata."""
    enriched: list[dict[str, Any]] = []
    for original in papers:
        paper = dict(original)
        analysis = paper.get("analysis") if isinstance(paper.get("analysis"), dict) else {}
        core_summary = str(analysis.get("one_liner") or "").strip()
        if not core_summary:
            core_summary = _first_sentence(str(paper.get("abstract") or "")) or "暂无可提炼摘要"
        theme_statement = str(analysis.get("relevance") or "").strip()
        if not theme_statement:
            topic_name = str(paper.get("topic_name") or "当前研究主题")
            theme_statement = f"本文归入“{topic_name}”，主要讨论 {paper.get('title', '该研究')}。"
        paper.update(
            core_summary=core_summary,
            theme_statement=theme_statement,
            method_highlights=_as_list(analysis.get("methods")),
            result_highlights=_as_list(analysis.get("results")),
            paper_type_label=PAPER_TYPE_LABELS.get(
                str(analysis.get("paper_type") or "unknown"), "待人工判断"
            ),
        )
        enriched.append(paper)
    return enriched


def apply_current_topic_rules(
    papers: Iterable[dict[str, Any]], topics: Iterable[Topic]
) -> list[dict[str, Any]]:
    """Re-evaluate stored rows so legacy false positives stay archived but are not displayed."""
    configured = {topic.id: topic for topic in topics}
    accepted: list[dict[str, Any]] = []
    for original in papers:
        row = dict(original)
        topic = configured.get(str(row.get("topic_id") or ""))
        if topic is None:
            accepted.append(row)
            continue
        paper = Paper.model_validate(row)
        score_paper(paper, topic)
        if paper.score < topic.min_score:
            continue
        row["score"] = paper.score
        row["score_detail"] = paper.score_detail
        accepted.append(row)
    return accepted


def _topic_record(topic: Topic | dict[str, Any]) -> dict[str, Any]:
    if isinstance(topic, Topic):
        return {
            "id": topic.id,
            "name": topic.name,
            "include": topic.method_terms or topic.include,
        }
    return {
        "id": str(topic.get("id") or ""),
        "name": str(topic.get("name") or topic.get("id") or "未命名主题"),
        "include": list(topic.get("include") or []),
    }


def _fallback_keywords(papers: list[dict[str, Any]], limit: int = 5) -> list[str]:
    words: Counter[str] = Counter()
    for paper in papers:
        title = str(paper.get("title") or "").casefold()
        words.update(
            token
            for token in re.findall(r"[a-z][a-z0-9-]{3,}", title)
            if token not in STOP_WORDS
        )
    return [word for word, _ in words.most_common(limit)]


def _focus_terms(
    papers: list[dict[str, Any]], configured_terms: list[str], limit: int = 5
) -> list[str]:
    matches: Counter[str] = Counter()
    for term in configured_terms:
        normalized = term.casefold().strip()
        if not normalized:
            continue
        count = sum(
            normalized in f"{paper.get('title', '')} {paper.get('abstract', '')}".casefold()
            for paper in papers
        )
        if count:
            matches[term] = count
    return [term for term, _ in matches.most_common(limit)] or _fallback_keywords(papers, limit)


def build_weekly_report(
    papers: Iterable[dict[str, Any]],
    topics: Iterable[Topic | dict[str, Any]],
    latest_run: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a deterministic weekly brief from verified paper rows and analyses."""
    rows = enrich_papers(papers)
    topic_config = {item["id"]: item for item in map(_topic_record, topics)}
    analyzed = [
        paper
        for paper in rows
        if (paper.get("analysis") or {}).get("status") in {"ok", "extractive"}
    ]
    open_access = [paper for paper in rows if paper.get("is_open_access")]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for paper in rows:
        grouped.setdefault(str(paper.get("topic_id") or "unclassified"), []).append(paper)

    topic_summaries: list[dict[str, Any]] = []
    for topic_id, topic_papers in grouped.items():
        config = topic_config.get(
            topic_id,
            {"id": topic_id, "name": topic_papers[0].get("topic_name") or topic_id, "include": []},
        )
        terms = _focus_terms(topic_papers, list(config.get("include") or []))
        high_priority = sorted(
            topic_papers,
            key=lambda item: (float(item.get("score") or 0), int(item.get("citation_count") or 0)),
            reverse=True,
        )[:3]
        analyzed_count = sum(
            (paper.get("analysis") or {}).get("status") in {"ok", "extractive"}
            for paper in topic_papers
        )
        focus_text = "、".join(terms) if terms else "该主题的最新研究问题"
        lead_title = high_priority[0]["title"] if high_priority else "暂无代表论文"
        topic_summaries.append(
            {
                "id": topic_id,
                "name": config["name"],
                "count": len(topic_papers),
                "share": round(len(topic_papers) / max(1, len(rows)) * 100),
                "analyzed_count": analyzed_count,
                "average_score": round(
                    sum(float(paper.get("score") or 0) for paper in topic_papers)
                    / len(topic_papers)
                    * 100
                ),
                "focus_terms": terms,
                "explanation": (
                    f"本期“{config['name']}”共收录 {len(topic_papers)} 篇，研究焦点集中在"
                    f"{focus_text}。建议先阅读《{lead_title}》，再结合其方法与结果条目判断"
                    "是否进入精读队列。"
                ),
                "highlights": high_priority,
            }
        )
    topic_summaries.sort(key=lambda item: (item["count"], item["average_score"]), reverse=True)

    type_counts = Counter(
        str((paper.get("analysis") or {}).get("paper_type") or "unknown") for paper in rows
    )
    type_distribution = [
        {
            "id": paper_type,
            "label": PAPER_TYPE_LABELS.get(paper_type, "待人工判断"),
            "count": count,
            "share": round(count / max(1, len(rows)) * 100),
        }
        for paper_type, count in type_counts.most_common()
    ]
    source_counts = Counter(source for paper in rows for source in paper.get("sources") or [])
    sources = [
        {"name": source, "count": count, "share": round(count / max(1, len(rows)) * 100)}
        for source, count in source_counts.most_common()
    ]
    highlights = sorted(
        rows,
        key=lambda item: (float(item.get("score") or 0), int(item.get("citation_count") or 0)),
        reverse=True,
    )[:6]
    finished_at = str((latest_run or {}).get("finished_at") or "")
    return {
        "run_id": (latest_run or {}).get("id"),
        "period_label": f"{finished_at[:10]} 自动周报" if finished_at else "最新文献周报",
        "paper_count": len(rows),
        "analyzed_count": len(analyzed),
        "analysis_rate": round(len(analyzed) / max(1, len(rows)) * 100),
        "open_access_count": len(open_access),
        "open_access_rate": round(len(open_access) / max(1, len(rows)) * 100),
        "average_score": round(
            sum(float(paper.get("score") or 0) for paper in rows) / max(1, len(rows)) * 100
        ),
        "topics": topic_summaries,
        "paper_types": type_distribution,
        "sources": sources,
        "highlights": highlights,
    }
