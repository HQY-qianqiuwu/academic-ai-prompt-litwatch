from __future__ import annotations

import hashlib
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from litwatch.api_models import LiteratureSearchRequest, LiteratureSearchResponse
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.export import rows_to_bibtex
from litwatch.pipeline import Pipeline
from litwatch.services import LiteratureSearchService
from litwatch.weekly_report import apply_current_topic_rules, build_weekly_report, enrich_papers

PACKAGE_DIR = Path(__file__).parent


def create_app(
    settings: Settings | None = None,
    literature_search_service: LiteratureSearchService | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_runtime_files()
    database = Database(settings.database_path)
    search_service = literature_search_service or LiteratureSearchService.from_settings(settings)
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
    app.state.literature_search_service = search_service
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
        latest_run = database.latest_run()
        latest_run_id = latest_run["id"] if latest_run else None
        weekly_papers = apply_current_topic_rules(
            database.list_papers(topic_id=topic, run_id=latest_run_id, limit=500),
            configured_topics,
        )
        visible_papers = apply_current_topic_rules(
            database.list_papers(topic_id=topic, limit=500), configured_topics
        )
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "papers": enrich_papers(visible_papers[:200]),
                "topics": topics,
                "active_topic": topic,
                "latest_run": latest_run,
                "weekly_report": build_weekly_report(
                    weekly_papers, configured_topics, latest_run
                ),
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

    @app.post(
        "/api/v1/literature/search",
        response_model=LiteratureSearchResponse,
        responses={
            502: {"description": "OpenAlex upstream HTTP or parse error"},
            504: {"description": "OpenAlex upstream timeout"},
        },
    )
    def literature_search(payload: LiteratureSearchRequest) -> LiteratureSearchResponse:
        """Search literature through the provider-independent service boundary."""
        try:
            result = search_service.search(topic=payload.topic, limit=payload.limit)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="OpenAlex request timed out") from None
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError):
            raise HTTPException(status_code=502, detail="OpenAlex upstream request failed") from None

        return LiteratureSearchResponse.from_result(result)

    return app


app = create_app()
