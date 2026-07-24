"""Async client cho Google Routes API — bản port của ml/routing_client.py
sang httpx (async) cho backend FastAPI, cùng logic fallback: thiếu
GOOGLE_ROUTES_API_KEY hoặc API lỗi/timeout -> ước lượng Haversine x hệ số
đường vòng, đánh dấu is_fallback=True, không bao giờ raise ra caller."""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx

ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
BASE_SPEED_M_PER_S = 7.0
FALLBACK_ROAD_DISTANCE_MULTIPLIER = 1.3


@dataclass
class RouteEstimate:
    distance_m: float
    duration_seconds: float
    traffic_aware_duration_seconds: float
    provider: str
    is_fallback: bool


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fallback(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
) -> RouteEstimate:
    distance_m = (
        _haversine_m(origin_lat, origin_lng, dest_lat, dest_lng) * FALLBACK_ROAD_DISTANCE_MULTIPLIER
    )
    duration_seconds = distance_m / BASE_SPEED_M_PER_S
    return RouteEstimate(
        distance_m=distance_m,
        duration_seconds=duration_seconds,
        traffic_aware_duration_seconds=duration_seconds,
        provider="haversine_fallback",
        is_fallback=True,
    )


async def estimate_route(
    api_key: str | None,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    *,
    client: httpx.AsyncClient,
) -> RouteEstimate:
    if not api_key:
        return _fallback(origin_lat, origin_lng, dest_lat, dest_lng)

    try:
        response = await client.post(
            ROUTES_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters",
            },
            json={
                "origin": {
                    "location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}
                },
                "destination": {
                    "location": {"latLng": {"latitude": dest_lat, "longitude": dest_lng}}
                },
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
            },
        )
        response.raise_for_status()
        payload = response.json()
        route = payload["routes"][0]
        traffic_aware_seconds = float(route["duration"].rstrip("s"))
        static_seconds = float(route.get("staticDuration", route["duration"]).rstrip("s"))
        return RouteEstimate(
            distance_m=float(route["distanceMeters"]),
            duration_seconds=static_seconds,
            traffic_aware_duration_seconds=traffic_aware_seconds,
            provider="google_routes",
            is_fallback=False,
        )
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return _fallback(origin_lat, origin_lng, dest_lat, dest_lng)
