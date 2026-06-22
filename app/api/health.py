"""Liveness endpoint: `GET /health` → 200 while the process is up."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Body of `GET /health`."""

    status: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return 200 whenever the process is up.

    Liveness only — does not probe the browser, providers, or network. If a
    readiness signal is ever needed, add a separate `/ready` (see architecture.md).
    """
    return HealthResponse(status="ok")
