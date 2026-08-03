from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.export import rows_to_bibtex

PACKAGE_DIR = Path(__file__).parent


def _snapshot_id(latest_run: dict | None) -> str:
    timestamp = (latest_run or {}).get("finished_at") or (latest_run or {}).get("started_at")
    if timestamp:
        return str(timestamp)[:10]
    return datetime.now(UTC).date().isoformat()


def _read_snapshots(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return payload if isinstance(payload, list) else []


def _render_page(
    template,
    *,
    papers: list[dict],
    topics: list[dict],
    active_topic: str,
    latest_run: dict | None,
    analysis_modes: list,
    css_path: str,
    home_path: str,
    topic_paths: dict[str, str],
    bib_path: str,
    archive_path: str,
    snapshot_label: str,
) -> str:
    return template.render(
        request=None,
        papers=papers,
        topics=topics,
        active_topic=active_topic,
        latest_run=latest_run,
        analysis_modes=analysis_modes,
        static_mode=True,
        static_css_path=css_path,
        home_path=home_path,
        topic_paths=topic_paths,
        bib_path=bib_path,
        archive_path=archive_path,
        snapshot_label=snapshot_label,
        scan_state={"scanning": False, "last_error": ""},
    )


def export_static(output_dir: Path, settings: Settings | None = None) -> dict:
    """Export the current database as a Pages-safe site and dated snapshot.

    An existing ``archive`` directory is deliberately preserved. The Pages
    workflow restores it from the previous ``gh-pages`` deployment before this
    function runs, so weekly snapshots accumulate instead of disappearing.
    """
    settings = settings or Settings()
    settings.ensure_runtime_files()
    database = Database(settings.database_path)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(PACKAGE_DIR / "templates")),
        autoescape=select_autoescape(("html", "xml")),
    )
    page_template = env.get_template("index.html")
    archive_template = env.get_template("archive.html")

    shutil.copyfile(PACKAGE_DIR / "static" / "styles.css", output_dir / "styles.css")
    (output_dir / ".nojekyll").touch()

    latest_run = database.latest_run()
    modes = settings.load_analysis_modes()
    topics = database.list_topics()
    snapshot_id = _snapshot_id(latest_run)
    generated_at = datetime.now(UTC).isoformat()
    snapshot_label = f"{snapshot_id} 文献快照"

    all_papers = database.list_papers(limit=500)
    (output_dir / "litwatch-all.bib").write_text(rows_to_bibtex(all_papers), encoding="utf-8")
    root_topic_paths = {topic["id"]: f"topics/{topic['id']}/" for topic in topics}
    (output_dir / "index.html").write_text(
        _render_page(
            page_template,
            papers=all_papers[:200],
            topics=topics,
            active_topic="",
            latest_run=latest_run,
            analysis_modes=modes,
            css_path="styles.css",
            home_path="index.html",
            topic_paths=root_topic_paths,
            bib_path="litwatch-all.bib",
            archive_path="archive/",
            snapshot_label=snapshot_label,
        ),
        encoding="utf-8",
    )

    topic_root = output_dir / "topics"
    for topic in topics:
        topic_id = topic["id"]
        papers = database.list_papers(topic_id=topic_id, limit=500)
        bib_name = f"litwatch-{topic_id}.bib"
        (output_dir / bib_name).write_text(rows_to_bibtex(papers), encoding="utf-8")
        topic_dir = topic_root / topic_id
        topic_dir.mkdir(parents=True, exist_ok=True)
        topic_paths = {
            item["id"]: ("./" if item["id"] == topic_id else f"../{item['id']}/") for item in topics
        }
        (topic_dir / "index.html").write_text(
            _render_page(
                page_template,
                papers=papers[:200],
                topics=topics,
                active_topic=topic_id,
                latest_run=latest_run,
                analysis_modes=modes,
                css_path="../../styles.css",
                home_path="../../index.html",
                topic_paths=topic_paths,
                bib_path=f"../../{bib_name}",
                archive_path="../../archive/",
                snapshot_label=snapshot_label,
            ),
            encoding="utf-8",
        )

    archive_root = output_dir / "archive"
    snapshot_dir = archive_root / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "litwatch-all.bib").write_text(rows_to_bibtex(all_papers), encoding="utf-8")
    (snapshot_dir / "index.html").write_text(
        _render_page(
            page_template,
            papers=all_papers[:200],
            topics=topics,
            active_topic="",
            latest_run=latest_run,
            analysis_modes=modes,
            css_path="../../styles.css",
            home_path="../../index.html",
            topic_paths={topic["id"]: f"../../topics/{topic['id']}/" for topic in topics},
            bib_path="litwatch-all.bib",
            archive_path="../",
            snapshot_label=snapshot_label,
        ),
        encoding="utf-8",
    )

    manifest_path = archive_root / "snapshots.json"
    snapshots = [item for item in _read_snapshots(manifest_path) if item.get("id") != snapshot_id]
    snapshots.append(
        {
            "id": snapshot_id,
            "label": snapshot_label,
            "generated_at": generated_at,
            "paper_count": len(all_papers),
            "path": f"{snapshot_id}/",
        }
    )
    snapshots.sort(key=lambda item: str(item.get("id", "")), reverse=True)
    manifest_path.write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (archive_root / "index.html").write_text(
        archive_template.render(snapshots=snapshots), encoding="utf-8"
    )
    database.connection.close()
    return {
        "output_dir": str(output_dir),
        "snapshot_id": snapshot_id,
        "paper_count": len(all_papers),
        "topic_count": len(topics),
    }
