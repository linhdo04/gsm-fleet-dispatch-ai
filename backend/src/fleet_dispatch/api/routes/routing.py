from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from fleet_dispatch.clients.routes import estimate_route

router = APIRouter()


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RouteEstimateRequest(BaseModel):
    origin: LatLng
    destination: LatLng


class RouteEstimateResponse(BaseModel):
    distance_m: float
    duration_seconds: float
    traffic_aware_duration_seconds: float
    provider: str
    is_fallback: bool


@router.post(
    "/routes/estimate",
    response_model=RouteEstimateResponse,
    summary="Estimate driving distance/duration between two points",
)
async def routes_estimate(body: RouteEstimateRequest, request: Request) -> RouteEstimateResponse:
    settings = request.app.state.settings
    result = await estimate_route(
        settings.google_routes_api_key,
        body.origin.lat,
        body.origin.lng,
        body.destination.lat,
        body.destination.lng,
        client=request.app.state.http_client,
    )
    return RouteEstimateResponse(
        distance_m=result.distance_m,
        duration_seconds=result.duration_seconds,
        traffic_aware_duration_seconds=result.traffic_aware_duration_seconds,
        provider=result.provider,
        is_fallback=result.is_fallback,
    )
