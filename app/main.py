"""FastAPI app factory, lifespan, and middleware wiring."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import health
from app.config import get_settings
from app.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hold process-lifetime state. Minimal for now — grows with later features."""
    settings = get_settings()
    app.state.settings = settings
    # Long-lived state is wired in by its owning feature:
    #   app.state.job_store        -> Feature 13 (in-memory JobStore)
    #   app.state.browser_manager  -> Feature 06 (lazy shared Chromium)
    #   app.state.scheduler        -> Feature 15 (bounded scheduler)
    # Shutdown order will matter then: drain the scheduler BEFORE closing the
    # browser (a no-op if it was never launched).
    yield


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
