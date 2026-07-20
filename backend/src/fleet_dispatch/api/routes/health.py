from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/health/live", response_model=HealthResponse, summary="Liveness probe")
async def liveness() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse, summary="Readiness probe")
async def readiness() -> HealthResponse:
    # Add checks for required dependencies (database, cache) here when introduced.
    return HealthResponse()
