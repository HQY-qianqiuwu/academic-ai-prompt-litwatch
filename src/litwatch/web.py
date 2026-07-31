from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from litwatch.config import Settings
from litwatch.db import Database
from litwatch.pipeline import Pipeline

PACKAGE_DIR = Path(__file__).parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_runtime_files()
    database = Database(settings.database_path)
    app = FastAPI(title="LitWatch", version="0.1.0")
    app.state.settings = settings
    app.state.database = database
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, topic: str = ""):
        topics = settings.load_topics()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "papers": database.list_papers(topic_id=topic, limit=200),
                "topics": topics,
                "active_topic": topic,
                "latest_run": database.latest_run(),
            },
        )

    @app.post("/run")
    def run_now(days: int = Form(default=settings.lookback_days)):
        Pipeline(settings, database).run(days=days)
        return RedirectResponse(url="/", status_code=303)

    @app.get("/health")
    def health():
        return {"status": "ok", "latest_run": database.latest_run()}

    return app


app = create_app()
