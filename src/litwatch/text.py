from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", " ", value).strip()


def canonical_id(*, doi: str = "", arxiv_id: str = "", title: str) -> str:
    if doi:
        return "doi:" + doi.lower().removeprefix("https://doi.org/").strip()
    if arxiv_id:
        return "arxiv:" + arxiv_id.lower().split("v")[0].strip()
    digest = hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()[:24]
    return "title:" + digest


def abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positioned = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(positioned))
