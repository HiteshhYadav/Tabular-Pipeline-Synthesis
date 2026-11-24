"""Liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.config import settings
from app.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report that the process is up, and whether execution is switched on.

    No dependency checks. A missing runner venv is reported by /execute
    itself, with a message saying how to create it, rather than here.
    """
    enabled = settings.enable_local_execution
    return HealthResponse(
        status="ok",
        version=__version__,
        execution_enabled=enabled,
        execution_sample_rows=settings.execution_sample_rows if enabled else None,
        auth_required=bool(settings.api_token_list),
    )
