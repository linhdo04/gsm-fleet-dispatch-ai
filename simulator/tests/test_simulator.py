import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from simulator.engine import PROJECT_ROOT, FleetSimulator
from simulator.generators import demand_counts_by_zone
from simulator.models import Driver
from simulator.supply_tracker import build_supply_snapshots


class SimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(
            (PROJECT_ROOT / "data" / "simulation_config.json").read_text(encoding="utf-8")
        )
        cls.zones = json.loads(
            (PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8")
        )

    def test_project_scale_is_consistent(self) -> None:
        self.assertEqual(len(self.zones), 30)
        self.assertEqual(self.config["simulation"]["zone_count"], 30)
        self.assertEqual(self.config["simulation"]["initial_driver_count"], 300)
        self.assertEqual(len({zone["h3_index"] for zone in self.zones}), 30)

    def test_demand_generation_is_reproducible(self) -> None:
        timestamp = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
        first = demand_counts_by_zone(
            self.zones, timestamp, "rain", False, self.config["demand"], 300,
            np.random.default_rng(1234)
        )
        second = demand_counts_by_zone(
            self.zones, timestamp, "rain", False, self.config["demand"], 300,
            np.random.default_rng(1234)
        )
        self.assertEqual(first, second)
        self.assertGreater(sum(first.values()), 0)

    def test_supply_tracker_counts_each_driver_once(self) -> None:
        now = datetime(2026, 1, 5, tzinfo=timezone.utc)
        zone_a, zone_b = self.zones[0]["zone_id"], self.zones[1]["zone_id"]
        drivers = [
            Driver("D1", zone_a, 80.0, "idle", idle_since=now),
            Driver("D2", zone_a, 70.0, "busy", zone_b, now),
        ]
        rows = build_supply_snapshots(
            drivers, self.zones, now, 1200, {zone_a: 1}, {zone_a: 2}
        )
        by_zone = {row["zone_id"]: row for row in rows}
        self.assertEqual(by_zone[zone_a]["idle_drivers"], 1)
        self.assertEqual(by_zone[zone_b]["trip_dropoff_incoming"], 1)
        self.assertEqual(sum(row["idle_drivers"] for row in rows), 1)

    def test_driver_initialization_is_reproducible(self) -> None:
        first = FleetSimulator(seed=77)
        second = FleetSimulator(seed=77)
        first.initialize(date(2026, 1, 5))
        second.initialize(date(2026, 1, 5))
        signature_a = [(d.zone_id, d.battery_percent, d.status) for d in first.drivers]
        signature_b = [(d.zone_id, d.battery_percent, d.status) for d in second.drivers]
        self.assertEqual(signature_a, signature_b)


if __name__ == "__main__":
    unittest.main()
