import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import pandas as pd

from .acceptance_model import FEATURE_COLUMNS as ACCEPTANCE_FEATURE_COLUMNS
from .common import PROJECT_ROOT, load_config, load_zones


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_zone_distances(zones: pd.DataFrame) -> Dict[tuple, float]:
    records = zones.to_dict("records")
    distances = {}
    for source in records:
        for target in records:
            distances[(source["zone_id"], target["zone_id"])] = _haversine_m(
                source["center_lat"], source["center_lng"], target["center_lat"], target["center_lng"]
            )
    return distances


def rank_candidates(
    candidates: List[dict],
    target_zone_id: str,
    target_deficit: float,
    timestamp: datetime,
    zone_distances: Dict[tuple, float],
    model,
) -> pd.DataFrame:
    """Score idle drivers with the trained Acceptance Probability Model and
    return them ranked by p_accept, highest first — the ranking step that
    replaces plain nearest-distance in report.md's Tuần 3 pseudocode."""
    rows = []
    for driver in candidates:
        distance_m = zone_distances[(driver["zone_id"], target_zone_id)] * 1.3
        rows.append(
            {
                "driver_id": driver["driver_id"],
                "from_zone_id": driver["zone_id"],
                "distance_m": distance_m,
                "battery_percent": driver["battery_percent"],
                "idle_minutes": driver.get("idle_minutes", 0.0),
                "historical_acceptance_rate": driver.get("historical_acceptance_rate", 0.5),
                "recent_suggestions": driver.get("recent_suggestions", 0),
                "target_deficit": target_deficit,
                "hour": timestamp.hour,
                "is_weekend": int(timestamp.weekday() >= 5),
            }
        )
    frame = pd.DataFrame(rows)
    frame["p_accept"] = model.predict_proba(frame[ACCEPTANCE_FEATURE_COLUMNS])[:, 1]
    return frame.sort_values("p_accept", ascending=False).reset_index(drop=True)


def suggest_round(
    zone_deficits: Dict[str, float],
    idle_drivers: List[dict],
    zone_distances: Dict[tuple, float],
    model,
    config: dict,
    timestamp: datetime,
) -> List[dict]:
    """One repositioning round across every zone with deficit > 0, highest
    deficit first. Implements the soft-reserve loop from report.md Tuần 3:
    after each driver is suggested, the *expected* remaining deficit is
    recomputed (a driver only reduces it by p_accept, not by a guaranteed 1 —
    a suggestion is not a confirmed trip) and the zone stops asking for more
    once the expected deficit is covered."""
    candidate_radius = float(config["repositioning"]["candidate_radius_m"])
    min_battery = float(config["battery"]["minimum_trip_reserve_percent"])
    used_driver_ids = set()
    suggestions = []

    ordered_zones = sorted(
        (item for item in zone_deficits.items() if item[1] > 0), key=lambda item: item[1], reverse=True
    )
    for target_zone_id, deficit in ordered_zones:
        remaining = deficit
        while remaining > 0:
            candidates = [
                driver
                for driver in idle_drivers
                if driver["driver_id"] not in used_driver_ids
                and driver["zone_id"] != target_zone_id  # already there — not a repositioning move
                and zone_distances[(driver["zone_id"], target_zone_id)] <= candidate_radius
                and driver["battery_percent"] >= min_battery
            ]
            if not candidates:
                break
            ranked = rank_candidates(candidates, target_zone_id, remaining, timestamp, zone_distances, model)
            best = ranked.iloc[0]
            used_driver_ids.add(best["driver_id"])
            p_accept = float(best["p_accept"])
            suggestions.append(
                {
                    "driver_id": best["driver_id"],
                    "from_zone_id": best["from_zone_id"],
                    "target_zone_id": target_zone_id,
                    "distance_m": round(float(best["distance_m"]), 1),
                    "p_accept": round(p_accept, 4),
                }
            )
            # soft-reserve: expected_pending_incoming[target_zone] += p_accept, recompute immediately
            remaining -= p_accept
    return suggestions


def load_demo_scenario(zones: pd.DataFrame):
    """The fixed scenario shared by every Tuần 3/4 comparison: the actual
    end-of-run fleet snapshot (data/generated/drivers_final.json) against a
    synthetic deficit profile derived from each zone's base_demand_weight.
    Kept in one place so greedy and any alternative algorithm (e.g. Minimum
    Cost Flow) are evaluated on exactly the same input."""
    drivers_path = PROJECT_ROOT / "data" / "generated" / "drivers_final.json"
    drivers = json.loads(drivers_path.read_text(encoding="utf-8"))
    idle_drivers = [d for d in drivers if d["status"] == "idle"]
    for driver in idle_drivers:
        driver.setdefault("idle_minutes", 15.0)
        driver.setdefault("historical_acceptance_rate", 0.5)
        driver.setdefault("recent_suggestions", 0)

    zone_ids = zones["zone_id"].tolist()
    weights = zones["base_demand_weight"].to_numpy()
    weights = weights / weights.sum()
    deficits = {
        zone_id: round(float(weight) * 20.0, 2)
        for zone_id, weight in zip(zone_ids, weights)
        if weight > weights.mean()
    }
    timestamp = datetime.now(timezone.utc)
    return idle_drivers, deficits, timestamp


def demo_live_snapshot(model, config: dict, zones: pd.DataFrame, zone_distances: Dict[tuple, float]) -> List[dict]:
    """Run one suggestion round on the shared demo scenario, to show the
    module producing real suggestions end-to-end."""
    idle_drivers, deficits, timestamp = load_demo_scenario(zones)
    return suggest_round(deficits, idle_drivers, zone_distances, model, config, timestamp)


def simulate_herding_comparison(ticks: int = 4) -> pd.DataFrame:
    """Illustrates why the soft-reserve mechanism matters, without needing a
    full multi-tick engine run: a zone with a constant demand of 10 and only
    2 freshly-idle candidates per tick, where suggested drivers take 2 ticks
    to arrive. WITHOUT the guard, the deficit calculation ignores drivers
    already en route and keeps re-suggesting the full gap every tick — the
    system dogpiles far more drivers than the zone ever needed (herding).
    WITH the guard, incoming drivers are counted immediately, so the zone
    stops asking once it is covered."""
    predicted_demand = 10
    idle_per_tick = 2
    travel_ticks = 2

    rows = []
    for guard in (True, False):
        in_transit: List[int] = []  # suggestions still traveling, one entry per tick they were sent
        total_suggested = 0
        for tick in range(ticks):
            arrived = in_transit[0] if len(in_transit) >= travel_ticks else 0
            still_traveling = sum(in_transit[max(0, len(in_transit) - travel_ticks + 1):]) if guard else 0
            effective_deficit = predicted_demand - idle_per_tick - (still_traveling if guard else 0)
            suggested = max(0, math.ceil(effective_deficit))
            in_transit.append(suggested)
            total_suggested += suggested
            rows.append(
                {
                    "chong_herding": guard,
                    "tick": tick,
                    "goi_y_tick_nay": suggested,
                    "dang_di_chuyen_chua_toi": still_traveling if guard else 0,
                    "tong_goi_y_luy_ke": total_suggested,
                }
            )
    return pd.DataFrame(rows)


def train_or_load_model(output_dir: Path):
    model_path = output_dir / "acceptance_model.joblib"
    if not model_path.exists():
        raise FileNotFoundError(
            f"{model_path} không tồn tại — chạy `python -m ml.acceptance_model` trước."
        )
    return joblib.load(model_path)


def run(output_dir: Path) -> dict:
    config = load_config()
    zones = load_zones()
    full_zones = pd.DataFrame(json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8")))
    zone_distances = build_zone_distances(full_zones[["zone_id", "center_lat", "center_lng"]])
    model = train_or_load_model(output_dir)

    suggestions = demo_live_snapshot(model, config, zones, zone_distances)
    herding_comparison = simulate_herding_comparison()
    herding_comparison.to_csv(output_dir / "herding_comparison.csv", index=False)

    summary = {
        "live_snapshot_suggestions": len(suggestions),
        "live_snapshot_sample": suggestions[:10],
        "herding_comparison_total_suggested": {
            "voi_chong_herding": int(
                herding_comparison[herding_comparison["chong_herding"]]["goi_y_tick_nay"].sum()
            ),
            "khong_chong_herding": int(
                herding_comparison[~herding_comparison["chong_herding"]]["goi_y_tick_nay"].sum()
            ),
        },
    }
    (output_dir / "repositioning_suggester_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Week 3 Repositioning Suggester demo")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
