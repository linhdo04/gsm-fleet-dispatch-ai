import argparse
import json
from datetime import date
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from simulator.engine import FleetSimulator
from simulator.validate_outputs import read_dataset

from .common import PROJECT_ROOT

SCENARIOS = ["A_PASSIVE", "B_REPOSITION_NO_RESERVE", "C_REPOSITION_SOFT_RESERVE"]


def run_scenario(scenario: str, seed: int, start_date: date, days: int, output_root: Path) -> dict:
    output_dir = output_root / scenario
    simulator = FleetSimulator(seed=seed)
    return simulator.run(start_date, days, output_dir, scenario=scenario)


def supply_demand_std(output_dir: Path) -> float:
    """report.md's 4th A/B metric: 'Độ lệch chuẩn tỷ lệ cung/cầu giữa các zone
    theo thời gian' — the std, across zones, of a smoothed supply/demand
    ratio (idle+confirmed_incoming+1)/(actual_demand+1) at each tick,
    averaged over every tick in the run. A high value means some zones are
    starved while others are flooded at the same moment — the imbalance the
    whole system exists to reduce."""
    supply = read_dataset(output_dir / "supply_snapshots")
    supply["supply_demand_ratio"] = (supply["idle_drivers"] + supply["confirmed_incoming"] + 1) / (
        supply["actual_demand"] + 1
    )
    per_tick_std = supply.groupby("timestamp")["supply_demand_ratio"].std()
    return float(per_tick_std.mean())


def summarize(scenario: str, run_summary: dict, output_dir: Path) -> dict:
    generated = run_summary["generated_requests"]
    matched = run_summary["matched_requests"]
    cancelled = run_summary["cancelled_requests"]
    wait_count = run_summary.get("wait_count", 0)
    return {
        "scenario": scenario,
        "generated_requests": generated,
        "matched_requests": matched,
        "cancelled_requests": cancelled,
        "repositioned_drivers": run_summary.get("repositioned_drivers", 0),
        "avg_wait_seconds": round(run_summary["wait_seconds_total"] / wait_count, 1) if wait_count else None,
        "cancellation_rate_pct": round(100 * cancelled / generated, 2) if generated else None,
        "deadhead_m_total": run_summary["deadhead_m"],
        "deadhead_m_per_driver": round(run_summary["deadhead_m"] / run_summary["driver_count"], 1),
        "supply_demand_ratio_std": round(supply_demand_std(output_dir), 4),
    }


def run_ab_test(seed: int, start_date: date, days: int, output_root: Path) -> Dict[str, dict]:
    output_root.mkdir(parents=True, exist_ok=True)
    results = {}
    for scenario in SCENARIOS:
        run_summary = run_scenario(scenario, seed, start_date, days, output_root)
        results[scenario] = summarize(scenario, run_summary, output_root / scenario)
    (output_root / "ab_test_summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(results.values()).to_csv(output_root / "ab_test_summary.csv", index=False)
    return results


NUMERIC_KPI_COLUMNS = [
    "avg_wait_seconds",
    "cancellation_rate_pct",
    "deadhead_m_per_driver",
    "supply_demand_ratio_std",
    "repositioned_drivers",
]


def run_ab_test_multi_seed(
    seeds: list, start_date: date, days: int, output_root: Path
) -> pd.DataFrame:
    """A single seed's difference between scenarios is partly noise — each
    scenario also consumes a different number of RNG draws (repositioning
    draws extra Bernoulli acceptance rolls the passive scenario never
    touches), which shifts the demand realization downstream even under a
    'same' seed. Averaging across every seed already configured for this in
    `simulation_config.json` (`experiments.ab_test_seeds`) turns a single
    noisy run into a defensible comparison."""
    output_root.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for seed in seeds:
        seed_dir = output_root / f"seed_{seed}"
        for scenario in SCENARIOS:
            run_summary = run_scenario(scenario, seed, start_date, days, seed_dir)
            row = summarize(scenario, run_summary, seed_dir / scenario)
            row["seed"] = seed
            all_rows.append(row)

    raw = pd.DataFrame(all_rows)
    raw.to_csv(output_root / "ab_test_raw_by_seed.csv", index=False)

    agg = (
        raw.groupby("scenario")[NUMERIC_KPI_COLUMNS]
        .agg(["mean", "std"])
        .round(4)
    )
    agg.columns = ["_".join(col) for col in agg.columns]
    agg = agg.reindex(SCENARIOS).reset_index()
    agg.to_csv(output_root / "ab_test_summary_multi_seed.csv", index=False)
    agg.to_json(output_root / "ab_test_summary_multi_seed.json", orient="records", indent=2)
    return agg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Week 4 A/B test (3 repositioning scenarios)")
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument(
        "--multi-seed",
        action="store_true",
        help="Average over every seed in simulation_config.json's experiments.ab_test_seeds instead of a single run",
    )
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 5))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "ab_test")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.multi_seed:
        from .common import load_config

        seeds = load_config()["experiments"]["ab_test_seeds"]
        agg = run_ab_test_multi_seed(seeds, args.start_date, args.days, args.output)
        print(agg.to_string(index=False))
    else:
        results = run_ab_test(args.seed, args.start_date, args.days, args.output)
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
