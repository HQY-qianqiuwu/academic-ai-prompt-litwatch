from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from importlib.util import find_spec

from litwatch.config import Topic
from litwatch.models import Paper
from litwatch.text import normalize_title

_semantic_model: object | None | bool = None


def _get_model():
    global _semantic_model
    if _semantic_model is False:
        return None
    if _semantic_model is None:
        if find_spec("sentence_transformers") is None or find_spec("numpy") is None:
            _semantic_model = False
            return None
        try:
            from sentence_transformers import SentenceTransformer

            _semantic_model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:  # noqa: BLE001 - optional model/network failures must degrade safely
            _semantic_model = False
            return None
    return _semantic_model


def _semantic_relevance(text: str, terms: list[str]) -> float | None:
    if not terms:
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        import numpy as np

        doc_emb = model.encode([text], show_progress_bar=False)
        term_embs = model.encode(terms, show_progress_bar=False)
        sims = np.dot(term_embs, doc_emb.T).flatten()
        return float(np.clip(sims.mean(), 0, 1))
    except Exception:  # noqa: BLE001 - optional inference must never break keyword ranking
        return None


def _contains(text: str, phrase: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(normalize_title(phrase))}(?![a-z0-9])"
    return bool(re.search(pattern, text))


def score_paper(paper: Paper, topic: Topic, *, today: date | None = None) -> Paper:
    today = today or datetime.now(UTC).date()
    title = normalize_title(paper.title)
    body = normalize_title(f"{paper.title} {paper.abstract}")
    include = [term for term in topic.include if term.strip()]

    if any(_contains(body, term) for term in topic.exclude):
        paper.score = 0
        paper.score_detail = {"excluded": 1.0}
        return paper

    paper_fulltext = f"{paper.title} {paper.abstract}"
    if include:
        body_hits = sum(_contains(body, term) for term in include) / len(include)
        title_hits = sum(_contains(title, term) for term in include) / len(include)
        keyword_relevance = min(1.0, body_hits * 0.65 + title_hits * 0.8)
        semantic = _semantic_relevance(paper_fulltext, include)
        relevance = (
            keyword_relevance if semantic is None else keyword_relevance * 0.6 + semantic * 0.4
        )
    else:
        query_tokens = {
            token for token in re.findall(r"\w+", topic.query.casefold()) if len(token) > 2
        }
        matched = sum(token in body for token in query_tokens)
        relevance = matched / max(1, len(query_tokens))

    age_days = max(0, (today - paper.publication_date).days) if paper.publication_date else 365
    recency = math.exp(-age_days / 45)
    impact = min(1.0, math.log1p(max(0, paper.citation_count)) / math.log(101))
    access = 1.0 if paper.is_open_access or paper.pdf_url else 0.0
    metadata = min(1.0, (bool(paper.abstract) + bool(paper.doi) + bool(paper.authors)) / 3)

    paper.score_detail = {
        "relevance": round(relevance, 4),
        "recency": round(recency, 4),
        "impact": round(impact, 4),
        "access": access,
        "metadata": round(metadata, 4),
    }
    paper.score = round(
        relevance * 0.58 + recency * 0.18 + impact * 0.10 + access * 0.08 + metadata * 0.06,
        4,
    )
    return paper
