from __future__ import annotations

import hashlib
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.export import rows_to_bibtex
from litwatch.pipeline import Pipeline

PACKAGE_DIR = Path(__file__).parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_runtime_files()
    database = Database(settings.database_path)
    scan_lock = threading.Lock()
    state_lock = threading.Lock()
    scan_state: dict[str, object] = {"scanning": False, "last_error": ""}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        database.connection.close()

    app = FastAPI(title="LitWatch", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.scan_state = scan_state
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    def state_snapshot() -> dict[str, object]:
        with state_lock:
            return dict(scan_state)

    def start_scan(*, days: int, topics: list[Topic] | None = None) -> bool:
        if not scan_lock.acquire(blocking=False):
            return False
        with state_lock:
            scan_state.update(scanning=True, last_error="")

        def worker() -> None:
            worker_database = Database(settings.database_path)
            try:
                Pipeline(settings, worker_database).run(days=days, topics=topics)
            except Exception as exc:  # noqa: BLE001 - surfaced in dashboard and health
                with state_lock:
                    scan_state["last_error"] = f"{type(exc).__name__}: {exc}"
            finally:
                worker_database.connection.close()
                with state_lock:
                    scan_state["scanning"] = False
                scan_lock.release()

        threading.Thread(target=worker, name="litwatch-scan", daemon=True).start()
        return True

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request, topic: str = ""):
        configured_topics = settings.load_topics()
        known_ids = {item.id for item in configured_topics}
        topics = configured_topics + [
            item for item in database.list_topics() if item["id"] not in known_ids
        ]
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "papers": database.list_papers(topic_id=topic, limit=200),
                "topics": topics,
                "active_topic": topic,
                "latest_run": database.latest_run(),
                "analysis_modes": settings.load_analysis_modes(),
                "static_mode": False,
                "scan_state": state_snapshot(),
            },
        )

    @app.post("/run")
    async def run_now(days: int = Form(default=settings.lookback_days)):
        status = "scanning" if start_scan(days=days) else "busy"
        return RedirectResponse(url=f"/?status={status}", status_code=303)

    @app.post("/quick-search")
    async def quick_search(
        name: str = Form(min_length=2, max_length=80),
        query: str = Form(min_length=3, max_length=500),
        include: str = Form(default=""),
        exclude: str = Form(default=""),
        analysis_mode: str = Form(default="quick_scan"),
        days: int = Form(default=30, ge=1, le=365),
    ):
        valid_modes = {mode.id for mode in settings.load_analysis_modes()}
        if analysis_mode not in valid_modes:
            analysis_mode = "quick_scan"
        digest = hashlib.sha256(f"{name}\0{query}".encode()).hexdigest()[:10]
        topic_id = f"quick_{digest}"
        topic = Topic(
            id=topic_id,
            name=name.strip(),
            query=query.strip(),
            include=[value.strip() for value in include.split(",") if value.strip()],
            exclude=[value.strip() for value in exclude.split(",") if value.strip()],
            analysis_mode=analysis_mode,
            min_score=0.2,
        )
        status = "scanning" if start_scan(days=days, topics=[topic]) else "busy"
        return RedirectResponse(url=f"/?topic={topic_id}&status={status}", status_code=303)

    @app.get("/export/bibtex", response_class=PlainTextResponse)
    async def export_bibtex(topic: str = ""):
        body = rows_to_bibtex(database.list_papers(topic_id=topic, limit=500))
        filename = f"litwatch-{topic or 'all'}.bib"
        return PlainTextResponse(
            body,
            media_type="application/x-bibtex",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "latest_run": database.latest_run(),
            **state_snapshot(),
        }

    return app


app = create_app()
