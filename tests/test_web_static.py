from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.models import Author, Paper
from litwatch.static_export import export_static
from litwatch.web import create_app


def settings_for(tmp_path: Path) -> Settings:
    topics = tmp_path / "topics.yaml"
    topics.write_text("topics: []\n", encoding="utf-8")
    return Settings(
        database_path=tmp_path / "litwatch.db",
        topics_path=topics,
        analysis_modes_path=Path("config/analysis_modes.yaml").resolve(),
    )


def seed_database(settings: Settings) -> None:
    database = Database(settings.database_path)
    run_id = database.start_run()
    database.upsert(
        Paper(
            canonical_id="doi:10.1234/test",
            title="A verified literature result",
            authors=[Author(name="Ada Lovelace")],
            publication_date=date(2026, 8, 1),
            url="https://doi.org/10.1234/test",
            topic_id="acoustics",
            topic_name="水声通信",
            score=0.82,
        ),
        run_id,
    )
    database.finish_run(run_id, fetched=1, deduplicated=1, accepted=1, analyzed=0, errors=[])
    database.connection.close()


def test_static_export_has_pages_safe_links_and_history(tmp_path):
    settings = settings_for(tmp_path)
    seed_database(settings)
    output = tmp_path / "site"

    result = export_static(output, settings)

    assert result["paper_count"] == 1
    assert (output / "index.html").exists()
    assert not (output / "index" / "index.html").exists()
    assert (output / "archive" / result["snapshot_id"] / "index.html").exists()
    assert (output / "archive" / "index.html").exists()
    assert (output / "litwatch-all.bib").exists()
    assert (output / "live-search.js").exists()
    root_html = (output / "index.html").read_text(encoding="utf-8")
    assert "data-live-search-form" in root_html
    assert 'src="live-search.js"' in root_html
    assert "Weekly research brief" in root_html
    assert "文章主题阐述" in root_html
    topic_html = (output / "topics" / "acoustics" / "index.html").read_text(encoding="utf-8")
    assert 'href="../../styles.css"' in topic_html
    assert 'href="../../litwatch-acoustics.bib"' in topic_html
    assert 'href="../../index.html"' in topic_html
    assert 'src="../../live-search.js"' in topic_html
    assert 'action="/quick-search"' not in topic_html

    manifest = json.loads((output / "archive" / "snapshots.json").read_text(encoding="utf-8"))
    assert manifest[0]["paper_count"] == 1

    manifest.append(
        {
            "id": "2026-07-20",
            "label": "2026-07-20 文献快照",
            "generated_at": "2026-07-20T00:00:00+00:00",
            "paper_count": 3,
            "path": "2026-07-20/",
        }
    )
    (output / "archive" / "snapshots.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    export_static(output, settings)
    updated = json.loads((output / "archive" / "snapshots.json").read_text(encoding="utf-8"))
    assert {item["id"] for item in updated} >= {"2026-07-20", result["snapshot_id"]}


def test_web_scan_is_non_blocking_and_reports_state(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    started = Event()
    release = Event()

    def slow_run(self, *, days=None, topics=None):
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr("litwatch.web.Pipeline.run", slow_run)
    with TestClient(create_app(settings)) as client:
        before = time.monotonic()
        response = client.post("/run", data={"days": "14"}, follow_redirects=False)
        elapsed = time.monotonic() - before

        assert response.status_code == 303
        assert response.headers["location"] == "/?status=scanning"
        assert elapsed < 0.5
        assert started.wait(timeout=0.5)
        assert client.get("/health").json()["scanning"] is True

        release.set()
        for _ in range(20):
            if client.get("/health").json()["scanning"] is False:
                break
            time.sleep(0.02)
        assert client.get("/health").json()["scanning"] is False
