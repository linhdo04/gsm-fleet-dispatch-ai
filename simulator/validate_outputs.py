import argparse
import json
from pathlib import Path

import pandas as pd


def read_dataset(path: Path) -> pd.DataFrame:
    parts = sorted(path.glob("day=*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No parquet partitions found in {path}")
    return pd.concat((pd.read_parquet(part) for part in parts), ignore_index=True)


def validate(output: Path) -> dict:
    demand = read_dataset(output / "demand_events")
    supply = read_dataset(output / "supply_snapshots")
    acceptance = read_dataset(output / "acceptance_history")
    drivers = json.loads((output / "drivers_final.json").read_text(encoding="utf-8"))
    run = json.loads((output / "simulation_run.json").read_text(encoding="utf-8"))

    assert len(drivers) == run["driver_count"] == 300
    assert demand["request_id"].is_unique
    assert supply.groupby("timestamp")["zone_id"].nunique().eq(30).all()
    assert supply[["idle_drivers", "confirmed_incoming", "outgoing_drivers"]].ge(0).all().all()
    assert acceptance["p_accept_ground_truth"].between(0, 1).all()
    assert acceptance["battery_percent"].between(0, 100).all()
    assert set(acceptance["accepted"].dropna().unique()).issubset({True, False})
    assert all(0 <= float(driver["battery_percent"]) <= 100 for driver in drivers)

    hourly = demand.assign(hour=demand["request_time"].dt.floor("h")).groupby("hour").size()
    summary = {
        "demand_rows": len(demand),
        "supply_rows": len(supply),
        "acceptance_rows": len(acceptance),
        "driver_count": len(drivers),
        "mean_requests_per_hour": round(float(hourly.mean()), 2),
        "peak_requests_per_hour": int(hourly.max()),
        "acceptance_rate": round(float(acceptance["accepted"].mean()), 4),
        "validation": "passed",
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generated simulator datasets")
    parser.add_argument("--output", type=Path, default=Path("data/generated"))
    args = parser.parse_args()
    print(json.dumps(validate(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
