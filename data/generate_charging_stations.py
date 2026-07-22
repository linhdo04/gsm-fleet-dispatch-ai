"""Sinh danh sách trạm sạc cho PoC — chưa có dữ liệu trạm sạc thật của GSM,
nên đặt 8 trạm theo farthest-point sampling trên 30 zone (bắt đầu từ zone
đầu tiên) để phủ đều khu vực thay vì đặt ngẫu nhiên/tuỳ tiện — cùng tinh
thần "giả lập có kiểm soát, có lý do rõ ràng" như cách phân loại zone_type
trong `generate_hanoi_zones.py`."""

import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
N_STATIONS = 8
PLUGS_PER_STATION = 6


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def main() -> None:
    zones = json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8"))
    zone_by_id = {z["zone_id"]: z for z in zones}
    distances = {
        (a["zone_id"], b["zone_id"]): haversine_m(a["center_lat"], a["center_lng"], b["center_lat"], b["center_lng"])
        for a in zones
        for b in zones
    }

    chosen = [zones[0]["zone_id"]]
    while len(chosen) < N_STATIONS:
        best_zone_id, best_min_dist = None, -1.0
        for z in zones:
            if z["zone_id"] in chosen:
                continue
            min_dist = min(distances[(z["zone_id"], c)] for c in chosen)
            if min_dist > best_min_dist:
                best_min_dist = min_dist
                best_zone_id = z["zone_id"]
        chosen.append(best_zone_id)

    stations = [
        {
            "station_id": f"CHG-{i:02d}",
            "name": f"Trạm sạc {zone_by_id[zone_id]['name']}",
            "zone_id": zone_id,
            "lat": zone_by_id[zone_id]["center_lat"],
            "lng": zone_by_id[zone_id]["center_lng"],
            "plug_count": PLUGS_PER_STATION,
        }
        for i, zone_id in enumerate(chosen, start=1)
    ]

    output_path = PROJECT_ROOT / "data" / "charging_stations.json"
    output_path.write_text(json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(stations)} charging stations to {output_path}")


if __name__ == "__main__":
    main()
