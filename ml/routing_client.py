"""`get_route()` từ `docs/business_design.md` mục 2.8 — gọi Google Routes API
thật khi có API key, cache theo cặp toạ độ (làm tròn 4 chữ số thập phân,
~10m, nên 2 lần gọi cùng cặp zone centroid sẽ luôn trúng cache), và fallback
Haversine × hệ số đường vòng khi không có key hoặc API lỗi — đúng quy trình
5 bước ở mục 2.8:
    1. Haversine lọc top ứng viên trước khi gọi (việc của caller, không phải
       của client này).
    2. Gọi Google Routes API cho các cặp ứng viên đã lọc.
    3. Dùng `traffic_aware_duration_seconds` để chấm điểm.
    4. Cache theo cặp zone trong thời gian ngắn (`zone_pair_cache_ttl_seconds`).
    5. Lỗi/hết quota → fallback Haversine × hệ số đường vòng, đánh dấu
       `is_fallback: true`.

Không có `GOOGLE_ROUTES_API_KEY` trong môi trường này — mọi lần chạy trong
dự án này đều đi qua nhánh fallback, đã kiểm chứng bằng
`ml/tests/test_routing_client.py`. Đặt biến môi trường
`GOOGLE_ROUTES_API_KEY` để bật lệnh gọi thật, không cần sửa code gọi module
này ở bất kỳ đâu khác.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import requests

GOOGLE_ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
BASE_SPEED_M_PER_S = 7.0  # ~420 m/min, cùng hằng số fallback dùng trong simulator/engine.py và matching_flow.py


@dataclass
class RouteResult:
    distance_m: float
    duration_seconds: float
    traffic_aware_duration_seconds: float
    encoded_polyline: Optional[str]
    provider: str  # "google_routes" | "haversine_fallback"
    is_fallback: bool


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Giải mã encoded polyline (thuật toán chuẩn của Google, precision 5)
    từ `RouteResult.encoded_polyline` thành danh sách điểm (lat, lng) để vẽ
    đường đi thật trên bản đồ, thay vì nối thẳng điểm đầu/cuối."""
    points: list[tuple[float, float]] = []
    index, lat, lng = 0, 0, 0
    length = len(encoded)
    while index < length:
        for coord in ("lat", "lng"):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if coord == "lat":
                lat += delta
            else:
                lng += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _cache_key(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> str:
    # Làm tròn 4 chữ số thập phân (~10m) — đủ để 2 lần gọi cùng cặp zone
    # centroid luôn trúng cache mà không cần client biết khái niệm "zone".
    return f"{origin_lat:.4f},{origin_lng:.4f}->{dest_lat:.4f},{dest_lng:.4f}"


class GoogleRoutesClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_path: Optional[Path] = None,
        cache_ttl_seconds: int = 300,
        fallback_road_distance_multiplier: float = 1.3,
        timeout_seconds: float = 5.0,
    ):
        self.api_key = api_key if api_key else os.environ.get("GOOGLE_ROUTES_API_KEY")
        self.cache_path = cache_path
        self.cache_ttl_seconds = cache_ttl_seconds
        self.fallback_road_distance_multiplier = fallback_road_distance_multiplier
        self.timeout_seconds = timeout_seconds
        self._cache: dict = self._load_cache()

    def _load_cache(self) -> dict:
        if self.cache_path and self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _cached(self, key: str) -> Optional[RouteResult]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() - entry["cached_at"] > self.cache_ttl_seconds:
            return None
        return RouteResult(**entry["result"])

    def _store(self, key: str, result: RouteResult) -> None:
        self._cache[key] = {"cached_at": time.time(), "result": asdict(result)}

    def _call_google_routes_api(
        self, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
    ) -> RouteResult:
        """Google Routes API — Compute Routes (mục 2.8 business_design.md).
        Format request/response theo tài liệu chính thức của Google; chưa
        từng gọi thật trong môi trường này vì không có API key — nếu response
        khác định dạng kỳ vọng (Google đổi API), lỗi sẽ rơi xuống nhánh
        fallback ở `get_route()`, không làm sập luồng chính."""
        response = requests.post(
            GOOGLE_ROUTES_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline.encodedPolyline",
            },
            json={
                "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}},
                "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lng}}},
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        route = payload["routes"][0]
        traffic_aware_seconds = float(route["duration"].rstrip("s"))
        static_seconds = float(route.get("staticDuration", route["duration"]).rstrip("s"))
        # Origin == destination -> Google trả "routes": [{"duration": "0s"}], bỏ hẳn
        # distanceMeters (không phải lỗi định dạng, đã kiểm chứng thật) -> coi là 0m.
        return RouteResult(
            distance_m=float(route.get("distanceMeters", 0.0)),
            duration_seconds=static_seconds,
            traffic_aware_duration_seconds=traffic_aware_seconds,
            encoded_polyline=route.get("polyline", {}).get("encodedPolyline"),
            provider="google_routes",
            is_fallback=False,
        )

    def _fallback(self, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> RouteResult:
        distance_m = _haversine_m(origin_lat, origin_lng, dest_lat, dest_lng) * self.fallback_road_distance_multiplier
        duration_seconds = distance_m / BASE_SPEED_M_PER_S
        return RouteResult(
            distance_m=distance_m,
            duration_seconds=duration_seconds,
            traffic_aware_duration_seconds=duration_seconds,
            encoded_polyline=None,
            provider="haversine_fallback",
            is_fallback=True,
        )

    def get_route(self, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> RouteResult:
        key = _cache_key(origin_lat, origin_lng, dest_lat, dest_lng)
        cached = self._cached(key)
        if cached is not None:
            return cached

        if self.api_key:
            try:
                result = self._call_google_routes_api(origin_lat, origin_lng, dest_lat, dest_lng)
            except (requests.RequestException, KeyError, ValueError, IndexError):
                result = self._fallback(origin_lat, origin_lng, dest_lat, dest_lng)
        else:
            result = self._fallback(origin_lat, origin_lng, dest_lat, dest_lng)

        self._store(key, result)
        self._save_cache()
        return result
