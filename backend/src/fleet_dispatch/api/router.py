from fastapi import APIRouter

from fleet_dispatch.api.routes.geocoding import router as geocoding_router
from fleet_dispatch.api.routes.health import router as health_router
from fleet_dispatch.api.routes.routing import router as routing_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(routing_router, tags=["routing"])
api_router.include_router(geocoding_router, tags=["geocoding"])
