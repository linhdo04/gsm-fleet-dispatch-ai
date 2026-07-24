"""Geocoding client — chuyển địa chỉ text (vd "17 ngõ 182 Lương Thế Vinh,
Thanh Xuân, Hà Nội") thành toạ độ thật qua Google Geocoding API, rồi ánh xạ
vào đúng H3 zone (cùng độ phân giải 7 như `data/hanoi_zones.json`) để tương
thích với hệ thống zone hiện có.

Khác với `routing_client.py`, geocoding không có fallback offline hợp lý —
không thể đoán toạ độ từ chuỗi text mà không gọi API thật. Thiếu
`GOOGLE_GEOCODING_API_KEY` hoặc API lỗi/không tìm thấy địa chỉ -> raise
`GeocodingError` rõ ràng, không bao giờ trả về toạ độ bịa đặt.

Địa chỉ nằm ngoài 30 zone đã tạo cho demo này (data/generate_hanoi_zones.py)
vẫn được geocode thành toạ độ thật, chỉ có `zone_id`/`zone_name` trả về None.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import h3
import requests

GOOGLE_GEOCODING_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
ZONES_PATH = Path(__file__).resolve().parent.parent / "data" / "hanoi_zones.json"
H3_RESOLUTION = 7  # phải khớp H3_RESOLUTION trong data/generate_hanoi_zones.py


class GeocodingError(RuntimeError):
    pass


@dataclass
class GeocodeResult:
    formatted_address: str
    lat: float
    lng: float
    h3_index: str
    zone_id: Optional[str]
    zone_name: Optional[str]


def _load_zone_by_h3(zones_path: Path) -> dict:
    zones = json.loads(zones_path.read_text(encoding="utf-8"))
    return {zone["h3_index"]: zone for zone in zones}


class GeocodingClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        zones_path: Path = ZONES_PATH,
        timeout_seconds: float = 5.0,
    ):
        self.api_key = api_key if api_key else os.environ.get("GOOGLE_GEOCODING_API_KEY")
        self.timeout_seconds = timeout_seconds
        self._zone_by_h3 = _load_zone_by_h3(zones_path)

    def geocode(self, address: str) -> GeocodeResult:
        if not self.api_key:
            raise GeocodingError(
                "Thiếu GOOGLE_GEOCODING_API_KEY trong môi trường — không thể geocode địa chỉ thành toạ độ."
            )

        response = requests.get(
            GOOGLE_GEOCODING_ENDPOINT,
            params={"address": address, "key": self.api_key, "region": "vn"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        status = payload.get("status")
        if status != "OK":
            raise GeocodingError(
                f"Geocoding thất bại cho '{address}': {status} — {payload.get('error_message', '')}"
            )

        result = payload["results"][0]
        lat = result["geometry"]["location"]["lat"]
        lng = result["geometry"]["location"]["lng"]
        cell = h3.latlng_to_cell(lat, lng, H3_RESOLUTION)
        zone = self._zone_by_h3.get(cell)

        return GeocodeResult(
            formatted_address=result["formatted_address"],
            lat=lat,
            lng=lng,
            h3_index=cell,
            zone_id=zone["zone_id"] if zone else None,
            zone_name=zone["name"] if zone else None,
        )
