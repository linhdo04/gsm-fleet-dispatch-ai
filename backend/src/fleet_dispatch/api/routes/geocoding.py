from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from fleet_dispatch.clients.geocoding import GeocodingError, geocode_address

router = APIRouter()


class GeocodeRequest(BaseModel):
    address: str = Field(min_length=1)


class GeocodeResponse(BaseModel):
    formatted_address: str
    lat: float
    lng: float


@router.post(
    "/geocoding/lookup",
    response_model=GeocodeResponse,
    summary="Geocode a free-text address to coordinates",
)
async def geocoding_lookup(body: GeocodeRequest, request: Request) -> GeocodeResponse:
    settings = request.app.state.settings
    try:
        result = await geocode_address(
            settings.google_geocoding_api_key,
            body.address,
            client=request.app.state.http_client,
        )
    except GeocodingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return GeocodeResponse(
        formatted_address=result.formatted_address, lat=result.lat, lng=result.lng
    )
