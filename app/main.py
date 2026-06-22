"""FastAPI app factory, lifespan, and middleware wiring."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import health
from app.config import get_settings
from app.fetching.browser import BrowserManager
from app.jobs.store import JobStore
from app.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hold process-lifetime state. Minimal for now — grows with later features."""
    settings = get_settings()
    app.state.settings = settings
    # Shared Chromium owner: created here, but Chromium itself launches lazily on the
    # first render=true request, so HTTP-only runs never start a browser.
    app.state.browser_manager = BrowserManager(settings)
    # Single source of job state for the process; the runner (F14) drives it.
    app.state.job_store = JobStore(settings=settings)
    # Still wired in by its owning feature:
    #   app.state.scheduler  -> Feature 15 (bounded scheduler)
    try:
        yield
    finally:
        # Feature 15 will drain the scheduler BEFORE this close (in-flight renders
        # must finish first). For now just close the browser — a no-op if it was
        # never launched.
        await app.state.browser_manager.aclose()


def create_app() -> FastAPI:
    """Build the FastAPI app: configure logging, add middleware, mount routes."""
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(title="AI-Web-Scraper", lifespan=lifespan)
    # v1 DNS-rebinding baseline: only serve requests whose Host is allow-listed.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.include_router(health.router)
    return app


app = create_app()
