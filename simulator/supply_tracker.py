from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, Iterable, List

from .models import Driver


def build_supply_snapshots(
    drivers: Iterable[Driver], zones: List[dict], timestamp: datetime,
    horizon_seconds: int, outgoing_by_zone: Dict[str, int],
    actual_demand_by_zone: Dict[str, int]
) -> List[dict]:
    idle = Counter()
    repositioning_incoming = Counter()
    trip_dropoff_incoming = Counter()
    horizon = timestamp + timedelta(seconds=horizon_seconds)

    for driver in drivers:
        if driver.status == "idle":
            idle[driver.zone_id] += 1
        elif driver.status == "incoming" and driver.destination_zone_id:
            repositioning_incoming[driver.destination_zone_id] += 1
        elif (
            driver.status == "busy"
            and driver.destination_zone_id
            and driver.available_at is not None
            and driver.available_at <= horizon
        ):
            trip_dropoff_incoming[driver.destination_zone_id] += 1

    rows = []
    for zone in zones:
        zone_id = zone["zone_id"]
        confirmed = repositioning_incoming[zone_id] + trip_dropoff_incoming[zone_id]
        outgoing = int(outgoing_by_zone.get(zone_id, 0))
        predicted_supply = idle[zone_id] + confirmed - outgoing
        rows.append(
            {
                "timestamp": timestamp,
                "zone_id": zone_id,
                "zone_type": zone["zone_type"],
                "idle_drivers": int(idle[zone_id]),
                "repositioning_incoming": int(repositioning_incoming[zone_id]),
                "trip_dropoff_incoming": int(trip_dropoff_incoming[zone_id]),
                "confirmed_incoming": int(confirmed),
                "expected_pending_incoming": 0.0,
                "outgoing_drivers": outgoing,
                "predicted_supply": float(predicted_supply),
                "actual_demand": int(actual_demand_by_zone.get(zone_id, 0)),
                "observed_deficit": float(actual_demand_by_zone.get(zone_id, 0) - predicted_supply),
            }
        )
    return rows
