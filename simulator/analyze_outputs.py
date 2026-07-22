import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from .validate_outputs import read_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Week 2 simulator sanity-check artifacts")
    parser.add_argument("--output", type=Path, default=Path("data/generated"))
    parser.add_argument("--artifacts", type=Path, default=Path("data/generated/analysis"))
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)

    demand = read_dataset(args.output / "demand_events")
    acceptance = read_dataset(args.output / "acceptance_history")
    zones = pd.read_json("data/hanoi_zones.json")[["zone_id", "zone_type"]]

    demand["local_time"] = demand["request_time"].dt.tz_convert("Asia/Ho_Chi_Minh")
    demand["hour"] = demand["local_time"].dt.hour
    demand = demand.merge(zones, left_on="pickup_zone_id", right_on="zone_id", how="left")
    hourly = demand.groupby("hour").size().rename("request_count").reset_index()
    by_type = demand.groupby("zone_type").size().rename("request_count").sort_values(ascending=False)
    hourly.to_csv(args.artifacts / "demand_by_hour.csv", index=False, encoding="utf-8")
    by_type.to_csv(args.artifacts / "demand_by_zone_type.csv", encoding="utf-8")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(hourly["hour"], hourly["request_count"] / demand["local_time"].dt.date.nunique(), marker="o")
    ax.axvspan(7, 9, alpha=0.15, color="orange", label="Morning peak")
    ax.axvspan(17, 19, alpha=0.15, color="red", label="Evening peak")
    ax.set(title="Average synthetic demand by local hour", xlabel="Hour", ylabel="Requests/day")
    ax.set_xticks(range(0, 24, 2))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.artifacts / "demand_by_hour.png", dpi=160)
    plt.close(fig)

    acceptance["distance_band"] = pd.cut(
        acceptance["distance_m"], bins=[0, 1000, 2500, 5000, float("inf")],
        labels=["0-1km", "1-2.5km", "2.5-5km", ">5km"], right=False
    )
    acceptance["battery_band"] = pd.cut(
        acceptance["battery_percent"], bins=[0, 20, 40, 60, 80, 101],
        labels=["0-20", "20-40", "40-60", "60-80", "80-100"], right=False
    )
    acceptance_by_distance = acceptance.groupby("distance_band", observed=False)["accepted"].mean()
    acceptance_by_battery = acceptance.groupby("battery_band", observed=False)["accepted"].mean()
    acceptance_by_distance.to_csv(args.artifacts / "acceptance_by_distance.csv", encoding="utf-8")
    acceptance_by_battery.to_csv(args.artifacts / "acceptance_by_battery.csv", encoding="utf-8")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    acceptance_by_distance.plot(kind="bar", ax=axes[0], title="Acceptance by distance")
    acceptance_by_battery.plot(kind="bar", ax=axes[1], title="Acceptance by battery")
    for ax in axes:
        ax.set_ylim(0, 1)
        ax.set_ylabel("Acceptance rate")
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(args.artifacts / "acceptance_sanity_checks.png", dpi=160)
    plt.close(fig)

    metrics = {
        "days": int(demand["local_time"].dt.date.nunique()),
        "request_count": int(len(demand)),
        "acceptance_sample_count": int(len(acceptance)),
        "overall_acceptance_rate": round(float(acceptance["accepted"].mean()), 4),
        "highest_demand_hour": int(hourly.loc[hourly["request_count"].idxmax(), "hour"]),
        "highest_demand_zone_type": str(by_type.index[0]),
    }
    (args.artifacts / "analysis_summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
