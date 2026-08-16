from __future__ import annotations

import html

import fitz


def render_html(digest: dict[str, object]) -> str:
    subscription = digest["subscription"]
    run = digest["run"]
    cards: list[str] = []
    for paper in digest["papers"]:
        title = html.escape(str(paper["title"]))
        authors = html.escape(", ".join(paper["authors"]))
        venue = html.escape(str(paper.get("venue") or ""))
        year = paper.get("year") or ""
        abstract = html.escape(str(paper.get("abstract") or ""))
        doi = html.escape(str(paper.get("doi") or ""))
        url = html.escape(str(paper.get("url") or ""))
        link = f'<a href="{url}">{title}</a>' if url else title
        cards.append(
            f"""
            <article style="margin:16px 0;padding:16px;border:1px solid #dbe4e8;border-radius:12px">
              <h3 style="margin:0 0 8px">{link}</h3>
              <div style="color:#62737b;font-size:13px">{authors} · {year} · {venue}</div>
              <p style="font-size:14px">{abstract}</p>
              <div style="font-size:12px;color:#0f766e">
                DOI: {doi} · 排名 {paper["rank_position"]} · 综合 {paper["rank_score"]:.2f}
                · 相关 {paper["relevance_score"]:.2f} · 质量 {paper["quality_score"]:.2f}
              </div>
            </article>
            """
        )
    body = "".join(cards) if cards else "<p>本期没有达到阈值的新论文。</p>"
    return f"""<!doctype html><html><body style="font-family:Arial,'Microsoft YaHei',sans-serif;color:#17323a;max-width:760px;margin:auto">
    <h1>LitWatch 每周文献推荐</h1>
    <p>订阅：{html.escape(str(subscription["name"]))} · 周期：{html.escape(str(digest["period"]))}</p>
    <p>新增 {run["new_count"]} 篇，推荐 {run["recommended_count"]} 篇。</p>
    {body}
    </body></html>"""


def render_pdf(digest: dict[str, object]) -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    subscription = digest["subscription"]
    run = digest["run"]
    y = 36.0

    def write(text: str, *, size: float = 12, bold: bool = False) -> None:
        nonlocal y
        page.insert_text(
            (36, y),
            text,
            fontsize=size,
            fontname="china-s",
        )
        y += size + 6

    write(f"LitWatch 每周文献推荐 - {subscription['name']}", size=18)
    write(f"周期：{digest['period']}    新增：{run['new_count']}    推荐：{run['recommended_count']}")
    for paper in digest["papers"]:
        if y > 780:
            page = document.new_page(width=595, height=842)
            y = 36.0
        write(f"{paper['rank_position']}. {paper['title']}", size=14)
        authors = ", ".join(paper["authors"])
        write(f"{authors} · {paper.get('year') or ''} · {paper.get('venue') or ''}", size=10)
        write(f"DOI: {paper.get('doi') or ''}    综合: {paper['rank_score']:.2f}"
              f"    相关: {paper['relevance_score']:.2f}    质量: {paper['quality_score']:.2f}", size=10)
        abstract = str(paper.get("abstract") or "")[:300]
        write(abstract, size=10)
        write("", size=6)
    return document.tobytes()
