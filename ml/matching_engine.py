"""SUPERSEDED — kept for history/reference only, not imported by
`ml/export_demo_data.py` or any current pipeline step.

Đây là bản Matching Engine đầu tiên (Tuần 4, theo `report.md` lúc đó):
Hungarian Algorithm cho ghép 1-1 mặc định, chuyển sang insertion heuristic
toàn cục khi mưa/giờ cao điểm/deficit vượt ngưỡng (`should_use_pooling`).

Sau khi có đặc tả chi tiết hơn ở `docs/business_design.md` ("Đặc tả luồng
Matching & Repositioning"), quyết định là **thay hẳn** thiết kế này bằng
`ml/matching_flow.py`: không còn "chế độ toàn cục" bật/tắt theo điều kiện,
mỗi request tự chạy qua cascade 4 bước (gán trực tiếp → chèn ghép chuyến →
chờ incoming → kích hoạt repositioning) và không dùng Hungarian Algorithm ở
đâu cả. Xem `ml/matching_flow.py` để biết thiết kế hiện hành.
"""

import argparse
import json
from itertools import product
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from .common import PROJECT_ROOT, load_config, load_zones
from .cost_model import FEATURE_COLUMNS as COST_FEATURE_COLUMNS
from .repositioning_suggester import build_zone_distances

LARGE_COST = 1e6  # excludes a pair from Hungarian without breaking the solver (needs finite costs)


def should_use_pooling(weather: str, hour: int, system_deficit: float, config: dict) -> bool:
    """report.md's trigger condition: ride-pooling activates on rain, on
    peak hours (7-9h, 17-19h), or once system-wide deficit exceeds a
    configured threshold — otherwise the engine defaults to plain 1-1
    Hungarian matching."""
    is_peak_hour = (7 <= hour < 9) or (17 <= hour < 19)
    is_rain = weather in {"rain", "heavy_rain", "storm"}
    deficit_threshold = config.get("matching", {}).get("pooling_deficit_threshold", 30)
    return is_peak_hour or is_rain or system_deficit >= deficit_threshold


def build_zone_pair_cost_table(
    zone_ids: List[str],
    zone_distances: Dict[tuple, float],
    zone_type_by_id: Dict[str, str],
    cost_model,
    context: dict,
) -> Dict[Tuple[str, str], float]:
    """report.md's own design note for the routing API applies just as well
    to the Cost Prediction Model: call it once per **zone pair**, not once
    per individual driver/request, and cache the result. For a fixed
    context (hour/weather/day — one per matching batch) there are only
    `zone_count^2` distinct costs, computed here in a *single* batched
    `predict()` call instead of one per candidate pair, which is what made
    the first version of this module too slow to finish."""
    pairs = list(product(zone_ids, zone_ids))
    distances = np.array([zone_distances[(a, b)] * 1.3 for a, b in pairs])
    frame = pd.DataFrame(
        {
            "distance_m": distances,
            "hour": context["hour"],
            "day_of_week": context["day_of_week"],
            "is_weekend": int(context["day_of_week"] >= 5),
            "is_holiday": int(context["is_holiday"]),
            "weather": context["weather"],
            "origin_zone_type": [zone_type_by_id[a] for a, _ in pairs],
            "destination_zone_type": [zone_type_by_id[b] for _, b in pairs],
        }
    )
    for col in ["weather", "origin_zone_type", "destination_zone_type"]:
        frame[col] = frame[col].astype("category")
    predicted = cost_model.predict(frame[COST_FEATURE_COLUMNS])
    return {pair: float(cost) for pair, cost in zip(pairs, predicted)}


def hungarian_match(
    drivers: pd.DataFrame,
    requests: pd.DataFrame,
    cost_table: Dict[Tuple[str, str], float],
    config: dict,
) -> List[dict]:
    """Default 1-1 mode: batch assignment via the Hungarian Algorithm
    (`scipy.optimize.linear_sum_assignment`). Cost matrix cell = predicted
    trip cost (Cost Prediction Model, via the cached zone-pair table) from a
    driver's zone to a request's pickup zone, plus a battery penalty so
    critically low-battery drivers are steered away from long pickups
    instead of being assigned them."""
    if drivers.empty or requests.empty:
        return []
    min_battery = float(config["battery"]["minimum_trip_reserve_percent"])
    low_battery = float(config["battery"]["low_battery_threshold_percent"])
    eligible = drivers[drivers["battery_percent"] >= min_battery].reset_index(drop=True)
    if eligible.empty:
        return []

    driver_zones = eligible["zone_id"].to_numpy()
    driver_battery = eligible["battery_percent"].to_numpy()
    pickup_zones = requests["pickup_zone_id"].to_numpy()

    cost_matrix = np.array(
        [[cost_table[(d_zone, p_zone)] for p_zone in pickup_zones] for d_zone in driver_zones]
    )
    # Low battery → heavily penalise long pickups (predicted cost > 10 min)
    # instead of a hard ban, so a nearby low-battery driver can still take a
    # short hop rather than being excluded from matching altogether.
    low_battery_mask = driver_battery[:, None] < low_battery
    long_pickup_mask = cost_matrix > 10.0
    cost_matrix = np.where(low_battery_mask & long_pickup_mask, cost_matrix + LARGE_COST / 2, cost_matrix)

    driver_idx, request_idx = linear_sum_assignment(cost_matrix)
    assignments = []
    for d_i, r_i in zip(driver_idx, request_idx):
        if cost_matrix[d_i, r_i] >= LARGE_COST:
            continue
        assignments.append(
            {
                "driver_id": eligible.iloc[d_i]["driver_id"],
                "request_id": requests.iloc[r_i]["request_id"],
                "predicted_cost_minutes": round(float(cost_matrix[d_i, r_i]), 2),
                "mode": "hungarian_1to1",
            }
        )
    return assignments


def _route_cost(stops: List[dict], cost_table: Dict[Tuple[str, str], float]) -> float:
    if len(stops) < 2:
        return 0.0
    return sum(cost_table[(a["zone_id"], b["zone_id"])] for a, b in zip(stops, stops[1:]))


def _feasible_insertions(stops: List[dict], capacity: int):
    """Every (pickup_index, dropoff_index) pair that keeps the route valid:
    pickup must come before its own dropoff, and passenger count on board
    must never exceed `vehicle_capacity`."""
    n = len(stops)
    onboard = 0
    onboard_by_position = [0]
    for stop in stops:
        onboard += 1 if stop["type"] == "pickup" else -1
        onboard_by_position.append(onboard)
    for i in range(n + 1):
        if onboard_by_position[i] >= capacity:
            continue
        for j in range(i, n + 1):
            yield i, j


def _nearby_candidate_drivers(
    routes: Dict[str, List[dict]],
    driver_zone_by_id: Dict[str, str],
    pickup_zone_id: str,
    zone_distances: Dict[tuple, float],
    candidate_radius_m: float,
    limit: int,
) -> List[str]:
    """Same principle as the Repositioning Suggester and report.md's
    `candidate_driver_limit_per_request`: only ever consider a small nearby
    pool, not the entire fleet — realistic (a driver across town is not a
    pooling candidate) and, incidentally, the difference between a demo
    that finishes instantly and one that doesn't."""
    driver_ids = list(routes.keys())
    driver_ids.sort(
        key=lambda driver_id: zone_distances[(driver_zone_by_id[driver_id], pickup_zone_id)]
    )
    nearby = [
        driver_id
        for driver_id in driver_ids
        if zone_distances[(driver_zone_by_id[driver_id], pickup_zone_id)] <= candidate_radius_m
    ]
    return nearby[:limit]


def insertion_pooling_match(
    routes: Dict[str, List[dict]],
    driver_zone_by_id: Dict[str, str],
    requests: pd.DataFrame,
    zone_distances: Dict[tuple, float],
    cost_table: Dict[Tuple[str, str], float],
    config: dict,
    vehicle_capacity: int = 4,
    max_detour_ratio: float = 1.2,
) -> List[dict]:
    """Ride-pooling mode: for each request, try inserting its pickup/dropoff
    into a nearby driver's current route at every capacity-and-order-valid
    position; take the insertion with the smallest added cost. Falls back
    to starting a fresh 1-passenger route on an idle driver (an empty
    route) if no pooled insertion is cheap enough (detour over
    `max_detour_ratio` versus that passenger's solo trip)."""
    candidate_radius_m = float(config["repositioning"]["candidate_radius_m"])
    candidate_limit = int(config["routing"]["candidate_driver_limit_per_request"])
    assignments = []
    for request in requests.itertuples():
        solo_cost = cost_table[(request.pickup_zone_id, request.destination_zone_id)]
        pickup_stop = {"type": "pickup", "zone_id": request.pickup_zone_id, "request_id": request.request_id}
        dropoff_stop = {"type": "dropoff", "zone_id": request.destination_zone_id, "request_id": request.request_id}

        best = None
        candidates = _nearby_candidate_drivers(
            routes, driver_zone_by_id, request.pickup_zone_id, zone_distances, candidate_radius_m, candidate_limit
        )
        for driver_id in candidates:
            stops = routes[driver_id]
            base_cost = _route_cost(stops, cost_table)
            for i, j in _feasible_insertions(stops, vehicle_capacity):
                candidate = stops[:i] + [pickup_stop] + stops[i:j] + [dropoff_stop] + stops[j:]
                delta = _route_cost(candidate, cost_table) - base_cost
                if delta > solo_cost * max_detour_ratio:
                    continue
                if best is None or delta < best["delta"]:
                    best = {"driver_id": driver_id, "delta": delta, "candidate": candidate}

        if best is not None:
            routes[best["driver_id"]] = best["candidate"]
            assignments.append(
                {
                    "driver_id": best["driver_id"],
                    "request_id": request.request_id,
                    "predicted_cost_minutes": round(best["delta"], 2),
                    "mode": "ride_pooling_insertion",
                }
            )
        else:
            assignments.append(
                {
                    "driver_id": None,
                    "request_id": request.request_id,
                    "predicted_cost_minutes": round(solo_cost, 2),
                    "mode": "ride_pooling_no_capacity",
                }
            )
    return assignments


def load_demo_inputs():
    config = load_config()
    zones = load_zones()
    full_zones = pd.DataFrame(json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8")))
    zone_distances = build_zone_distances(full_zones[["zone_id", "center_lat", "center_lng"]])
    zone_type_by_id = dict(zip(zones["zone_id"], zones["zone_type"]))

    drivers_path = PROJECT_ROOT / "data" / "generated" / "drivers_final.json"
    all_drivers = json.loads(drivers_path.read_text(encoding="utf-8"))
    idle_drivers = pd.DataFrame([d for d in all_drivers if d["status"] == "idle"])
    return config, zones, zone_distances, zone_type_by_id, idle_drivers


def build_synthetic_requests(zones: pd.DataFrame, rng: np.random.Generator, n: int) -> pd.DataFrame:
    zone_ids = zones["zone_id"].tolist()
    weights = zones["base_demand_weight"].to_numpy()
    weights = weights / weights.sum()
    pickups = rng.choice(zone_ids, size=n, p=weights)
    destinations = rng.choice(zone_ids, size=n, p=weights)
    return pd.DataFrame(
        {
            "request_id": [f"REQ{i:04d}" for i in range(n)],
            "pickup_zone_id": pickups,
            "destination_zone_id": destinations,
        }
    )


def run_demo(output_dir: Path) -> dict:
    config, zones, zone_distances, zone_type_by_id, idle_drivers = load_demo_inputs()
    cost_model = joblib.load(output_dir / "cost_model.joblib")
    rng = np.random.default_rng(int(config["random_seed"]))
    zone_ids = zones["zone_id"].tolist()

    context_normal = {"hour": 13, "day_of_week": 2, "is_holiday": False, "weather": "clear"}
    context_peak_rain = {"hour": 18, "day_of_week": 2, "is_holiday": False, "weather": "rain"}

    requests = build_synthetic_requests(zones, rng, n=40)

    cost_table_normal = build_zone_pair_cost_table(zone_ids, zone_distances, zone_type_by_id, cost_model, context_normal)
    hungarian_assignments = hungarian_match(idle_drivers, requests, cost_table_normal, config)

    cost_table_peak_rain = build_zone_pair_cost_table(
        zone_ids, zone_distances, zone_type_by_id, cost_model, context_peak_rain
    )
    driver_zone_by_id = dict(zip(idle_drivers["driver_id"], idle_drivers["zone_id"]))
    routes = {driver_id: [] for driver_id in driver_zone_by_id}
    pooling_assignments = insertion_pooling_match(
        routes, driver_zone_by_id, requests, zone_distances, cost_table_peak_rain, config
    )

    use_pooling_now = should_use_pooling("rain", 18, system_deficit=10, config=config)
    use_pooling_midday = should_use_pooling("clear", 13, system_deficit=10, config=config)

    summary = {
        "mode_trigger_examples": {
            "18h_rain": use_pooling_now,
            "13h_clear": use_pooling_midday,
        },
        "hungarian_1to1": {
            "requests": len(requests),
            "matched": len(hungarian_assignments),
            "avg_predicted_cost_minutes": round(
                float(np.mean([a["predicted_cost_minutes"] for a in hungarian_assignments])), 2
            )
            if hungarian_assignments
            else None,
        },
        "ride_pooling": {
            "requests": len(requests),
            "assigned": sum(1 for a in pooling_assignments if a["driver_id"] is not None),
            "unmatched_no_capacity": sum(1 for a in pooling_assignments if a["driver_id"] is None),
            "drivers_used": sum(1 for stops in routes.values() if stops),
            "drivers_serving_2plus_passengers": sum(
                1 for stops in routes.values() if len({s["request_id"] for s in stops}) >= 2
            ),
        },
    }
    pd.DataFrame(hungarian_assignments).to_csv(output_dir / "matching_hungarian_demo.csv", index=False)
    pd.DataFrame(pooling_assignments).to_csv(output_dir / "matching_pooling_demo.csv", index=False)
    (output_dir / "matching_engine_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo the Week 4 Matching Engine (Hungarian + ride-pooling)")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_demo(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
