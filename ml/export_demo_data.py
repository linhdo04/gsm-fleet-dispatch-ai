import argparse
import json
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np
import pandas as pd

from .common import (
    PROJECT_ROOT,
    add_holiday_feature,
    add_local_time_features,
    attach_weather,
    build_hourly_weather_lookup,
    load_config,
    load_demand_events,
    load_zones,
)
from simulator.validate_outputs import read_dataset
from .repositioning_suggester import build_zone_distances, suggest_round, train_or_load_model
from .matching_engine import build_synthetic_requests
from .matching_flow import RouteEstimator, ZoneState, handle_new_request
from .nlg_explainer import OpenAIExplainer
from .routing_client import GoogleRoutesClient, decode_polyline

# Frontend/src/mock/scenario.ts was built with fully synthetic numbers before
# any model existed. Now that Tuần 3/4 produced a real Acceptance Model and a
# real 56-day simulator run, this script re-derives every number the demo UI
# shows — one representative *real* historical tick per scenario condition —
# instead of the seeded-random generator. NLG explanation text calls
# `OpenAIExplainer` (`ml/nlg_explainer.py`) — real OpenAI API call when
# OPENAI_API_KEY is set, template fallback otherwise.

SCENARIO_CONDITIONS = {
    "normal": dict(hour_range=(12, 14), weather={"clear"}, weekend=False, holiday=False),
    "rain": dict(hour_range=(12, 14), weather={"rain", "heavy_rain"}, weekend=None, holiday=False),
    "peak": dict(hour_range=None, peak_hours=True, weather={"clear"}, weekend=False, holiday=False),
    "holiday": dict(hour_range=(12, 14), weather=None, weekend=None, holiday=True),
}


def _route_path(routes_client: GoogleRoutesClient, origin: tuple, dest: tuple) -> Optional[list]:
    """Toạ độ đường đi thật (đã decode encoded polyline) giữa 2 điểm, hoặc
    None nếu đang chạy fallback Haversine (không có GOOGLE_ROUTES_API_KEY)
    — frontend (MapView.tsx) chỉ vẽ đường minh hoạ nối thẳng khi None, để
    không giả vờ là route thực tế.

    Origin == destination (2 stop cùng zone, ví dụ 2 khách pickup cùng zone
    trong 1 route ghép chuyến) -> không gọi API: Google trả "duration": "0s"
    nhưng bỏ hẳn distanceMeters/polyline cho quãng đường 0m, không phải lỗi
    cần fallback — tự trả về đúng 1 điểm, không tốn quota API."""
    if origin[0] == dest[0] and origin[1] == dest[1]:
        return [list(origin)]
    result = routes_client.get_route(origin[0], origin[1], dest[0], dest[1])
    if result.is_fallback or not result.encoded_polyline:
        return None
    return [list(point) for point in decode_polyline(result.encoded_polyline)]


def _pooled_route_path(routes_client: GoogleRoutesClient, points: list) -> Optional[list]:
    """Nối các đoạn route thật giữa các stop liên tiếp thành 1 đường đi hoàn
    chỉnh. Chỉ 1 đoạn rơi vào fallback (thiếu key/lỗi API) là đủ để cả
    route trả về None — không trộn lẫn đoạn thật với đoạn minh hoạ, tránh
    đánh lừa frontend rằng cả đường là route thực tế."""
    if len(points) < 2:
        return None
    full_path: list = []
    for origin, dest in zip(points, points[1:]):
        segment = _route_path(routes_client, origin, dest)
        if segment is None:
            return None
        full_path.extend(segment[1:] if full_path else segment)
    return full_path


def _load_supply_with_context() -> pd.DataFrame:
    config = load_config()
    supply = read_dataset(PROJECT_ROOT / "data" / "generated" / "supply_snapshots")
    supply = add_local_time_features(supply, "timestamp", config)
    supply = add_holiday_feature(supply)
    demand_events = load_demand_events()
    weather_lookup = build_hourly_weather_lookup(demand_events, config)
    return attach_weather(supply, weather_lookup)


def _pick_hour_window(supply: pd.DataFrame, condition: dict, deficit_by_timestamp: pd.Series) -> pd.DataFrame:
    """Picks one real 5-minute tick matching the scenario condition. Deficit
    is genuinely near-zero at most individual ticks (300 drivers usually
    cover demand) and averaging a full hour washes out the interesting
    moments almost entirely — tried that first, every scenario came back
    with zero suggestions. So instead: among every tick that matches the
    condition, take the one with the highest real total deficit — still an
    actual historical moment, just a demo-worthy one rather than an
    arbitrary one (the equivalent of picking a good screenshot)."""
    ticks = supply.drop_duplicates(subset=["timestamp"]).copy()
    mask = pd.Series(True, index=ticks.index)
    if condition.get("peak_hours"):
        mask &= (ticks["hour"].between(7, 8)) | (ticks["hour"].between(17, 18))
    elif condition.get("hour_range"):
        lo, hi = condition["hour_range"]
        mask &= ticks["hour"].between(lo, hi - 1)
    if condition.get("weather"):
        mask &= ticks["weather"].isin(condition["weather"])
    if condition.get("weekend") is not None:
        mask &= ticks["is_weekend"] == condition["weekend"]
    if condition.get("holiday") is not None:
        mask &= ticks["is_holiday"] == condition["holiday"]
    matches = ticks[mask].copy()
    if matches.empty:
        raise ValueError(f"No real tick found for condition {condition}")
    matches["total_deficit"] = matches["timestamp"].map(deficit_by_timestamp).fillna(0.0)
    chosen = matches.sort_values("total_deficit", ascending=False).iloc[0]
    return chosen


def _driver_points_for_tick(
    zone_rows: pd.DataFrame, zones: pd.DataFrame, scenario_key: str, rng: np.random.Generator
) -> list:
    zone_center = {row.zone_id: (row.center_lat, row.center_lng) for row in zones.itertuples()}
    points = []
    counter = 0

    def add_dots(zone_id: str, count: int, status: str):
        nonlocal counter
        lat0, lng0 = zone_center[zone_id]
        for _ in range(int(count)):
            counter += 1
            lat_offset = (rng.random() - 0.5) * 0.012
            lng_offset = (rng.random() - 0.5) * 0.012
            points.append(
                {
                    "driver_id": f"{scenario_key[:1].upper()}{counter:04d}",
                    "zone_id": zone_id,
                    "lat": lat0 + lat_offset,
                    "lng": lng0 + lng_offset,
                    "battery_level": None,
                    "status": status,
                }
            )

    for row in zone_rows.itertuples():
        add_dots(row.zone_id, row.idle_drivers, "idle")
        add_dots(row.zone_id, row.repositioning_incoming, "incoming")
        add_dots(row.zone_id, row.trip_dropoff_incoming, "busy")
    return points


def _suggestions_for_tick(
    zone_rows: pd.DataFrame,
    zones: pd.DataFrame,
    zone_distances: Dict[tuple, float],
    model,
    config: dict,
    timestamp,
    scenario_key: str,
    explainer: OpenAIExplainer,
    routes_client: GoogleRoutesClient,
    limit: int = 5,
) -> list:
    """Real Acceptance Probability Model + real Repositioning Suggester
    (`ml/repositioning_suggester.py`), fed the actual historical deficit
    profile from this tick. The idle-driver *pool* still comes from
    `drivers_final.json` (the only individually-identified snapshot the
    simulator persists — see docs/week3_models.md) rather than this exact
    historical moment, so treat this as "what the Suggester recommends
    right now, facing a real deficit pattern representative of this
    condition" rather than a literal replay of that historical tick."""
    drivers_path = PROJECT_ROOT / "data" / "generated" / "drivers_final.json"
    all_drivers = json.loads(drivers_path.read_text(encoding="utf-8"))
    idle_drivers = [d for d in all_drivers if d["status"] == "idle"]
    for driver in idle_drivers:
        driver.setdefault("idle_minutes", 15.0)
        driver.setdefault("historical_acceptance_rate", 0.5)
        driver.setdefault("recent_suggestions", 0)

    zone_deficits = {
        row.zone_id: float(row.observed_deficit) for row in zone_rows.itertuples() if row.observed_deficit > 0
    }
    zone_center = {row.zone_id: (row.center_lat, row.center_lng) for row in zones.itertuples()}
    raw_suggestions = suggest_round(
        zone_deficits, idle_drivers, zone_distances, model, config, timestamp, zone_center
    )

    zone_name = dict(zip(zones["zone_id"], zones["name"])) if "name" in zones.columns else {}
    weather_label = {"clear": "trời quang", "cloudy": "nhiều mây", "rain": "mưa", "heavy_rain": "mưa to"}

    ranked = sorted(raw_suggestions, key=lambda s: zone_deficits.get(s["target_zone_id"], 0), reverse=True)[:limit]
    suggestions = []
    for s in ranked:
        target_deficit = zone_deficits.get(s["target_zone_id"], 0)
        from_name = zone_name.get(s["from_zone_id"], s["from_zone_id"])
        target_name = zone_name.get(s["target_zone_id"], s["target_zone_id"])
        from_point = zone_center[s["from_zone_id"]]
        to_point = zone_center[s["target_zone_id"]]
        suggestions.append(
            {
                "suggestion_id": f"S-{scenario_key}-{s['target_zone_id']}-{s['driver_id']}",
                "driver_id": s["driver_id"],
                "from_zone_id": s["from_zone_id"],
                "from_zone_name": from_name,
                "from": list(from_point),
                "target_zone_id": s["target_zone_id"],
                "target_zone_name": target_name,
                "to": list(to_point),
                "path": _route_path(routes_client, from_point, to_point),
                "acceptance_probability": s["p_accept"],
                "reason": f"deficit dự báo +{target_deficit:.1f} xe",
                "explanation": explainer.explain_suggestion(
                    target_zone_name=target_name,
                    target_deficit=target_deficit,
                    driver_id=s["driver_id"],
                    from_zone_name=from_name,
                    distance_m=s["distance_m"],
                    p_accept=s["p_accept"],
                ),
            }
        )
    return suggestions


def _matching_for_tick(
    full_zones: pd.DataFrame,
    zone_distances: Dict[tuple, float],
    zone_type_by_id: Dict[str, str],
    cost_model,
    config: dict,
    tick,
    zone_states: Dict[str, ZoneState],
    acceptance_model,
    rng: np.random.Generator,
    routes_client: GoogleRoutesClient,
    n_requests: int = 30,
) -> dict:
    """Runs the real cascade (`ml/matching_flow.py`, replaces the old
    Hungarian/`should_use_pooling` mode-switch from `ml/matching_engine.py`)
    request-by-request for a synthetic batch, fed the real hour/weather/
    holiday context of this scenario's tick plus the tick's real
    `zone_states` (so Step 3/4 of the cascade see the same deficit the map
    and KPI panel show). Each request independently resolves to one of 4
    actions — there is no longer a single global "mode" for the whole batch,
    so the payload reports an action breakdown instead of a `mode` field."""
    zone_name = dict(zip(full_zones["zone_id"], full_zones["name"]))
    zone_center = {row.zone_id: (row.center_lat, row.center_lng) for row in full_zones.itertuples()}
    zone_ids = full_zones["zone_id"].tolist()
    context = {
        "hour": int(tick["hour"]),
        "day_of_week": int(pd.Timestamp(str(tick["timestamp"])).dayofweek),
        "is_holiday": bool(tick["is_holiday"]),
        "weather": tick["weather"],
    }
    router = RouteEstimator(zone_distances, config["routing"]["fallback_road_distance_multiplier"], cost_model, zone_type_by_id, context)
    router.warm_cache(zone_ids)

    drivers_path = PROJECT_ROOT / "data" / "generated" / "drivers_final.json"
    all_drivers = json.loads(drivers_path.read_text(encoding="utf-8"))
    for driver in all_drivers:
        driver.setdefault("idle_minutes", 15.0)
        driver.setdefault("historical_acceptance_rate", 0.5)
        driver.setdefault("recent_suggestions", 0)
    drivers_by_id = {d["driver_id"]: d for d in all_drivers}
    idle_drivers = [d for d in all_drivers if d["status"] == "idle"]
    pooling_candidates = [d for d in all_drivers if d["status"] in {"idle", "busy"}][:60]

    requests = build_synthetic_requests(full_zones, rng, n_requests)

    routes_by_driver: Dict[str, list] = {}
    action_counts: Dict[str, int] = {}
    direct_assign_etas = []
    pooled_costs = []
    for row in requests.itertuples():
        request = {
            "request_id": row.request_id,
            "pickup_zone_id": row.pickup_zone_id,
            "destination_zone_id": row.destination_zone_id,
            "request_time": tick["timestamp"],
        }
        result = handle_new_request(
            request,
            zone_states,
            [d for d in idle_drivers if d["status"] == "idle"],
            pooling_candidates,
            routes_by_driver,
            drivers_by_id,
            router,
            acceptance_model,
            config,
            tick["timestamp"],
            context["weather"],
        )
        action_counts[result["action"]] = action_counts.get(result["action"], 0) + 1
        if result["action"] == "direct_assign":
            direct_assign_etas.append(result["eta_seconds"])
        elif result["action"] == "pooled_insertion":
            pooled_costs.append(result["cost"])

    pooled_routes = []
    for driver_id, stops in routes_by_driver.items():
        passenger_ids = {s.request_id for s in stops}
        if len(passenger_ids) < 2:
            continue
        total_distance_m = sum(zone_distances[(a.zone_id, b.zone_id)] * 1.3 for a, b in zip(stops, stops[1:]))
        pooled_routes.append(
            {
                "driver_id": driver_id,
                "passengers": len(passenger_ids),
                "total_distance_m": round(total_distance_m, 1),
                "path": _pooled_route_path(routes_client, [zone_center[s.zone_id] for s in stops]),
                "stops": [
                    {
                        "type": s.type,
                        "zone_id": s.zone_id,
                        "zone_name": zone_name.get(s.zone_id, s.zone_id),
                        "lat": zone_center[s.zone_id][0],
                        "lng": zone_center[s.zone_id][1],
                    }
                    for s in stops
                ],
            }
        )

    return {
        "requests": len(requests),
        "action_breakdown": action_counts,
        "avg_direct_assign_eta_seconds": round(float(np.mean(direct_assign_etas)), 1) if direct_assign_etas else None,
        "avg_pooled_insertion_cost": round(float(np.mean(pooled_costs)), 2) if pooled_costs else None,
        "pooled_routes": sorted(pooled_routes, key=lambda r: r["passengers"], reverse=True)[:5],
    }


def export_scenarios(output_dir: Path) -> Dict[str, dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    zones = load_zones()
    full_zones = pd.DataFrame(json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8")))
    zone_distances = build_zone_distances(full_zones[["zone_id", "center_lat", "center_lng"]])
    zone_type_by_id = dict(zip(zones["zone_id"], zones["zone_type"]))
    model = train_or_load_model(PROJECT_ROOT / "ml" / "artifacts")
    cost_model = joblib.load(PROJECT_ROOT / "ml" / "artifacts" / "cost_model.joblib")
    supply = _load_supply_with_context()
    rng = np.random.default_rng(int(config["random_seed"]))
    explainer = OpenAIExplainer()
    routes_client = GoogleRoutesClient(
        cache_path=output_dir / "google_routes_cache.json",
        cache_ttl_seconds=config["routing"]["zone_pair_cache_ttl_seconds"],
        fallback_road_distance_multiplier=config["routing"]["fallback_road_distance_multiplier"],
    )
    deficit_by_timestamp = (
        supply.assign(positive_deficit=supply["observed_deficit"].clip(lower=0))
        .groupby("timestamp")["positive_deficit"]
        .sum()
    )
    manifest = {}
    for scenario_key, condition in SCENARIO_CONDITIONS.items():
        tick = _pick_hour_window(supply, condition, deficit_by_timestamp)
        timestamp = tick["timestamp"]
        zone_rows = supply[supply["timestamp"] == timestamp]

        zone_states = [
            {
                "zone_id": row.zone_id,
                "idle_drivers": int(row.idle_drivers),
                "incoming_drivers": int(row.repositioning_incoming + row.trip_dropoff_incoming),
                "outgoing_drivers": int(row.outgoing_drivers),
                "predicted_supply": float(row.predicted_supply),
                "predicted_demand": int(row.actual_demand),
                "deficit": float(row.observed_deficit),
            }
            for row in zone_rows.itertuples()
        ]
        driver_points = _driver_points_for_tick(zone_rows, full_zones, scenario_key, rng)
        suggestions = _suggestions_for_tick(
            zone_rows, full_zones, zone_distances, model, config, timestamp, scenario_key, explainer, routes_client
        )
        zone_states_flow = {
            row.zone_id: ZoneState(
                zone_id=row.zone_id,
                predicted_demand=float(row.actual_demand),
                idle_drivers=int(row.idle_drivers),
                confirmed_incoming=int(row.repositioning_incoming + row.trip_dropoff_incoming),
                outgoing_drivers=int(row.outgoing_drivers),
            )
            for row in zone_rows.itertuples()
        }
        matching = _matching_for_tick(
            full_zones,
            zone_distances,
            zone_type_by_id,
            cost_model,
            config,
            tick,
            zone_states_flow,
            model,
            rng,
            routes_client,
        )

        payload = {
            "scenario": scenario_key,
            "source_tick": {
                "timestamp": str(timestamp),
                "weather": tick["weather"],
                "hour_local": int(tick["hour"]),
                "is_weekend": bool(tick["is_weekend"]),
                "is_holiday": bool(tick["is_holiday"]),
            },
            "zone_states": zone_states,
            "driver_points": driver_points,
            "suggestions": suggestions,
            "matching": matching,
        }
        (output_dir / f"scenario_{scenario_key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest[scenario_key] = payload["source_tick"]

    return manifest


def export_kpi(ab_test_dir: Path, output_dir: Path) -> list:
    """Reshape the real 10-seed A/B test result into the frontend's
    `KpiRow[]` shape, replacing report.md's placeholder estimate numbers."""
    agg = pd.read_csv(ab_test_dir / "ab_test_summary_multi_seed.csv").set_index("scenario")
    rows = [
        {
            "metric": "Thời gian chờ khách",
            "unit": "giây",
            "lowerIsBetter": True,
            "values": agg["avg_wait_seconds_mean"].round(1).to_dict(),
        },
        {
            "metric": "Tỷ lệ cuốc bị hủy",
            "unit": "%",
            "lowerIsBetter": True,
            "values": agg["cancellation_rate_pct_mean"].round(2).to_dict(),
        },
        {
            "metric": "Deadhead / tài xế",
            "unit": "km/xe",
            "lowerIsBetter": True,
            "values": (agg["deadhead_m_per_driver_mean"] / 1000).round(2).to_dict(),
        },
        {
            "metric": "Lệch chuẩn cung/cầu",
            "unit": "điểm",
            "lowerIsBetter": True,
            "values": agg["supply_demand_ratio_std_mean"].round(2).to_dict(),
        },
        {
            "metric": "Lượt điều xe / 7 ngày",
            "unit": "lượt",
            "lowerIsBetter": True,
            "values": agg["repositioned_drivers_mean"].round(0).to_dict(),
        },
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "kpi_real.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export real Tuần 3/4 results as static JSON for the frontend demo")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "frontend" / "public" / "data")
    parser.add_argument("--ab-test-dir", type=Path, default=PROJECT_ROOT / "data" / "ab_test_multiseed")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = export_scenarios(args.output)
    kpi_rows = export_kpi(args.ab_test_dir, args.output)
    print(json.dumps({"scenarios": manifest, "kpi_rows": len(kpi_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
