from __future__ import annotations

import html
import smtplib
import ssl
from collections import Counter
from email.message import EmailMessage

from litwatch.config import Settings
from litwatch.models import Paper, RunSummary


def render_digest(summary: RunSummary, papers: list[Paper], *, limit: int = 20) -> str:
    topic_counts = Counter(paper.topic_name or "未分类" for paper in papers)
    topic_summary = "".join(
        f'<span style="display:inline-block;margin:4px;padding:6px 10px;border-radius:999px;'
        f'background:#e7f4f1;color:#0f766e">{html.escape(name)} · {count} 篇</span>'
        for name, count in topic_counts.most_common()
    )
    cards: list[str] = []
    for paper in papers[:limit]:
        analysis = paper.analysis
        one_liner = str(analysis.get("one_liner") or paper.abstract[:260] or "暂无摘要")
        authors = ", ".join(author.name for author in paper.authors[:6])
        cards.append(
            f"""
            <article style="margin:18px 0;padding:18px;border:1px solid #dbe4e8;border-radius:12px">
              <div style="color:#0f766e;font-size:13px">{html.escape(paper.topic_name)} · 评分 {paper.score:.2f}</div>
              <h3 style="margin:8px 0"><a href="{html.escape(paper.url)}">{html.escape(paper.title)}</a></h3>
              <div style="color:#62737b;font-size:13px">{html.escape(authors)} · {paper.publication_date or ""} · {html.escape(paper.venue)}</div>
              <p>{html.escape(one_liner)}</p>
              <p style="padding:10px;background:#f1f7f5;border-left:3px solid #65b7aa;font-size:13px"><strong>主题阐述：</strong>{html.escape(str(analysis.get("relevance") or f"归入 {paper.topic_name}，建议结合摘要与方法条目判断是否精读。"))}</p>
              <div style="font-size:12px;color:#62737b">来源：{html.escape(", ".join(paper.sources))} · 引用 {paper.citation_count} · {"开放全文" if paper.is_open_access else "未确认开放全文"}</div>
            </article>
            """
        )
    return f"""<!doctype html><html><body style="font-family:Arial,'Microsoft YaHei',sans-serif;color:#17323a;max-width:760px;margin:auto">
    <h1>LitWatch 文献雷达</h1>
    <p>本次获取 {summary.fetched} 条，去重后 {summary.deduplicated} 条，入选 {summary.accepted} 条，AI 分析 {summary.analyzed} 条。</p>
    <div style="margin:14px 0">{topic_summary}</div>
    {"".join(cards) if cards else "<p>本期没有达到阈值的新论文。</p>"}
    </body></html>"""


def send_email(settings: Settings, subject: str, html_body: str) -> None:
    required = [
        settings.smtp_host,
        settings.smtp_username,
        settings.smtp_password,
        settings.email_from,
        settings.email_to,
    ]
    if not all(required):
        raise ValueError("SMTP 配置不完整，请检查 .env")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = settings.email_to
    message.set_content("请使用支持 HTML 的邮件客户端查看 LitWatch 文献摘要。")
    message.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as server:
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
