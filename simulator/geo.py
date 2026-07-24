"""random_point_in_zone() — điểm ngẫu nhiên thật trong polygon H3 hex của
zone (không phải tâm zone cố định), để `distance_m` giữa driver và target
zone trong Acceptance History không còn rời rạc hoá thành 3 giá trị cố định
(xem docs/week2_data_sanity_check.md mục 4, khuyến nghị sửa #1).

Dùng rejection sampling trong bounding box của `boundary` + kiểm tra thành
viên bằng chính định nghĩa H3 cell (`zone["h3_index"]`) — tận dụng luôn
nguồn sự thật đã sinh ra boundary (data/generate_hanoi_zones.py), không cần
viết thuật toán point-in-polygon riêng.
"""

from __future__ import annotations

import h3
import numpy as np


def random_point_in_zone(zone: dict, rng: np.random.Generator, max_attempts: int = 100) -> tuple:
    boundary = zone["boundary"]
    lat_min = min(point["lat"] for point in boundary)
    lat_max = max(point["lat"] for point in boundary)
    lng_min = min(point["lng"] for point in boundary)
    lng_max = max(point["lng"] for point in boundary)
    h3_index = zone["h3_index"]
    resolution = zone["h3_resolution"]

    for _ in range(max_attempts):
        lat = float(rng.uniform(lat_min, lat_max))
        lng = float(rng.uniform(lng_min, lng_max))
        if h3.latlng_to_cell(lat, lng, resolution) == h3_index:
            return lat, lng
    # Cực hiếm khi rơi vào đây (100 lần rejection sampling đều trượt) — trả
    # về tâm zone như fallback an toàn thay vì raise, không làm sập simulator.
    return zone["center_lat"], zone["center_lng"]
