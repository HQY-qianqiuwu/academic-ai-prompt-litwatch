from __future__ import annotations

from datetime import UTC, datetime

import typer

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.models import Author, Paper
from litwatch.notifier import render_digest, send_email
from litwatch.pipeline import Pipeline
from litwatch.web import create_app
from litwatch.zotero import ZoteroExporter

app = typer.Typer(help="LitWatch 多源文献雷达")


def _settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_files()
    return settings


@app.command()
def scan(
    days: int | None = typer.Option(None, min=1, max=365, help="向前检索的天数"),
    email: bool = typer.Option(False, help="扫描后发送邮件摘要"),
) -> None:
    """执行一次多源检索、去重、排序和可选 AI 分析。"""
    settings = _settings()
    summary, papers = Pipeline(settings).run(days=days)
    typer.echo(summary.model_dump_json(indent=2))
    if email:
        today = datetime.now(UTC).date().isoformat()
        send_email(settings, f"LitWatch 周报：{today}", render_digest(summary, papers))
        typer.echo("邮件已发送。")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8000, min=1, max=65535)
) -> None:
    """启动本地 Web 仪表盘。"""
    import uvicorn

    uvicorn.run(create_app(_settings()), host=host, port=port)


@app.command("zotero-export")
def zotero_export(
    min_score: float = typer.Option(0.55, min=0, max=1),
    limit: int = typer.Option(20, min=1, max=50),
) -> None:
    """将数据库中的高分论文写入 Zotero。"""
    settings = _settings()
    rows = Database(settings.database_path).list_papers(limit=500)
    papers = []
    for row in rows:
        if float(row["score"]) < min_score:
            continue
        papers.append(
            Paper(
                canonical_id=row["canonical_id"],
                title=row["title"],
                abstract=row["abstract"],
                authors=[Author.model_validate(author) for author in row["authors"]],
                publication_date=row["publication_date"],
                venue=row["venue"],
                doi=row["doi"],
                url=row["url"],
                pdf_url=row["pdf_url"],
                is_open_access=bool(row["is_open_access"]),
                citation_count=row["citation_count"],
                sources=row["sources"],
                source_ids=row["source_ids"],
                topic_id=row["topic_id"],
                topic_name=row["topic_name"],
                score=row["score"],
                score_detail=row["score_detail"],
                analysis=row["analysis"],
            )
        )
        if len(papers) >= limit:
            break
    result = ZoteroExporter(settings).export(papers)
    typer.echo(f"已提交 {len(papers)} 篇；Zotero 响应：{result}")


if __name__ == "__main__":
    app()
