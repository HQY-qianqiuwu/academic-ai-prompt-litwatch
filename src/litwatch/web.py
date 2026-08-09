from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from litwatch.api_models import (
    LiteratureSearchRequest,
    LiteratureSearchResponse,
    ProviderCapabilityResponse,
    ProviderProfileResponse,
    ProviderProfileWrite,
)
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.export import rows_to_bibtex
from litwatch.pipeline import Pipeline
from litwatch.provider_config import ProviderProfileStore, default_provider_profile
from litwatch.provider_security import ProviderBaseUrlError, validate_provider_base_url
from litwatch.services import AllProvidersFailedError, LiteratureSearchService
from litwatch.sources.registry import (
    InMemoryCredentialStore,
    ProviderRegistry,
    ProviderRegistryError,
)
from litwatch.weekly_report import apply_current_topic_rules, build_weekly_report, enrich_papers

PACKAGE_DIR = Path(__file__).parent


def create_app(
    settings: Settings | None = None,
    literature_search_service: LiteratureSearchService | None = None,
    provider_registry: ProviderRegistry | None = None,
    provider_profile_store: ProviderProfileStore | None = None,
    credential_store: InMemoryCredentialStore | None = None,
    provider_base_url_validator: Callable[[str], str] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_runtime_files()
    database = Database(settings.database_path)
    credential_store = credential_store or InMemoryCredentialStore.from_settings(settings)
    provider_registry = provider_registry or ProviderRegistry.from_settings(
        settings, credential_store=credential_store
    )
    provider_profile_store = provider_profile_store or ProviderProfileStore(
        [
            default_provider_profile(
                openalex_base_url=settings.openalex_base_url,
                semantic_scholar_base_url=settings.semantic_scholar_base_url,
                arxiv_base_url=settings.arxiv_base_url,
                crossref_base_url=settings.crossref_base_url,
            )
        ]
    )
    provider_base_url_validator = provider_base_url_validator or validate_provider_base_url
    search_service = literature_search_service or LiteratureSearchService(
        registry=provider_registry,
        profile_store=provider_profile_store,
    )
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
    app.state.provider_registry = provider_registry
    app.state.provider_profile_store = provider_profile_store
    app.state.credential_store = credential_store
    app.state.scan_state = scan_state
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(_: Request, error: RequestValidationError):
        """Return useful validation metadata without echoing credential-bearing input."""
        safe_errors = [
            {
                key: value
                for key, value in item.items()
                if key in {"loc", "msg", "type"}
            }
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

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
    async def research_search(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="research_search.html",
            context={"static_mode": False},
        )

    @app.get("/provider-settings", response_class=HTMLResponse)
    async def provider_settings(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="provider_settings.html",
            context={},
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request, topic: str = ""):
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
            502: {"description": "All selected providers failed"},
            504: {"description": "All selected providers timed out"},
        },
    )
    def literature_search(payload: LiteratureSearchRequest) -> LiteratureSearchResponse:
        """Search literature through the provider-independent service boundary."""
        try:
            search_arguments: dict[str, object] = {
                "topic": payload.topic,
                "limit": payload.limit,
            }
            if payload.providers is not None:
                search_arguments["providers"] = payload.providers
            result = search_service.search(**search_arguments)
        except ProviderRegistryError:
            raise HTTPException(
                status_code=422, detail="Invalid provider selection or configuration"
            ) from None
        except AllProvidersFailedError as error:
            if error.all_timeouts:
                raise HTTPException(
                    status_code=504,
                    detail="All selected literature providers timed out",
                ) from None
            raise HTTPException(
                status_code=502,
                detail="All selected literature providers failed",
            ) from None
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Literature request timed out") from None
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError):
            raise HTTPException(status_code=502, detail="Literature request failed") from None

        return LiteratureSearchResponse.from_result(result)

    @app.get("/api/v1/providers", response_model=list[ProviderCapabilityResponse])
    def providers() -> list[ProviderCapabilityResponse]:
        """List declared capabilities and clearly identify runnable adapters."""
        return [
            ProviderCapabilityResponse.from_capability(capability)
            for capability in provider_registry.capabilities()
        ]

    @app.get("/api/v1/provider-profiles", response_model=list[ProviderProfileResponse])
    def provider_profiles() -> list[ProviderProfileResponse]:
        """List non-secret provider profiles and credential readiness only."""
        return [
            ProviderProfileResponse.from_profile(profile, credential_store)
            for profile in provider_profile_store.list()
        ]

    @app.post("/api/v1/provider-profiles", response_model=ProviderProfileResponse)
    def upsert_provider_profile(payload: ProviderProfileWrite) -> ProviderProfileResponse:
        """Upsert a profile and retain supplied credentials only in process memory."""
        try:
            try:
                existing_profile = provider_profile_store.get(payload.profile_id)
            except KeyError:
                existing_profile = None
            profile = payload.to_profile(existing_profile)
            for provider_update in payload.providers:
                if "base_url" not in provider_update.model_fields_set:
                    continue
                provider = profile.provider(provider_update.provider_id)
                provider_base_url_validator(str(provider.base_url))
        except (ProviderBaseUrlError, ValidationError, ValueError):
            raise HTTPException(status_code=422, detail="Invalid provider profile") from None

        credential_updates: list[tuple[str, str | None]] = []
        for provider_update in payload.providers:
            if provider_update.api_key is None and not provider_update.clear_secret:
                continue
            provider = profile.provider(provider_update.provider_id)
            if not provider.credential_reference:
                raise HTTPException(
                    status_code=422,
                    detail="Credential update requires credential_reference",
                )
            secret = (
                provider_update.api_key.get_secret_value()
                if provider_update.api_key is not None
                else None
            )
            credential_updates.append((provider.credential_reference, secret))
        for reference, secret in credential_updates:
            if secret is None:
                credential_store.clear(reference)
            else:
                credential_store.set(reference, secret)
        stored_profile = provider_profile_store.upsert(profile)
        return ProviderProfileResponse.from_profile(stored_profile, credential_store)

    return app


app = create_app()
