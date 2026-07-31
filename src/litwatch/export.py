from __future__ import annotations

import re


def _escape_bibtex(value: str) -> str:
    return value.replace("{", "\\{").replace("}", "\\}")


def rows_to_bibtex(rows: list[dict]) -> str:
    entries: list[str] = []
    used_keys: set[str] = set()
    for index, row in enumerate(rows, start=1):
        authors = row.get("authors") or []
        first_author = authors[0]["name"].split()[-1] if authors else "paper"
        year = (row.get("publication_date") or "nd")[:4]
        key_base = re.sub(r"[^A-Za-z0-9]", "", f"{first_author}{year}") or f"paper{index}"
        key = key_base
        suffix = 2
        while key in used_keys:
            key = f"{key_base}{suffix}"
            suffix += 1
        used_keys.add(key)

        fields = {
            "title": row.get("title") or "",
            "author": " and ".join(author["name"] for author in authors),
            "year": year if year != "nd" else "",
            "journal": row.get("venue") or "",
            "doi": row.get("doi") or "",
            "url": row.get("url") or "",
            "abstract": row.get("abstract") or "",
        }
        rendered = [
            f"  {name} = {{{_escape_bibtex(str(value))}}}"
            for name, value in fields.items()
            if value
        ]
        entries.append(f"@article{{{key},\n" + ",\n".join(rendered) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")
