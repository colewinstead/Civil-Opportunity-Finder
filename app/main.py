"""Application factory: initialize storage and scheduler during lifespan."""
import asyncio
import secrets
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings
from app.database import Base, create_database
from app.logging_config import configure_logging
from app.routes import api, web
from app.scrapers.registry import SCRAPERS, sync_sources
from app.services.collection import CollectionService


def create_app(settings: Settings | None = None, registry=None) -> FastAPI:
    settings = settings or Settings()
    registry = SCRAPERS if registry is None else registry

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging()
        engine, sessions = create_database(settings.database_url)
        Base.metadata.create_all(engine)
        with sessions.begin() as session:
            sync_sources(session, registry)
        collection = CollectionService(sessions, settings, registry)
        collection.recover_interrupted()
        application.state.settings = settings
        application.state.engine = engine
        application.state.sessions = sessions
        application.state.collection = collection
        scheduler = None
        if settings.enable_scheduler:
            scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
            scheduler.add_job(collection.scheduled_collect, "cron", hour=settings.scrape_hour, minute=settings.scrape_minute,
                              id="daily_collection", max_instances=1, coalesce=True, misfire_grace_time=3600)
            scheduler.start()
        application.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None:
                await asyncio.to_thread(scheduler.shutdown, wait=True)
            engine.dispose()

    application = FastAPI(title="Mississippi Civil Opportunity Finder", version="0.1.0", lifespan=lifespan,
                          docs_url=None, redoc_url=None)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @application.middleware("http")
    async def browser_security(request: Request, call_next):
        token = request.cookies.get("csrf_token")
        if not token or len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
            token = secrets.token_hex(32)
        request.state.csrf_token = token
        response = await call_next(request)
        if request.cookies.get("csrf_token") != token:
            response.set_cookie("csrf_token", token, httponly=True, samesite="strict", secure=request.url.scheme == "https")
        response.headers["X-Content-Type-Options"] = "nosniff"
        # no-referrer can make browser form POSTs carry Origin: null.
        # same-origin retains the local origin while omitting external referrers.
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        return response

    application.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
    application.include_router(api.router)
    application.include_router(web.router)
    return application


app = create_app()
