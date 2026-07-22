"""Luồng A (request mới) và Luồng B (tài xế idle) từ
`docs/business_design.md` — "Đặc tả luồng Matching & Repositioning".

Thay thế `ml/matching_engine.py` (Hungarian Algorithm cho 1-1 + insertion
heuristic bật/tắt theo mưa/giờ cao điểm): quyết định đó đã bị bỏ theo yêu cầu
của spec mới — không còn khái niệm "chế độ toàn cục", mỗi request tự chạy qua
cascade 4 bước (gán trực tiếp → chèn ghép chuyến → chờ xe incoming → kích
hoạt repositioning), và mỗi tài xế idle tự chạy qua cascade riêng (pin →
deficit tại chỗ → zone lân cận → soft-reserve).

Phạm vi: đây là phần logic nghiệp vụ (Business/AI sở hữu theo mục 7
`business_design.md`). Việc nối vào một event loop sống có khoá
đa luồng thật (`atomic update`, mục 4) là việc của Platform/Infra — module
này cung cấp đúng các hàm/state mà một event loop như vậy sẽ gọi, và được
kiểm chứng bằng unit test cho 3 ca biên nêu ở mục 5 việc-cần-làm, chứ không
tự dựng một message queue/threading thật.

`get_route()` (Google Routes API) chưa có API key trong môi trường này —
mọi ETA/khoảng cách dưới đây dùng Haversine × `fallback_road_distance_multiplier`
cộng `Cost Prediction Model` (Tuần 4) làm proxy, giống mọi chỗ khác trong dự án.
"""

from __future__ import annotations

import argparse
import json
import math
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np

from .routing_client import GoogleRoutesClient

import pandas as pd

from .acceptance_model import FEATURE_COLUMNS as ACCEPTANCE_FEATURE_COLUMNS
from .cost_model import FEATURE_COLUMNS as COST_FEATURE_COLUMNS

BASE_SPEED_M_PER_S = 7.0  # ~420 m/min, cùng hằng số dùng trong simulator/engine.py khi chưa có route API thật


# ---------------------------------------------------------------------------
# State — mục 9 (expected_pending_incoming) + mục 2.1/2.5 business_design.md
# ---------------------------------------------------------------------------


@dataclass
class ZoneState:
    zone_id: str
    predicted_demand: float
    idle_drivers: int = 0
    confirmed_incoming: int = 0
    outgoing_drivers: int = 0
    expected_pending_incoming: float = 0.0  # Σ p_accept của mọi soft-reserve đang "pending" cho zone này

    @property
    def expected_supply(self) -> float:
        return self.idle_drivers + self.confirmed_incoming + self.expected_pending_incoming - self.outgoing_drivers

    @property
    def expected_deficit(self) -> float:
        return self.predicted_demand - self.expected_supply


@dataclass
class Suggestion:
    suggestion_id: str
    driver_id: str
    target_zone_id: str
    acceptance_probability: float
    created_at: datetime
    ttl_seconds: int
    reserve_status: str = "pending"  # pending | accepted | rejected | expired | cancelled

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.ttl_seconds)


@dataclass
class RouteStop:
    type: str  # "pickup" | "dropoff"
    request_id: str
    zone_id: str


# ---------------------------------------------------------------------------
# Mục 1.5 — aging priority (chống đói khách)
# ---------------------------------------------------------------------------


def aging_priority(request_time: datetime, now: datetime, config: dict) -> float:
    matching_cfg = config["matching"]
    waited_seconds = (now - request_time).total_seconds()
    base = -waited_seconds  # số nhỏ hơn (âm hơn) = ưu tiên hơn khi sort tăng dần
    if waited_seconds > matching_cfg["urgent_threshold_seconds"]:
        base -= matching_cfg["urgent_priority_boost"]
    return base


# ---------------------------------------------------------------------------
# Mục 1.4 — cost function cho chèn tuyến ghép chuyến
# ---------------------------------------------------------------------------


@dataclass
class InsertionCandidate:
    driver_id: str
    pickup_index: int
    dropoff_index: int
    wait_time_seconds: float
    extra_travel_time_existing_passengers_seconds: float
    occupied_seats_after_match: int
    detour_ratio: float
    battery_feasible: bool
    cost: float


def compute_cost(
    wait_time_seconds: float,
    extra_travel_time_existing_passengers_seconds: float,
    occupied_seats_after_match: int,
    vehicle_capacity: int,
    detour_ratio: float,
    target_detour_ratio: float,
    config: dict,
) -> float:
    weights = config["matching"]["cost_weights"]
    fill_rate_bonus = occupied_seats_after_match / vehicle_capacity
    detour_penalty = max(0.0, detour_ratio - target_detour_ratio)
    return (
        weights["w1_wait_time"] * wait_time_seconds
        + weights["w2_existing_passenger_extra_time"] * extra_travel_time_existing_passengers_seconds
        + weights["w3_fill_rate"] * (1.0 - fill_rate_bonus)
        + weights["w4_detour_penalty"] * detour_penalty
    )


# ---------------------------------------------------------------------------
# Haversine + Cost Prediction Model proxy cho get_route()/predicted_segment_cost()
# ---------------------------------------------------------------------------


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_zone_distances(zones: pd.DataFrame) -> Dict[Tuple[str, str], float]:
    records = zones.to_dict("records")
    return {
        (a["zone_id"], b["zone_id"]): haversine_m(a["center_lat"], a["center_lng"], b["center_lat"], b["center_lng"])
        for a in records
        for b in records
    }


class RouteEstimator:
    """`get_route()` thay thế — Haversine × hệ số đường vòng làm khoảng cách,
    Cost Prediction Model (nếu có) hoặc tốc độ trung bình cố định làm thời
    gian, đúng cơ chế fallback mục 2.8 `business_design.md` (không có
    Google Routes API key thật trong môi trường này nên luôn `is_fallback=True`)."""

    def __init__(
        self,
        zone_distances: Dict[Tuple[str, str], float],
        road_distance_multiplier: float,
        cost_model=None,
        zone_type_by_id: Optional[Dict[str, str]] = None,
        context: Optional[dict] = None,
    ):
        self.zone_distances = zone_distances
        self.road_distance_multiplier = road_distance_multiplier
        self.cost_model = cost_model
        self.zone_type_by_id = zone_type_by_id or {}
        self.context = context or {}
        self._duration_cache: Dict[Tuple[str, str], float] = {}

    def distance_m(self, from_zone_id: str, to_zone_id: str) -> float:
        return self.zone_distances[(from_zone_id, to_zone_id)] * self.road_distance_multiplier

    def warm_cache(self, zone_ids: List[str]) -> None:
        """Same fix as `ml/matching_engine.py`'s `build_zone_pair_cost_table`:
        a fixed context has only `zone_count^2` distinct durations, computed
        here in one batched `predict()` call. Without this,
        `generate_valid_insertions`'s nested candidate×position×segment
        loops call `cost_model.predict()` one row at a time and the demo
        never finishes (hit the same 180s timeout matching_engine.py did on
        its first version)."""
        if self.cost_model is None:
            return
        pairs = [(a, b) for a in zone_ids for b in zone_ids if (a, b) not in self._duration_cache]
        if not pairs:
            return
        distances = [self.zone_distances[pair] * self.road_distance_multiplier for pair in pairs]
        frame = pd.DataFrame(
            {
                "distance_m": distances,
                "hour": self.context.get("hour", 12),
                "day_of_week": self.context.get("day_of_week", 2),
                "is_weekend": int(self.context.get("day_of_week", 2) >= 5),
                "is_holiday": int(self.context.get("is_holiday", False)),
                "weather": self.context.get("weather", "clear"),
                "origin_zone_type": [self.zone_type_by_id.get(a, "residential") for a, _ in pairs],
                "destination_zone_type": [self.zone_type_by_id.get(b, "residential") for _, b in pairs],
            }
        )
        for col in ["weather", "origin_zone_type", "destination_zone_type"]:
            frame[col] = frame[col].astype("category")
        predicted_minutes = self.cost_model.predict(frame[COST_FEATURE_COLUMNS])
        for pair, minutes in zip(pairs, predicted_minutes):
            self._duration_cache[pair] = float(minutes) * 60.0

    def duration_seconds(self, from_zone_id: str, to_zone_id: str) -> float:
        cached = self._duration_cache.get((from_zone_id, to_zone_id))
        if cached is not None:
            return cached
        distance_m = self.distance_m(from_zone_id, to_zone_id)
        if self.cost_model is None:
            return distance_m / BASE_SPEED_M_PER_S
        frame = pd.DataFrame(
            [
                {
                    "distance_m": distance_m,
                    "hour": self.context.get("hour", 12),
                    "day_of_week": self.context.get("day_of_week", 2),
                    "is_weekend": int(self.context.get("day_of_week", 2) >= 5),
                    "is_holiday": int(self.context.get("is_holiday", False)),
                    "weather": self.context.get("weather", "clear"),
                    "origin_zone_type": self.zone_type_by_id.get(from_zone_id, "residential"),
                    "destination_zone_type": self.zone_type_by_id.get(to_zone_id, "residential"),
                }
            ]
        )
        for col in ["weather", "origin_zone_type", "destination_zone_type"]:
            frame[col] = frame[col].astype("category")
        duration = float(self.cost_model.predict(frame[COST_FEATURE_COLUMNS])[0]) * 60.0
        self._duration_cache[(from_zone_id, to_zone_id)] = duration
        return duration


# ---------------------------------------------------------------------------
# Mục 2 — find_and_reserve_driver_for_zone: dùng chung cho Luồng A Step 4 và
# Luồng B Step 3-4 (mục 4 "Điểm nối giữa 2 luồng")
# ---------------------------------------------------------------------------


def rank_by_p_accept(
    candidates: List[dict],
    target_zone_id: str,
    target_deficit: float,
    timestamp: datetime,
    router: RouteEstimator,
    acceptance_model,
) -> pd.DataFrame:
    rows = []
    for driver in candidates:
        distance_m = router.distance_m(driver["zone_id"], target_zone_id)
        rows.append(
            {
                "driver_id": driver["driver_id"],
                "from_zone_id": driver["zone_id"],
                "distance_m": distance_m,
                "battery_percent": driver["battery_percent"],
                "idle_minutes": driver.get("idle_minutes", 15.0),
                "historical_acceptance_rate": driver.get("historical_acceptance_rate", 0.5),
                "recent_suggestions": driver.get("recent_suggestions", 0),
                "target_deficit": target_deficit,
                "hour": timestamp.hour,
                "is_weekend": int(timestamp.weekday() >= 5),
            }
        )
    frame = pd.DataFrame(rows)
    frame["p_accept"] = acceptance_model.predict_proba(frame[ACCEPTANCE_FEATURE_COLUMNS])[:, 1]
    return frame.sort_values("p_accept", ascending=False).reset_index(drop=True)


def find_and_reserve_driver_for_zone(
    target_zone_id: str,
    zone_states: Dict[str, ZoneState],
    candidate_drivers: List[dict],
    drivers_by_id: Dict[str, dict],
    router: RouteEstimator,
    acceptance_model,
    config: dict,
    timestamp: datetime,
) -> Optional[Suggestion]:
    """Chỉ tài xế `idle` mới được tạo reservation mới (mục 8, bất biến cuối).
    Dùng chung bởi cả 2 luồng: Luồng A Step 4 gọi với `candidate_drivers` là
    toàn bộ idle driver trong bán kính (tìm ứng viên tốt nhất cho 1 zone
    đang thiếu), Luồng B Step 3-4 gọi với `candidate_drivers = [driver]`
    (chỉ đánh giá đúng 1 tài xế đang được xét) — cùng một hàm, không viết
    2 lần logic soft-reserve như mục 4 yêu cầu."""
    zone_state = zone_states[target_zone_id]
    still_needed = zone_state.expected_deficit
    if still_needed <= 0:
        return None

    idle_only = [d for d in candidate_drivers if drivers_by_id[d["driver_id"]]["status"] == "idle"]
    if not idle_only:
        return None

    ranked = rank_by_p_accept(idle_only, target_zone_id, still_needed, timestamp, router, acceptance_model)
    best = ranked.iloc[0]
    p_accept = float(best["p_accept"])

    suggestion = Suggestion(
        suggestion_id=f"S-{uuid.uuid4().hex[:8]}",
        driver_id=best["driver_id"],
        target_zone_id=target_zone_id,
        acceptance_probability=p_accept,
        created_at=timestamp,
        ttl_seconds=config["repositioning"]["soft_reserve_ttl_seconds"],
    )
    zone_state.expected_pending_incoming += p_accept
    drivers_by_id[suggestion.driver_id]["status"] = "reserved"
    return suggestion


def on_suggestion_accepted(suggestion: Suggestion, zone_states: Dict[str, ZoneState], drivers_by_id: Dict[str, dict]) -> None:
    zone_state = zone_states[suggestion.target_zone_id]
    zone_state.expected_pending_incoming -= suggestion.acceptance_probability
    zone_state.confirmed_incoming += 1
    suggestion.reserve_status = "accepted"
    driver = drivers_by_id[suggestion.driver_id]
    driver["status"] = "incoming"
    driver["destination_zone_id"] = suggestion.target_zone_id


def on_suggestion_resolved_without_move(
    suggestion: Suggestion,
    zone_states: Dict[str, ZoneState],
    drivers_by_id: Dict[str, dict],
    reason: str,
) -> None:
    """`reason` ∈ {rejected, expired, cancelled} — mục 2.4: không cộng vào
    `confirmed_incoming` vì tài xế chưa từng được xác nhận đang tới zone."""
    assert reason in {"rejected", "expired", "cancelled"}
    zone_state = zone_states[suggestion.target_zone_id]
    zone_state.expected_pending_incoming -= suggestion.acceptance_probability
    suggestion.reserve_status = reason
    drivers_by_id[suggestion.driver_id]["status"] = "idle"


# ---------------------------------------------------------------------------
# Luồng B — xử lý xe idle
# ---------------------------------------------------------------------------


def pick_best_target_zone(
    candidate_zone_ids: List[str],
    driver: dict,
    zone_states: Dict[str, ZoneState],
    router: RouteEstimator,
) -> Optional[str]:
    ranked = []
    for zone_id in candidate_zone_ids:
        zone_state = zone_states[zone_id]
        still_needed = zone_state.expected_deficit
        if still_needed <= 0:
            continue  # đã đủ xe pending -> chống herding (mục 4)
        duration_seconds = router.duration_seconds(driver["zone_id"], zone_id)
        score = still_needed / max(duration_seconds, 1.0)
        ranked.append((zone_id, score))
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[1])[0]


def find_nearest_charging_station(
    driver_zone_id: str,
    charging_stations: List[dict],
    zone_center_by_id: Dict[str, Tuple[float, float]],
    routes_client,
) -> Optional[dict]:
    """`data/charging_stations.json` (8 trạm, farthest-point sampling trên 30
    zone — xem `data/generate_charging_stations.py`) × `GoogleRoutesClient`
    (`ml/routing_client.py`) cho khoảng cách/ETA thật (hoặc fallback Haversine
    có nhãn `is_fallback` rõ ràng nếu không có API key)."""
    if not charging_stations:
        return None
    driver_lat, driver_lng = zone_center_by_id[driver_zone_id]
    best = None
    for station in charging_stations:
        route = routes_client.get_route(driver_lat, driver_lng, station["lat"], station["lng"])
        if best is None or route.distance_m < best["distance_m"]:
            best = {
                "station_id": station["station_id"],
                "name": station["name"],
                "distance_m": round(route.distance_m, 1),
                "duration_seconds": round(route.duration_seconds, 1),
                "is_fallback": route.is_fallback,
            }
    return best


def handle_idle_driver(
    driver: dict,
    zone_states: Dict[str, ZoneState],
    drivers_by_id: Dict[str, dict],
    neighbor_zone_ids: List[str],
    router: RouteEstimator,
    acceptance_model,
    config: dict,
    timestamp: datetime,
    charging_stations: Optional[List[dict]] = None,
    zone_center_by_id: Optional[Dict[str, Tuple[float, float]]] = None,
    routes_client=None,
) -> dict:
    battery_cfg = config["battery"]
    low_battery = driver["battery_percent"] < battery_cfg["critical_battery_threshold_percent"] or (
        driver["battery_percent"] < battery_cfg["low_battery_threshold_percent"]
    )
    if low_battery:
        forced = driver["battery_percent"] < battery_cfg["critical_battery_threshold_percent"]
        result = {"action": "route_to_charger", "forced": forced}
        if charging_stations and zone_center_by_id and routes_client:
            result["nearest_station"] = find_nearest_charging_station(
                driver["zone_id"], charging_stations, zone_center_by_id, routes_client
            )
        return result

    zone_id = driver["zone_id"]
    if zone_states[zone_id].expected_deficit > 0:
        return {"action": "stay_idle", "reason": "own_zone_still_short"}

    candidate_zone_ids = [z for z in neighbor_zone_ids if zone_states[z].expected_deficit > 0]
    if not candidate_zone_ids:
        return {"action": "stay_idle", "reason": "no_deficit_neighbor"}

    target_zone_id = pick_best_target_zone(candidate_zone_ids, driver, zone_states, router)
    if target_zone_id is None:
        return {"action": "stay_idle", "reason": "neighbors_already_covered"}

    suggestion = find_and_reserve_driver_for_zone(
        target_zone_id, zone_states, [driver], drivers_by_id, router, acceptance_model, config, timestamp
    )
    if suggestion is None:
        return {"action": "stay_idle", "reason": "target_covered_between_pick_and_reserve"}
    return {"action": "suggested", "suggestion": suggestion}


# ---------------------------------------------------------------------------
# Luồng A — xử lý request mới
# ---------------------------------------------------------------------------


def satisfies_hard_constraints(
    detour_ratio: float,
    pickup_eta_seconds: float,
    occupied_seats_after_match: int,
    vehicle_capacity: int,
    pickup_before_dropoff_ok: bool,
    battery_feasible: bool,
    config: dict,
    weather: str,
) -> bool:
    detour_cfg = config["matching"]["max_detour_ratio"]
    eta_cfg = config["matching"]["pickup_eta_max_minutes"]
    max_detour = detour_cfg["rain"] if weather in {"rain", "heavy_rain", "storm"} else detour_cfg["default"]
    max_eta_seconds = (eta_cfg["rain"] if weather in {"rain", "heavy_rain", "storm"} else eta_cfg["default"]) * 60
    return (
        occupied_seats_after_match <= vehicle_capacity
        and pickup_before_dropoff_ok
        and pickup_eta_seconds <= max_eta_seconds
        and detour_ratio <= max_detour
        and battery_feasible
    )


def feasible_insertion_positions(stops: List[RouteStop], capacity: int):
    """Mọi (pickup_index, dropoff_index) giữ tuyến hợp lệ: pickup luôn trước
    dropoff của chính nó, số khách trên xe không vượt capacity tại bất kỳ
    điểm nào."""
    onboard = 0
    onboard_by_position = [0]
    for stop in stops:
        onboard += 1 if stop.type == "pickup" else -1
        onboard_by_position.append(onboard)
    n = len(stops)
    for i in range(n + 1):
        if onboard_by_position[i] >= capacity:
            continue
        for j in range(i, n + 1):
            yield i, j


def _route_duration_seconds(stops: List[RouteStop], router: RouteEstimator) -> float:
    if len(stops) < 2:
        return 0.0
    return sum(router.duration_seconds(a.zone_id, b.zone_id) for a, b in zip(stops, stops[1:]))


def _battery_feasible(driver: dict, added_distance_m: float, config: dict) -> bool:
    """Xấp xỉ mức pin tiêu hao — cùng hệ số 0,32%/km dùng trong
    `simulator/engine.py` (`energy_percent`) — rồi so với ngưỡng dự trữ tối
    thiểu cho 1 chuyến."""
    consumed_percent = (added_distance_m / 1000.0) * 0.32
    remaining = driver["battery_percent"] - consumed_percent
    return remaining >= config["battery"]["minimum_trip_reserve_percent"]


def generate_valid_insertions(
    request: dict,
    pooling_candidates: List[dict],
    routes_by_driver: Dict[str, List[RouteStop]],
    router: RouteEstimator,
    config: dict,
    weather: str,
) -> List[InsertionCandidate]:
    vehicle_capacity = config["matching"]["vehicle_capacity"]
    solo_duration = router.duration_seconds(request["pickup_zone_id"], request["destination_zone_id"])
    pickup_stop = RouteStop("pickup", request["request_id"], request["pickup_zone_id"])
    dropoff_stop = RouteStop("dropoff", request["request_id"], request["destination_zone_id"])

    valid: List[InsertionCandidate] = []
    for driver in pooling_candidates:
        stops = routes_by_driver.get(driver["driver_id"], [])
        base_duration = _route_duration_seconds(stops, router)
        pickup_eta_seconds = router.duration_seconds(driver["zone_id"], request["pickup_zone_id"])

        for i, j in feasible_insertion_positions(stops, vehicle_capacity):
            candidate_stops = stops[:i] + [pickup_stop] + stops[i:j] + [dropoff_stop] + stops[j:]
            new_duration = _route_duration_seconds(candidate_stops, router)
            extra_total = new_duration - base_duration
            wait_time_seconds = pickup_eta_seconds
            extra_for_existing = max(0.0, extra_total - wait_time_seconds)

            new_passenger_travel_time = _route_duration_seconds(candidate_stops[i : j + 2], router) or solo_duration
            detour_ratio = max(0.0, (new_passenger_travel_time / max(solo_duration, 1.0)) - 1.0)

            added_distance_m = router.distance_m(driver["zone_id"], request["pickup_zone_id"])
            battery_feasible = _battery_feasible(driver, added_distance_m, config)
            occupied_after = sum(1 for s in candidate_stops[: i + 1] if s.type == "pickup") - sum(
                1 for s in candidate_stops[: i + 1] if s.type == "dropoff"
            ) + 1

            if not satisfies_hard_constraints(
                detour_ratio,
                wait_time_seconds,
                len({s.request_id for s in candidate_stops}),
                vehicle_capacity,
                True,  # feasible_insertion_positions đã đảm bảo thứ tự pickup<dropoff
                battery_feasible,
                config,
                weather,
            ):
                continue

            cost = compute_cost(
                wait_time_seconds,
                extra_for_existing,
                len({s.request_id for s in candidate_stops}),
                vehicle_capacity,
                detour_ratio,
                config["matching"]["max_detour_ratio"]["rain" if weather in {"rain", "heavy_rain", "storm"} else "default"],
                config,
            )
            valid.append(
                InsertionCandidate(
                    driver_id=driver["driver_id"],
                    pickup_index=i,
                    dropoff_index=j,
                    wait_time_seconds=wait_time_seconds,
                    extra_travel_time_existing_passengers_seconds=extra_for_existing,
                    occupied_seats_after_match=len({s.request_id for s in candidate_stops}),
                    detour_ratio=detour_ratio,
                    battery_feasible=battery_feasible,
                    cost=cost,
                )
            )
    return valid


def handle_new_request(
    request: dict,
    zone_states: Dict[str, ZoneState],
    idle_drivers: List[dict],
    pooling_candidates: List[dict],
    routes_by_driver: Dict[str, List[RouteStop]],
    drivers_by_id: Dict[str, dict],
    router: RouteEstimator,
    acceptance_model,
    config: dict,
    timestamp: datetime,
    weather: str,
) -> dict:
    """Luồng A đầy đủ — mục 1.2 `business_design.md`. Trả về dict mô tả
    hành động đã xảy ra để caller (simulator hoặc unit test) cập nhật state
    ngoài (driver.status, request.status, hàng đợi...)."""
    target_zone_id = request["pickup_zone_id"]
    eta_fast_threshold = config["matching"]["eta_fast_threshold_seconds"]

    # ---- STEP 1: xe idle rất gần? ----
    nearby_idle = sorted(
        (d for d in idle_drivers if d["status"] == "idle"),
        key=lambda d: router.distance_m(d["zone_id"], target_zone_id),
    )[:5]
    for driver in nearby_idle:
        eta_seconds = router.duration_seconds(driver["zone_id"], target_zone_id)
        if eta_seconds <= eta_fast_threshold:
            driver["status"] = "busy"
            return {"action": "direct_assign", "driver_id": driver["driver_id"], "eta_seconds": eta_seconds}

    # ---- STEP 2: chèn vào xe busy/pooling? ----
    valid_insertions = generate_valid_insertions(request, pooling_candidates, routes_by_driver, router, config, weather)
    if valid_insertions:
        best = min(valid_insertions, key=lambda c: c.cost)
        stops = routes_by_driver.setdefault(best.driver_id, [])
        pickup_stop = RouteStop("pickup", request["request_id"], request["pickup_zone_id"])
        dropoff_stop = RouteStop("dropoff", request["request_id"], request["destination_zone_id"])
        routes_by_driver[best.driver_id] = (
            stops[: best.pickup_index] + [pickup_stop] + stops[best.pickup_index : best.dropoff_index]
            + [dropoff_stop] + stops[best.dropoff_index :]
        )
        return {"action": "pooled_insertion", "driver_id": best.driver_id, "cost": best.cost}

    # ---- STEP 3: xe incoming đã đủ bù? ----
    zone_state = zone_states[target_zone_id]
    if zone_state.expected_deficit <= 0:
        return {
            "action": "queued_waiting_for_incoming",
            "priority": aging_priority(request["request_time"], timestamp, config),
        }

    # ---- STEP 4: kích hoạt Repositioning Suggester ----
    suggestion = find_and_reserve_driver_for_zone(
        target_zone_id, zone_states, idle_drivers, drivers_by_id, router, acceptance_model, config, timestamp
    )
    return {
        "action": "queued_pending_reposition",
        "suggestion": suggestion,
        "priority": aging_priority(request["request_time"], timestamp, config),
    }


# ---------------------------------------------------------------------------
# Demo trên dữ liệu thật — cùng quy ước với các module ml/*.py khác (Tuần 3-4):
# tái dùng fleet snapshot cuối run (drivers_final.json) + model đã train,
# không phải dữ liệu bịa.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _build_demo_zone_states(zones, idle_drivers: List[dict]) -> Dict[str, ZoneState]:
    idle_counts = Counter(d["zone_id"] for d in idle_drivers)
    weights = zones["base_demand_weight"].to_numpy()
    mean_weight = weights.mean()
    zone_states = {}
    for zone_id, weight in zip(zones["zone_id"], weights):
        # cùng công thức deficit-demo dùng ở ml/repositioning_suggester.py
        # (load_demo_scenario): zone có base_demand_weight trên trung bình
        # được coi là đang có áp lực cầu cao hơn cho kịch bản demo.
        predicted_demand = round(float(weight) * 20.0, 2) if weight > mean_weight else round(float(weight) * 6.0, 2)
        zone_states[zone_id] = ZoneState(
            zone_id=zone_id, predicted_demand=predicted_demand, idle_drivers=idle_counts.get(zone_id, 0)
        )
    return zone_states


def run_demo(output_dir: Path) -> dict:
    from .common import load_config, load_zones

    config = load_config()
    zones = load_zones()
    full_zones = pd.DataFrame(json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8")))
    zone_distances = build_zone_distances(full_zones[["zone_id", "center_lat", "center_lng"]])
    zone_type_by_id = dict(zip(zones["zone_id"], zones["zone_type"]))
    zone_ids = zones["zone_id"].tolist()

    cost_model = joblib.load(output_dir / "cost_model.joblib")
    acceptance_model = joblib.load(output_dir / "acceptance_model.joblib")
    context = {"hour": 18, "day_of_week": 2, "is_holiday": False, "weather": "clear"}
    router = RouteEstimator(
        zone_distances, config["routing"]["fallback_road_distance_multiplier"], cost_model, zone_type_by_id, context
    )
    router.warm_cache(zone_ids)

    all_drivers = json.loads((PROJECT_ROOT / "data" / "generated" / "drivers_final.json").read_text(encoding="utf-8"))
    for driver in all_drivers:
        driver.setdefault("idle_minutes", 15.0)
        driver.setdefault("historical_acceptance_rate", 0.5)
        driver.setdefault("recent_suggestions", 0)
    drivers_by_id = {d["driver_id"]: d for d in all_drivers}
    idle_drivers = [d for d in all_drivers if d["status"] == "idle"]

    zone_states = _build_demo_zone_states(zones, idle_drivers)
    timestamp = datetime.now(timezone.utc)

    charging_stations = json.loads((PROJECT_ROOT / "data" / "charging_stations.json").read_text(encoding="utf-8"))
    zone_center_by_id = {row.zone_id: (row.center_lat, row.center_lng) for row in full_zones.itertuples()}
    routes_client = GoogleRoutesClient(
        cache_path=output_dir / "google_routes_cache.json",
        cache_ttl_seconds=config["routing"]["zone_pair_cache_ttl_seconds"],
        fallback_road_distance_multiplier=config["routing"]["fallback_road_distance_multiplier"],
    )

    # ---- Luồng B: mọi tài xế idle đi qua handle_idle_driver một lượt ----
    radius_m = config["repositioning"]["candidate_radius_m"]
    flow_b_actions = Counter()
    charging_routed = 0
    for driver in list(idle_drivers):
        if driver["status"] != "idle":
            continue  # có thể đã bị 1 suggestion trước đó chuyển sang "reserved"
        neighbor_ids = [z for z in zone_ids if zone_distances[(driver["zone_id"], z)] <= radius_m]
        result = handle_idle_driver(
            driver,
            zone_states,
            drivers_by_id,
            neighbor_ids,
            router,
            acceptance_model,
            config,
            timestamp,
            charging_stations,
            zone_center_by_id,
            routes_client,
        )
        flow_b_actions[result["action"]] += 1
        if result["action"] == "route_to_charger" and result.get("nearest_station"):
            charging_routed += 1

    # ---- Luồng A: batch request tổng hợp, cùng phân bố theo base_demand_weight ----
    rng = np.random.default_rng(int(config["random_seed"]))
    weights = zones["base_demand_weight"].to_numpy()
    weights = weights / weights.sum()
    n_requests = 25
    pickups = rng.choice(zone_ids, size=n_requests, p=weights)
    destinations = rng.choice(zone_ids, size=n_requests, p=weights)
    routes_by_driver: Dict[str, List[RouteStop]] = {}
    pooling_candidates = [d for d in all_drivers if d["status"] in {"idle", "busy"}][:60]

    flow_a_actions = Counter()
    for i in range(n_requests):
        request = {
            "request_id": f"REQ{i:04d}",
            "pickup_zone_id": pickups[i],
            "destination_zone_id": destinations[i],
            "request_time": timestamp,
        }
        still_idle = [d for d in idle_drivers if d["status"] == "idle"]
        result = handle_new_request(
            request,
            zone_states,
            still_idle,
            pooling_candidates,
            routes_by_driver,
            drivers_by_id,
            router,
            acceptance_model,
            config,
            timestamp,
            context["weather"],
        )
        flow_a_actions[result["action"]] += 1

    summary = {
        "flow_b_handle_idle_driver": dict(flow_b_actions),
        "flow_a_handle_new_request": dict(flow_a_actions),
        "zones_still_in_deficit_after_flow_b": sum(1 for zs in zone_states.values() if zs.expected_deficit > 0),
        "pooled_routes_active": sum(1 for stops in routes_by_driver.values() if len({s.request_id for s in stops}) >= 2),
        "drivers_routed_to_nearest_charging_station": charging_routed,
        "routing_provider": "google_routes" if routes_client.api_key else "haversine_fallback (no GOOGLE_ROUTES_API_KEY)",
    }
    (output_dir / "matching_flow_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo Luồng A/B (matching_flow.py) trên dữ liệu thật")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_demo(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
