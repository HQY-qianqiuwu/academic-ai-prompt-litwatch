from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from litwatch.analysis import PaperAnalyzer
from litwatch.analysis_repository import AnalysisRepository
from litwatch.api_models import (
    JobCreateRequest,
    JobResponse,
    LiteratureSearchRequest,
    LiteratureSearchResponse,
    PaperAnalysisJobRequest,
    ProviderCapabilityResponse,
    ProviderProfileResponse,
    ProviderProfileWrite,
    RadarCreateRequest,
    RadarUpdateRequest,
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SubscriptionRunResponse,
    SubscriptionUpdateRequest,
)
from litwatch.config import Settings, Topic
from litwatch.db import Database
from litwatch.delivery_repository import DeliveryRepository
from litwatch.export import rows_to_bibtex
from litwatch.historical_paper_repository import HistoricalPaperRepository
from litwatch.job_repository import JobRepository
from litwatch.llm.factory import build_llm_runtime
from litwatch.pipeline import Pipeline
from litwatch.provider_config import ProviderProfileStore, default_provider_profile
from litwatch.provider_security import ProviderBaseUrlError, validate_provider_base_url
from litwatch.radar_repository import RadarRepository
from litwatch.radars import ResearchRadar
from litwatch.runtime import ApplicationRuntime, RuntimeStatus
from litwatch.services import (
    AllProvidersFailedError,
    LiteratureSearchService,
    SubscriptionNotFoundError,
    SubscriptionProviderError,
    SubscriptionService,
)
from litwatch.services.delivery import DeliveryService
from litwatch.services.jobs import JobHandler, JobWorker
from litwatch.services.paper_analysis import (
    PaperAnalysisJobHandler,
    PaperAnalysisService,
)
from litwatch.services.radars import (
    RadarNotFoundError,
    RadarProviderError,
    RadarScanAlreadyActiveError,
    RadarScanUnavailableError,
    RadarYearRangeError,
    ResearchRadarService,
)
from litwatch.services.scheduler import SchedulerService
from litwatch.services.subscription_runs import (
    RunAlreadyActiveError,
    SubscriptionRunError,
    SubscriptionRunService,
)
from litwatch.sources.registry import (
    InMemoryCredentialStore,
    ProviderRegistry,
    ProviderRegistryError,
)
from litwatch.subscription_repository import SubscriptionRepository
from litwatch.subscription_run_repository import SubscriptionRunRepository

PACKAGE_DIR = Path(__file__).parent


def create_app(
    settings: Settings | None = None,
    literature_search_service: LiteratureSearchService | None = None,
    provider_registry: ProviderRegistry | None = None,
    provider_profile_store: ProviderProfileStore | None = None,
    credential_store: InMemoryCredentialStore | None = None,
    provider_base_url_validator: Callable[[str], str] | None = None,
    subscription_service: SubscriptionService | None = None,
    subscription_run_service: SubscriptionRunService | None = None,
    scheduler_service: SchedulerService | None = None,
    research_radar_service: ResearchRadarService | None = None,
    job_handlers: Mapping[str, JobHandler] | None = None,
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
    subscription_repository = (
        subscription_service.repository
        if subscription_service is not None
        else SubscriptionRepository(database)
    )
    subscription_service = subscription_service or SubscriptionService(
        subscription_repository, provider_registry, provider_profile_store
    )
    historical_repository = HistoricalPaperRepository(database)
    run_repository = SubscriptionRunRepository(database)
    delivery_repository = DeliveryRepository(database)
    delivery_service = DeliveryService(delivery_repository, historical_repository)
    subscription_run_service = subscription_run_service or SubscriptionRunService(
        search_service,
        subscription_repository,
        run_repository,
        historical_repository,
        delivery_service,
    )
    scheduler_service = scheduler_service or SchedulerService(
        subscription_repository,
        run_repository,
        subscription_run_service,
        poll_seconds=settings.scheduler_poll_seconds,
        lease_seconds=settings.scheduler_lease_seconds,
    )
    radar_repository = (
        research_radar_service.repository
        if research_radar_service is not None
        else RadarRepository(database)
    )
    research_radar_service = research_radar_service or ResearchRadarService(
        radar_repository,
        provider_registry,
        provider_profile_store,
        search_service=search_service,
    )
    scan_lock = threading.Lock()
    state_lock = threading.Lock()
    scan_state: dict[str, object] = {"scanning": False, "last_error": ""}
    job_repository = JobRepository(database)
    job_worker = JobWorker(
        job_repository,
        poll_seconds=settings.job_poll_seconds,
        lease_seconds=settings.job_lease_seconds,
        concurrency=settings.job_concurrency,
        default_timeout_seconds=settings.job_default_timeout_seconds,
    )

    analysis_llm_runtime = build_llm_runtime(settings, database=database)
    analysis_service = PaperAnalysisService(
        analyzer=PaperAnalyzer(
            settings,
            gateway=(analysis_llm_runtime.gateway if analysis_llm_runtime else None),
            budget_factory=(
                analysis_llm_runtime.budget_factory if analysis_llm_runtime else None
            ),
        ),
        repository=AnalysisRepository(database),
    )
    job_worker.register(
        "paper_analysis",
        PaperAnalysisJobHandler(
            database=database,
            topics=settings.load_topics,
            service=analysis_service,
        ),
    )

    custom_job_types = frozenset((job_handlers or {}).keys())
    for job_type, handler in (job_handlers or {}).items():
        job_worker.register(job_type, handler)

    def close_owned_resources() -> None:
        try:
            if analysis_llm_runtime is not None:
                analysis_llm_runtime.close()
        finally:
            database.connection.close()

    def close_owned_resources_when_worker_drains() -> None:
        if job_worker.active_count == 0:
            close_owned_resources()
            return

        def wait_for_drain() -> None:
            while job_worker.active_count:
                threading.Event().wait(0.01)
            try:
                close_owned_resources()
            except Exception:  # noqa: BLE001 - deferred cleanup has no caller
                return

        threading.Thread(
            target=wait_for_drain,
            name="litwatch-resource-cleanup",
            daemon=True,
        ).start()

    runtime = ApplicationRuntime(
        database_preflight=database.verify_migrations,
        scheduler_start=scheduler_service.start,
        scheduler_stop=scheduler_service.stop,
        worker_start=job_worker.start,
        worker_stop=job_worker.stop,
        startup_hooks=(research_radar_service.recover_stale_scans,),
        shutdown_hooks=(close_owned_resources_when_worker_drains,),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            runtime.start()
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="LitWatch", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.literature_search_service = search_service
    app.state.provider_registry = provider_registry
    app.state.provider_profile_store = provider_profile_store
    app.state.credential_store = credential_store
    app.state.subscription_service = subscription_service
    app.state.subscription_run_service = subscription_run_service
    app.state.subscription_run_repository = run_repository
    app.state.delivery_repository = delivery_repository
    app.state.scheduler_service = scheduler_service
    app.state.runtime = runtime
    app.state.job_repository = job_repository
    app.state.job_worker = job_worker
    app.state.paper_analysis_service = analysis_service
    app.state.research_radar_service = research_radar_service
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
            pipeline: Pipeline | None = None
            try:
                pipeline = Pipeline(settings, worker_database)
                pipeline.run(days=days, topics=topics)
            except Exception as exc:  # noqa: BLE001 - surfaced in dashboard and health
                with state_lock:
                    scan_state["last_error"] = f"{type(exc).__name__}: {exc}"
            finally:
                if pipeline is not None:
                    pipeline.close()
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

    @app.get("/subscriptions", response_class=HTMLResponse)
    async def subscription_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="subscriptions.html",
            context={},
        )

    @app.get("/subscriptions/{subscription_id}/runs", response_class=HTMLResponse)
    async def subscription_run_history_page(request: Request, subscription_id: str):
        try:
            subscription = subscription_service.get(subscription_id)
        except SubscriptionNotFoundError:
            raise HTTPException(status_code=404, detail="Subscription not found") from None
        return templates.TemplateResponse(
            request=request,
            name="subscription_run_history.html",
            context={"subscription": subscription},
        )

    @app.get("/weekly-digests", response_class=HTMLResponse)
    async def weekly_digests(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="weekly_digests.html",
            context={},
        )

    @app.get("/radars", response_class=HTMLResponse)
    @app.get("/radars/new", response_class=HTMLResponse)
    async def radars_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="radars.html",
            context={},
        )

    @app.get("/radars/{radar_id}", response_class=HTMLResponse)
    @app.get("/radars/{radar_id}/scans", response_class=HTMLResponse)
    async def radar_detail_page(request: Request, radar_id: str):
        try:
            radar = research_radar_service.get(radar_id)
        except RadarNotFoundError:
            raise HTTPException(status_code=404, detail="Research Radar not found") from None
        return templates.TemplateResponse(
            request=request,
            name="radar_detail.html",
            context={"radar": radar},
        )

    @app.get("/dashboard")
    async def dashboard_compatibility_redirect():
        return RedirectResponse(url="/radars", status_code=307)

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

    @app.get("/api/v2/runtime")
    def runtime_status() -> dict[str, bool | str]:
        status = RuntimeStatus.from_mode(settings.runtime_mode)
        return {
            "mode": status.mode.value,
            "python_primary": status.python_primary,
            "requires_dify": status.requires_dify,
            "requires_docker": status.requires_docker,
            "requires_ssrf_proxy": status.requires_ssrf_proxy,
        }

    @app.post("/api/v2/jobs", response_model=JobResponse, status_code=202)
    def create_job(payload: JobCreateRequest) -> JobResponse:
        if payload.job_type not in job_worker.registered_job_types:
            raise HTTPException(status_code=422, detail="unsupported job type")
        if payload.job_type == "paper_analysis" and "paper_analysis" not in custom_job_types:
            try:
                PaperAnalysisJobRequest.model_validate(payload.payload)
            except ValidationError:
                raise HTTPException(
                    status_code=422, detail="invalid paper analysis request"
                ) from None
        canonical_payload = json.dumps(
            payload.payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        input_hash = hashlib.sha256(
            f"{payload.job_type}\0{canonical_payload}".encode()
        ).hexdigest()
        record = job_repository.enqueue(
            job_type=payload.job_type,
            idempotency_key=payload.idempotency_key,
            input_hash=input_hash,
            payload=payload.payload,
            max_attempts=payload.max_attempts,
            timeout_seconds=(
                payload.timeout_seconds or settings.job_default_timeout_seconds
            ),
        )
        return JobResponse.from_record(record)

    @app.get("/api/v2/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str) -> JobResponse:
        record = job_repository.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return JobResponse.from_record(record)

    @app.post("/api/v2/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str) -> JobResponse:
        try:
            record = job_repository.request_cancel(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="job not found") from None
        return JobResponse.from_record(record)

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

    @app.get("/api/v1/subscriptions", response_model=list[SubscriptionResponse])
    def subscriptions() -> list[SubscriptionResponse]:
        return [
            SubscriptionResponse.from_subscription(subscription)
            for subscription in subscription_service.list()
        ]

    @app.post(
        "/api/v1/subscriptions",
        response_model=SubscriptionResponse,
        status_code=201,
    )
    def create_subscription(payload: SubscriptionCreateRequest) -> SubscriptionResponse:
        try:
            subscription = subscription_service.create(payload)
        except SubscriptionProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return SubscriptionResponse.from_subscription(subscription)

    @app.get(
        "/api/v1/subscriptions/{subscription_id}",
        response_model=SubscriptionResponse,
    )
    def get_subscription(subscription_id: str) -> SubscriptionResponse:
        try:
            subscription = subscription_service.get(subscription_id)
        except SubscriptionNotFoundError:
            raise HTTPException(status_code=404, detail="Subscription not found") from None
        return SubscriptionResponse.from_subscription(subscription)

    @app.patch(
        "/api/v1/subscriptions/{subscription_id}",
        response_model=SubscriptionResponse,
    )
    def update_subscription(
        subscription_id: str, payload: SubscriptionUpdateRequest
    ) -> SubscriptionResponse:
        changes = payload.model_dump(exclude_unset=True)
        try:
            subscription = subscription_service.update(subscription_id, changes)
        except SubscriptionNotFoundError:
            raise HTTPException(status_code=404, detail="Subscription not found") from None
        except SubscriptionProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except ValidationError as error:
            safe_errors = [
                {
                    key: value
                    for key, value in item.items()
                    if key in {"loc", "msg", "type"}
                }
                for item in error.errors()
            ]
            raise HTTPException(status_code=422, detail=safe_errors) from None
        return SubscriptionResponse.from_subscription(subscription)

    @app.post(
        "/api/v1/subscriptions/{subscription_id}/run",
        response_model=SubscriptionRunResponse,
    )
    def run_subscription(subscription_id: str) -> SubscriptionRunResponse:
        try:
            result = subscription_run_service.run_now(subscription_id)
        except SubscriptionNotFoundError:
            raise HTTPException(status_code=404, detail="Subscription not found") from None
        except RunAlreadyActiveError:
            raise HTTPException(status_code=409, detail="Subscription run already active") from None
        except SubscriptionRunError:
            raise HTTPException(status_code=502, detail="Subscription run failed") from None
        return SubscriptionRunResponse.from_result(result)

    def radar_summary(radar: ResearchRadar) -> dict[str, object]:
        radar_id = radar.id
        latest_successful = radar_repository.latest_successful_scan(radar_id)
        latest = radar_repository.latest_scan(radar_id)
        relations = radar_repository.list_paper_relations(radar_id)
        trends = latest_successful.analysis.get("trends", []) if latest_successful else []
        return {
            **radar.model_dump(mode="json"),
            "paper_count": len(relations),
            "hot_trend_count": sum(
                item.get("classification") in {"hot", "emerging"}
                for item in trends
                if isinstance(item, dict)
            ),
            "latest_scan_status": latest.status.value if latest else None,
        }

    @app.get("/api/v1/radars")
    def radars() -> list[dict[str, object]]:
        return [radar_summary(radar) for radar in research_radar_service.list()]

    @app.post("/api/v1/radars", status_code=201)
    def create_radar(payload: RadarCreateRequest) -> dict[str, object]:
        try:
            radar = research_radar_service.create(payload)
        except (RadarProviderError, RadarYearRangeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return radar_summary(radar)

    @app.get("/api/v1/radars/{radar_id}")
    def get_radar(radar_id: str) -> dict[str, object]:
        try:
            radar = research_radar_service.get(radar_id)
        except RadarNotFoundError:
            raise HTTPException(status_code=404, detail="Research Radar not found") from None
        latest = radar_repository.latest_successful_scan(radar_id)
        return {
            **radar_summary(radar),
            "analysis": latest.analysis if latest else {},
        }

    @app.patch("/api/v1/radars/{radar_id}")
    def update_radar(
        radar_id: str, payload: RadarUpdateRequest
    ) -> dict[str, object]:
        try:
            radar = research_radar_service.update(
                radar_id, payload.model_dump(exclude_unset=True)
            )
        except RadarNotFoundError:
            raise HTTPException(status_code=404, detail="Research Radar not found") from None
        except (RadarProviderError, RadarYearRangeError, ValidationError, ValueError):
            raise HTTPException(status_code=422, detail="Invalid Research Radar configuration") from None
        return radar_summary(radar)

    def run_radar_scan(scan_id: str) -> None:
        try:
            research_radar_service.execute_scan(scan_id)
        except (RadarScanUnavailableError, RadarNotFoundError):
            return

    @app.post("/api/v1/radars/{radar_id}/scan", status_code=202)
    def scan_radar(
        radar_id: str, background_tasks: BackgroundTasks
    ) -> dict[str, str]:
        try:
            scan = research_radar_service.start_scan(radar_id)
        except RadarNotFoundError:
            raise HTTPException(status_code=404, detail="Research Radar not found") from None
        except RadarScanAlreadyActiveError:
            raise HTTPException(
                status_code=409, detail="Research Radar scan already active"
            ) from None
        except RadarScanUnavailableError:
            raise HTTPException(status_code=409, detail="Research Radar is unavailable") from None
        background_tasks.add_task(run_radar_scan, scan.id)
        return {"status": "accepted", "scan_id": scan.id}

    @app.get("/api/v1/radars/{radar_id}/scans")
    def radar_scans(radar_id: str) -> list[dict[str, object]]:
        if radar_repository.get(radar_id) is None:
            raise HTTPException(status_code=404, detail="Research Radar not found")
        return [scan.model_dump(mode="json") for scan in radar_repository.list_scans(radar_id)]

    @app.get("/api/v1/radars/{radar_id}/papers")
    def radar_papers(radar_id: str) -> list[dict[str, object]]:
        if radar_repository.get(radar_id) is None:
            raise HTTPException(status_code=404, detail="Research Radar not found")
        relations = {
            relation.canonical_id: relation
            for relation in radar_repository.list_paper_relations(radar_id)
        }
        return [
            {
                **paper.model_dump(mode="json"),
                "publication_year": relations[paper.canonical_id].publication_year,
                "relevance_score": relations[paper.canonical_id].relevance_score,
                "representative_score": relations[
                    paper.canonical_id
                ].representative_score,
            }
            for paper in radar_repository.list_papers(radar_id)
        ]

    def latest_analysis(radar_id: str, field: str) -> list[object]:
        if radar_repository.get(radar_id) is None:
            raise HTTPException(status_code=404, detail="Research Radar not found")
        latest = radar_repository.latest_successful_scan(radar_id)
        value = latest.analysis.get(field, []) if latest else []
        return value if isinstance(value, list) else []

    @app.get("/api/v1/radars/{radar_id}/timeline")
    def radar_timeline(radar_id: str) -> list[object]:
        return latest_analysis(radar_id, "timeline")

    @app.get("/api/v1/radars/{radar_id}/trends")
    def radar_trends(radar_id: str) -> list[object]:
        return latest_analysis(radar_id, "trends")

    @app.get("/api/v1/deliveries")
    def deliveries(subscription_id: str | None = None) -> list[dict[str, object]]:
        return [
            delivery.model_dump(mode="json")
            for delivery in delivery_repository.list(subscription_id)
        ]

    @app.get("/api/v1/deliveries/{delivery_id}")
    def delivery_detail(delivery_id: str) -> dict[str, object]:
        delivery = delivery_repository.get(delivery_id)
        if delivery is None:
            raise HTTPException(status_code=404, detail="Digest not found")
        return delivery.model_dump(mode="json")

    @app.get("/api/v1/subscriptions/{subscription_id}/runs")
    def subscription_runs(subscription_id: str) -> list[dict[str, object]]:
        if not subscription_repository.exists(subscription_id):
            raise HTTPException(status_code=404, detail="Subscription not found")
        return [
            run.model_dump(mode="json")
            for run in run_repository.list_for_subscription(subscription_id)
        ]

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
