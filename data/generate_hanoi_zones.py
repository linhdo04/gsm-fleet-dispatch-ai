import json
import math
from pathlib import Path

import h3


CENTER_LAT = 21.028511
CENTER_LNG = 105.804817
H3_RESOLUTION = 7
ZONE_COUNT = 30

TYPE_CONFIG = {
    "central_business": {"base_demand_weight": 1.50, "peak_profile": "all_day_high"},
    "office": {"base_demand_weight": 1.35, "peak_profile": "weekday_commute"},
    "residential": {"base_demand_weight": 1.00, "peak_profile": "morning_out_evening_in"},
    "commercial": {"base_demand_weight": 1.25, "peak_profile": "evening_weekend"},
    "university": {"base_demand_weight": 1.15, "peak_profile": "class_hours"},
    "transport_hub": {"base_demand_weight": 1.45, "peak_profile": "arrival_departure"},
    "mixed_use": {"base_demand_weight": 1.10, "peak_profile": "balanced"},
    "peripheral": {"base_demand_weight": 0.70, "peak_profile": "low_density"},
}

LAND_USE_ANCHORS = [
    ("transport_hub", "Bến xe Mỹ Đình", 21.0284, 105.7783, 0.9),
    ("transport_hub", "Ga Hà Nội", 21.0242, 105.8412, 0.8),
    ("transport_hub", "Bến xe Giáp Bát", 20.9807, 105.8417, 0.9),
    ("transport_hub", "Bến xe Nước Ngầm", 20.9649, 105.8425, 0.8),
    ("university", "Cụm đại học Bách Khoa - Kinh tế - Xây dựng", 21.0055, 105.8433, 1.2),
    ("university", "Đại học Quốc gia - Xuân Thủy", 21.0375, 105.7825, 1.1),
    ("university", "Cụm đại học Nguyễn Trãi", 20.9907, 105.7988, 1.0),
    ("central_business", "Hồ Hoàn Kiếm", 21.0287, 105.8522, 1.8),
    ("office", "Duy Tân", 21.0302, 105.7827, 1.8),
    ("office", "Keangnam - Phạm Hùng", 21.0174, 105.7830, 1.6),
    ("office", "Ba Đình", 21.0358, 105.8145, 1.7),
    ("office", "Láng Hạ - Thái Hà", 21.0163, 105.8108, 1.6),
    ("commercial", "Vincom Bà Triệu", 21.0112, 105.8496, 1.3),
    ("commercial", "Royal City", 21.0022, 105.8150, 1.4),
    ("commercial", "Times City", 20.9947, 105.8680, 1.4),
    ("commercial", "Aeon Mall Long Biên", 21.0274, 105.8990, 1.4),
    ("commercial", "The Garden - Mễ Trì", 21.0131, 105.7751, 1.3),
    ("residential", "Tây Hồ", 21.0640, 105.8180, 2.2),
    ("residential", "Ciputra", 21.0745, 105.7955, 1.8),
    ("residential", "Linh Đàm", 20.9645, 105.8270, 1.8),
    ("residential", "Vinhomes Riverside", 21.0510, 105.8910, 1.8),
]


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat_km = (lat1 - lat2) * 111.32
    lng_km = (lng1 - lng2) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(lat_km**2 + lng_km**2)


def classify_zone(lat: float, lng: float) -> dict:
    matches = []
    nearest = None
    for zone_type, anchor_name, anchor_lat, anchor_lng, radius_km in LAND_USE_ANCHORS:
        distance = distance_km(lat, lng, anchor_lat, anchor_lng)
        cell_radius_allowance_km = 1.0 if H3_RESOLUTION == 7 else 0.0
        effective_radius_km = radius_km + cell_radius_allowance_km
        candidate = (distance / effective_radius_km, distance, zone_type, anchor_name)
        if nearest is None or distance < nearest[0]:
            nearest = (distance, anchor_name)
        if distance <= effective_radius_km:
            matches.append(candidate)

    if matches:
        _, anchor_distance, zone_type, anchor_name = min(matches)
    else:
        distance_from_center = distance_km(lat, lng, CENTER_LAT, CENTER_LNG)
        if distance_from_center >= 6.4:
            zone_type = "peripheral"
        elif distance_from_center >= 4.2:
            zone_type = "residential"
        else:
            zone_type = "mixed_use"
        anchor_distance, anchor_name = nearest

    config = TYPE_CONFIG[zone_type]
    return {
        "zone_type": zone_type,
        "classification_anchor": anchor_name,
        "anchor_distance_km": round(anchor_distance, 2),
        "base_demand_weight": config["base_demand_weight"],
        "peak_profile": config["peak_profile"],
        "classification_method": "deterministic_poc_anchor_rule_v1",
    }


def distance_score(cell: str) -> float:
    lat, lng = h3.cell_to_latlng(cell)
    lat_km = (lat - CENTER_LAT) * 111.32
    lng_km = (lng - CENTER_LNG) * 111.32 * math.cos(math.radians(CENTER_LAT))
    return lat_km**2 + lng_km**2


def main() -> None:
    center_cell = h3.latlng_to_cell(CENTER_LAT, CENTER_LNG, H3_RESOLUTION)
    candidates = h3.grid_disk(center_cell, 9)
    selected = sorted(candidates, key=lambda cell: (distance_score(cell), cell))[:ZONE_COUNT]

    selected_set = set(selected)
    connected = {selected[0]}
    frontier = [selected[0]]
    while frontier:
        current = frontier.pop()
        for neighbor in h3.grid_disk(current, 1):
            if neighbor in selected_set and neighbor not in connected:
                connected.add(neighbor)
                frontier.append(neighbor)
    if connected != selected_set:
        raise RuntimeError("Generated zone set is not contiguous")

    features = []
    zone_records = []
    for index, cell in enumerate(selected, start=1):
        zone_id = f"HN-Z{index:03d}"
        center_lat, center_lng = h3.cell_to_latlng(cell)
        boundary = h3.cell_to_boundary(cell)
        coordinates = [[lng, lat] for lat, lng in boundary]
        coordinates.append(coordinates[0])

        classification = classify_zone(center_lat, center_lng)

        properties = {
            "zone_id": zone_id,
            "name": f"Hà Nội Zone {index:03d}",
            "h3_index": cell,
            "h3_resolution": H3_RESOLUTION,
            "center_lat": round(center_lat, 7),
            "center_lng": round(center_lng, 7),
            **classification,
        }
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "Polygon", "coordinates": [coordinates]},
            }
        )
        zone_records.append(
            {
                **properties,
                "boundary": [
                    {"lat": round(lat, 7), "lng": round(lng, 7)}
                    for lat, lng in boundary
                ],
            }
        )

    output_dir = Path(__file__).resolve().parent
    geojson = {
        "type": "FeatureCollection",
        "name": "hanoi_urban_h3_zones",
        "metadata": {
            "scope": "Hanoi urban core PoC, not Hanoi administrative boundary",
            "zone_count": ZONE_COUNT,
            "h3_resolution": H3_RESOLUTION,
            "generator_center": {"lat": CENTER_LAT, "lng": CENTER_LNG},
        },
        "features": features,
    }
    (output_dir / "hanoi_zones.geojson").write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "hanoi_zones.json").write_text(
        json.dumps(zone_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_area_km2 = sum(h3.cell_area(cell, unit="km^2") for cell in selected)
    print(
        f"Generated {len(features)} contiguous zones at H3 resolution "
        f"{H3_RESOLUTION}, covering {total_area_km2:.2f} km²."
    )


if __name__ == "__main__":
    main()
