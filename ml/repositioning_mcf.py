import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from ortools.graph.python import min_cost_flow

from .common import PROJECT_ROOT, load_config, load_zones
from .repositioning_suggester import (
    build_zone_distances,
    load_demo_scenario,
    rank_candidates,
    suggest_round,
    train_or_load_model,
)


def group_idle_by_zone(idle_drivers: List[dict]) -> Dict[str, List[dict]]:
    idle_by_zone: Dict[str, List[dict]] = defaultdict(list)
    for driver in idle_drivers:
        idle_by_zone[driver["zone_id"]].append(driver)
    return idle_by_zone


def build_supply_demand(
    idle_drivers: List[dict], deficits: Dict[str, float]
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Surplus zones = every zone holding idle drivers that is *not* itself
    in deficit (mirrors the 'vùng thừa xe (S) / vùng thiếu xe (D)' split from
    the fleet-rebalancing literature). Demand is the same synthetic deficit
    profile used by the greedy demo, rounded up to whole drivers for the
    integer flow formulation MCF requires."""
    idle_by_zone: Dict[str, int] = defaultdict(int)
    for driver in idle_drivers:
        idle_by_zone[driver["zone_id"]] += 1

    demand = {zone_id: int(-(-amount // 1)) for zone_id, amount in deficits.items() if amount > 0}
    supply = {
        zone_id: count
        for zone_id, count in idle_by_zone.items()
        if zone_id not in demand and count > 0
    }
    return supply, demand


def distance_pair_costs(
    surplus_ids: List[str], deficit_ids: List[str], zone_distances: Dict[tuple, float]
) -> Dict[Tuple[str, str], float]:
    """Pure-distance arc cost — the classic transportation-problem
    formulation, blind to how likely a driver is to actually accept."""
    return {
        (s_id, d_id): zone_distances[(s_id, d_id)] * 1.3 for s_id in surplus_ids for d_id in deficit_ids
    }


def estimate_zone_pair_p_accept(
    surplus_ids: List[str],
    deficit_ids: List[str],
    idle_by_zone: Dict[str, List[dict]],
    zone_distances: Dict[tuple, float],
    model,
    timestamp,
) -> Dict[Tuple[str, str], float]:
    """Best predicted p_accept across a surplus zone's current idle pool, for
    each (surplus_zone, deficit_zone) pair — i.e. the p_accept of whichever
    driver `flows_to_driver_suggestions` would actually pick *first* from
    that zone. Using the pool *average* here instead (tried first) badly
    over-estimates how many drivers are needed: a zone with 13 idle drivers
    of mixed battery/history has one great candidate and a dozen mediocre
    ones, but demand only needs to be inflated for the one that will really
    be sent. Averaging in the mediocre ones inflated demand from 17 to 45
    and forced MCF to dig into far, low-quality pairs to hit that inflated
    target — worse on every metric than doing nothing. The max fixes that.
    This single estimate feeds both halves of the two-tier fix: it prices
    the MCF arc (so the zone-pair choice isn't blind to acceptance) and it
    inflates each zone's integer demand (so the *quantity* sent isn't blind
    to it either)."""
    p_accept_map = {}
    for s_id in surplus_ids:
        pool = idle_by_zone.get(s_id, [])
        if not pool:
            continue
        for d_id in deficit_ids:
            ranked = rank_candidates(pool, d_id, 1.0, timestamp, zone_distances, model)
            p_accept_map[(s_id, d_id)] = float(ranked["p_accept"].max())
    return p_accept_map


def hybrid_pair_costs(
    pair_p_accept: Dict[Tuple[str, str], float], zone_distances: Dict[tuple, float]
) -> Dict[Tuple[str, str], float]:
    """Layer-1 cost, fix #1: price each zone pair as *expected distance per
    accepted driver* (distance / p_accept) instead of raw distance — a
    purely distance-minimizing flow plan happily routes drivers into far,
    low-acceptance pairs."""
    return {
        (s_id, d_id): (zone_distances[(s_id, d_id)] * 1.3) / max(p_accept, 0.05)
        for (s_id, d_id), p_accept in pair_p_accept.items()
    }


def inflate_demand_for_acceptance(
    deficits: Dict[str, float], deficit_ids: List[str], pair_p_accept: Dict[Tuple[str, str], float]
) -> Dict[str, int]:
    """Layer-1 cost, fix #2 — the one that actually matters most: plain MCF
    treats `ceil(deficit)` as a hard, guaranteed-to-succeed target, exactly
    like each suggested driver is certain to accept. Greedy never makes that
    mistake (it subtracts p_accept, not 1, per suggestion — see
    repositioning_suggester.py) which is *why* it ends up sending ~2x more
    drivers per zone than MCF's naive integer demand. Here each zone's
    demand is inflated by the best acceptance rate reachable from any
    surplus zone, so MCF's *quantity* decision stops under-shooting too,
    not just its zone-pair choice."""
    best_p_accept: Dict[str, float] = {}
    for (_, d_id), p_accept in pair_p_accept.items():
        if p_accept > best_p_accept.get(d_id, 0.0):
            best_p_accept[d_id] = p_accept
    inflated = {}
    for d_id in deficit_ids:
        p_hat = best_p_accept.get(d_id, 0.5)
        inflated[d_id] = max(1, math.ceil(deficits[d_id] / max(p_hat, 0.05)))
    return inflated


def solve_min_cost_flow(
    supply: Dict[str, int],
    demand: Dict[str, int],
    pair_costs: Dict[Tuple[str, str], float],
    unmet_penalty: Optional[float] = None,
) -> List[dict]:
    """Classic transportation-problem formulation: source -> surplus zones
    -> deficit zones -> sink. This is the Minimum Cost Flow approach
    (Google OR-Tools) suggested as the "tối ưu hoá toàn cục" alternative to
    the greedy p_accept-ranked Repositioning Suggester — the arc cost is
    supplied by the caller (`distance_pair_costs` for the plain baseline,
    `hybrid_pair_costs` for the two-tier hybrid).

    Unlike the greedy suggester, the bipartite graph here is fully
    connected (no candidate_radius_m cutoff): a global cost-minimizer
    already disfavours expensive pairs through the cost itself, and an
    artificial radius cutoff can make the exact supply/demand balance
    SimpleMinCostFlow requires infeasible.

    `unmet_penalty`, when set, turns `demand` from a hard target into a
    soft one: a phantom source->deficit arc lets a zone go "unfulfilled" at
    a high fixed cost instead of forcing a real driver into an excessively
    bad pair just to hit an inflated integer target exactly. Needed once
    `demand` comes from `inflate_demand_for_acceptance` — inflating by
    1/p_accept can ask for more drivers than nearby supply can reasonably
    cover, and a *hard* balance would rather ship a driver 8km away than
    leave that phantom shortfall unresolved."""
    surplus_ids = sorted(supply)
    deficit_ids = sorted(demand)
    source = 0
    surplus_node = {zone_id: 1 + i for i, zone_id in enumerate(surplus_ids)}
    deficit_node = {zone_id: 1 + len(surplus_ids) + j for j, zone_id in enumerate(deficit_ids)}
    sink = 1 + len(surplus_ids) + len(deficit_ids)

    smcf = min_cost_flow.SimpleMinCostFlow()
    for zone_id in surplus_ids:
        smcf.add_arc_with_capacity_and_unit_cost(source, surplus_node[zone_id], supply[zone_id], 0)
    for zone_id in deficit_ids:
        smcf.add_arc_with_capacity_and_unit_cost(deficit_node[zone_id], sink, demand[zone_id], 0)

    arc_lookup: Dict[int, Tuple[str, str]] = {}
    for s_id in surplus_ids:
        for d_id in deficit_ids:
            cost = pair_costs.get((s_id, d_id))
            if cost is None:
                continue
            arc_index = smcf.add_arc_with_capacity_and_unit_cost(
                surplus_node[s_id], deficit_node[d_id], min(supply[s_id], demand[d_id]), round(cost)
            )
            arc_lookup[arc_index] = (s_id, d_id)

    total_supply = sum(supply.values())
    total_demand = sum(demand.values())
    if unmet_penalty is not None:
        for zone_id in deficit_ids:
            smcf.add_arc_with_capacity_and_unit_cost(source, deficit_node[zone_id], demand[zone_id], round(unmet_penalty))
        total_flow = total_demand
    else:
        total_flow = min(total_supply, total_demand)

    smcf.set_node_supply(source, total_flow)
    smcf.set_node_supply(sink, -total_flow)

    status = smcf.solve()
    if status != smcf.OPTIMAL:
        raise RuntimeError(f"MinCostFlow did not reach OPTIMAL (status={status})")

    flows = []
    for arc_index, (s_id, d_id) in arc_lookup.items():
        flow = smcf.flow(arc_index)
        if flow > 0:
            flows.append({"from_zone_id": s_id, "target_zone_id": d_id, "drivers_to_move": int(flow)})
    return flows


def flows_to_driver_suggestions(
    flows: List[dict],
    idle_drivers: List[dict],
    zone_distances: Dict[tuple, float],
    model,
    timestamp,
) -> List[dict]:
    """MCF only plans zone-to-zone driver counts ('move N drivers from X to
    Y'); it still needs a policy for *which* physical driver goes. To keep
    the comparison against the greedy suggester fair, pick the same way:
    rank idle drivers in the surplus zone by the Acceptance Probability
    Model and take the top N per flow."""
    idle_by_zone = group_idle_by_zone(idle_drivers)
    used_driver_ids = set()

    suggestions = []
    for flow in sorted(flows, key=lambda item: item["drivers_to_move"], reverse=True):
        pool = [d for d in idle_by_zone[flow["from_zone_id"]] if d["driver_id"] not in used_driver_ids]
        if not pool:
            continue
        ranked = rank_candidates(
            pool, flow["target_zone_id"], float(flow["drivers_to_move"]), timestamp, zone_distances, model
        )
        chosen = ranked.head(flow["drivers_to_move"])
        for _, row in chosen.iterrows():
            used_driver_ids.add(row["driver_id"])
            suggestions.append(
                {
                    "driver_id": row["driver_id"],
                    "from_zone_id": row["from_zone_id"],
                    "target_zone_id": flow["target_zone_id"],
                    "distance_m": round(float(row["distance_m"]), 1),
                    "p_accept": round(float(row["p_accept"]), 4),
                }
            )
    return suggestions


def summarize(name: str, suggestions: List[dict], elapsed_seconds: float, total_deficit: float) -> dict:
    total_distance = sum(item["distance_m"] for item in suggestions)
    total_expected_coverage = sum(item["p_accept"] for item in suggestions)
    return {
        "algorithm": name,
        "runtime_ms": round(elapsed_seconds * 1000, 3),
        "drivers_suggested": len(suggestions),
        "total_distance_m": round(total_distance, 1),
        "avg_distance_m": round(total_distance / len(suggestions), 1) if suggestions else None,
        "total_expected_coverage": round(total_expected_coverage, 2),
        "coverage_ratio_vs_deficit": round(total_expected_coverage / total_deficit, 4) if total_deficit else None,
    }


def run_comparison(output_dir: Path) -> dict:
    config = load_config()
    zones = load_zones()
    full_zones = pd.DataFrame(json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8")))
    zone_distances = build_zone_distances(full_zones[["zone_id", "center_lat", "center_lng"]])
    model = train_or_load_model(output_dir)

    idle_drivers, deficits, timestamp = load_demo_scenario(zones)
    total_deficit = sum(deficits.values())
    idle_by_zone = group_idle_by_zone(idle_drivers)

    # 1) Greedy — p_accept ranking, online per-zone soft-reserve (report.md's design).
    start = time.perf_counter()
    greedy_suggestions = suggest_round(deficits, [dict(d) for d in idle_drivers], zone_distances, model, config, timestamp)
    greedy_elapsed = time.perf_counter() - start

    supply, demand = build_supply_demand(idle_drivers, deficits)
    surplus_ids, deficit_ids = sorted(supply), sorted(demand)

    # 2) Pure Minimum Cost Flow — global optimum, but blind to acceptance likelihood.
    start = time.perf_counter()
    distance_costs = distance_pair_costs(surplus_ids, deficit_ids, zone_distances)
    flows_distance = solve_min_cost_flow(supply, demand, distance_costs)
    mcf_distance_suggestions = flows_to_driver_suggestions(
        flows_distance, [dict(d) for d in idle_drivers], zone_distances, model, timestamp
    )
    mcf_distance_elapsed = time.perf_counter() - start

    # 3) Two-tier hybrid — layer 1 (MCF) decides zone-pair quantities using an
    # acceptance-aware cost AND an acceptance-inflated demand (both fixes are
    # needed: cost alone barely moves the needle, see docs/repositioning_mcf_vs_greedy.md);
    # layer 2 (Acceptance Model) still picks the specific driver.
    start = time.perf_counter()
    pair_p_accept = estimate_zone_pair_p_accept(surplus_ids, deficit_ids, idle_by_zone, zone_distances, model, timestamp)
    hybrid_costs = hybrid_pair_costs(pair_p_accept, zone_distances)
    hybrid_demand = inflate_demand_for_acceptance(deficits, deficit_ids, pair_p_accept)
    # A shortfall should only be accepted over a real assignment once that
    # assignment is clearly worse than what greedy typically achieves (avg
    # cost ~5,300 in this scenario) — using the *max* cost in the matrix as
    # the threshold (tried first) made virtually every real pair "cheap by
    # comparison", so the penalty never actually triggered. Anchor it to the
    # cheap end of the distribution instead.
    unmet_penalty = float(np.percentile(list(hybrid_costs.values()), 25))
    flows_hybrid = solve_min_cost_flow(supply, hybrid_demand, hybrid_costs, unmet_penalty=unmet_penalty)
    mcf_hybrid_suggestions = flows_to_driver_suggestions(
        flows_hybrid, [dict(d) for d in idle_drivers], zone_distances, model, timestamp
    )
    mcf_hybrid_elapsed = time.perf_counter() - start

    comparison = {
        "scenario": {
            "deficit_zones": len(deficits),
            "total_deficit": round(total_deficit, 2),
            "surplus_zones": len(supply),
            "surplus_drivers_available": sum(supply.values()),
            "mcf_distance_total_demand": sum(demand.values()),
            "mcf_hybrid_total_demand": sum(hybrid_demand.values()),
        },
        "greedy_p_accept": summarize("greedy_p_accept", greedy_suggestions, greedy_elapsed, total_deficit),
        "min_cost_flow_distance": summarize(
            "min_cost_flow_distance", mcf_distance_suggestions, mcf_distance_elapsed, total_deficit
        ),
        "min_cost_flow_hybrid": summarize(
            "min_cost_flow_hybrid_acceptance_aware", mcf_hybrid_suggestions, mcf_hybrid_elapsed, total_deficit
        ),
        "mcf_distance_flow_plan": flows_distance,
        "mcf_hybrid_flow_plan": flows_hybrid,
    }
    (output_dir / "repositioning_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(greedy_suggestions).to_csv(output_dir / "greedy_suggestions.csv", index=False)
    pd.DataFrame(mcf_distance_suggestions).to_csv(output_dir / "mcf_distance_suggestions.csv", index=False)
    pd.DataFrame(mcf_hybrid_suggestions).to_csv(output_dir / "mcf_hybrid_suggestions.csv", index=False)
    return comparison


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the greedy p_accept Repositioning Suggester against a Minimum Cost Flow (OR-Tools) alternative"
    )
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    comparison = run_comparison(args.output)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
