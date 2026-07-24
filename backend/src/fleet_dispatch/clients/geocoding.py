"""Async client cho Google Geocoding API — bản port của
ml/geocoding_client.py sang httpx cho backend FastAPI.

Khác routes.py, geocoding không có fallback offline hợp lý — không thể đoán
toạ độ từ chuỗi text mà không gọi API thật. Thiếu GOOGLE_GEOCODING_API_KEY
hoặc API lỗi/không tìm thấy địa chỉ -> raise GeocodingError rõ ràng, endpoint
gọi module này chịu trách nhiệm chuyển thành HTTP error response phù hợp."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

GEOCODING_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"


class GeocodingError(RuntimeError):
    pass


@dataclass
class GeocodeResult:
    formatted_address: str
    lat: float
    lng: float


async def geocode_address(
    api_key: str | None,
    address: str,
    *,
    client: httpx.AsyncClient,
) -> GeocodeResult:
    if not api_key:
        raise GeocodingError("Thiếu GOOGLE_GEOCODING_API_KEY trong môi trường.")

    try:
        response = await client.get(
            GEOCODING_ENDPOINT,
            params={"address": address, "key": api_key, "region": "vn"},
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise GeocodingError(f"Gọi Geocoding API thất bại: {exc}") from exc

    status = payload.get("status")
    if status != "OK":
        raise GeocodingError(
            f"Geocoding thất bại cho '{address}': {status} — {payload.get('error_message', '')}"
        )

    try:
        result = payload["results"][0]
        return GeocodeResult(
            formatted_address=result["formatted_address"],
            lat=result["geometry"]["location"]["lat"],
            lng=result["geometry"]["location"]["lng"],
        )
    except (KeyError, IndexError) as exc:
        raise GeocodingError(f"Phản hồi Geocoding API không đúng định dạng kỳ vọng: {exc}") from exc
