"""FastAPI app factory, lifespan, and middleware wiring."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import health
from app.config import get_settings
from app.fetching.browser import BrowserManager
from app.jobs.scheduler import Scheduler
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
    # Bounded background execution: admission cap + concurrency + graceful drain.
    app.state.scheduler = Scheduler(app_state=app.state, settings=settings)
    try:
        yield
    finally:
        # Drain in-flight jobs BEFORE closing the browser: renders may still be live,
        # and a stray render must not outlast Chromium. aclose() is a no-op if the
        # browser was never launched.
        await app.state.scheduler.shutdown()
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
