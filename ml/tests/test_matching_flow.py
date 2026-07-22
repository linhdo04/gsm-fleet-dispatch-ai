import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ml.matching_flow import (
    RouteEstimator,
    ZoneState,
    find_and_reserve_driver_for_zone,
    find_nearest_charging_station,
    on_suggestion_accepted,
    on_suggestion_resolved_without_move,
)
from ml.routing_client import GoogleRoutesClient

# The 3 edge cases explicitly requested in docs/business_design.md's
# "Việc cần Agent làm cụ thể" (item 5): (a) two requests racing for the same
# driver, (b) a soft-reserve expiring mid-batch, (c) deficit hitting zero
# mid-batch — each must NOT result in a double-assignment or an
# over-committed zone.


class StubAcceptanceModel:
    """Deterministic p_accept by row position — `rank_by_p_accept` only ever
    passes `ACCEPTANCE_FEATURE_COLUMNS` to `predict_proba` (matching what the
    real trained model receives in production), so the stub can't key off
    `driver_id`. Row order matches the candidate list order the caller
    passed in, which every test below controls explicitly."""

    def __init__(self, p_sequence):
        self.p_sequence = list(p_sequence)

    def predict_proba(self, frame: pd.DataFrame):
        p = np.array(self.p_sequence[: len(frame)], dtype=float)
        return np.column_stack([1 - p, p])


def make_config(**overrides) -> dict:
    config = {
        "matching": {
            "vehicle_capacity": 4,
            "eta_fast_threshold_seconds": 300,
            "urgent_threshold_seconds": 360,
            "urgent_priority_boost": 100000,
            "batch_window_seconds": {"normal": 30, "high_deficit": 15},
            "max_detour_ratio": {"default": 0.20, "rain": 0.15},
            "pickup_eta_max_minutes": {"default": 10, "rain": 12},
            "cost_weights": {
                "w1_wait_time": 1.0,
                "w2_existing_passenger_extra_time": 0.5,
                "w3_fill_rate": 2.0,
                "w4_detour_penalty": 3.0,
            },
        },
        "battery": {
            "low_battery_threshold_percent": 20,
            "critical_battery_threshold_percent": 10,
            "minimum_trip_reserve_percent": 8,
        },
        "repositioning": {
            "soft_reserve_ttl_seconds": 60,
            "candidate_radius_m": 5000,
            "idle_timeout_seconds_before_reposition_check": 900,
        },
    }
    config.update(overrides)
    return config


def make_router() -> RouteEstimator:
    # 3 zones on a line, 2km apart — no cost_model, so duration falls back
    # to distance / BASE_SPEED_M_PER_S (deterministic, no model file needed).
    zone_distances = {
        ("Z1", "Z1"): 0.0, ("Z2", "Z2"): 0.0, ("Z3", "Z3"): 0.0,
        ("Z1", "Z2"): 2000.0, ("Z2", "Z1"): 2000.0,
        ("Z1", "Z3"): 4000.0, ("Z3", "Z1"): 4000.0,
        ("Z2", "Z3"): 2000.0, ("Z3", "Z2"): 2000.0,
    }
    return RouteEstimator(zone_distances, road_distance_multiplier=1.0, cost_model=None)


def make_driver(driver_id: str, zone_id: str, battery: float = 80.0) -> dict:
    return {
        "driver_id": driver_id,
        "zone_id": zone_id,
        "battery_percent": battery,
        "status": "idle",
        "idle_minutes": 15.0,
        "historical_acceptance_rate": 0.5,
        "recent_suggestions": 0,
    }


class RaceForSameDriverTest(unittest.TestCase):
    """(a) Two zones both in deficit, only one idle driver exists overall —
    reserving it for the first zone must remove it from the candidate pool
    for the second zone in the same batch, instead of double-assigning it."""

    def test_second_zone_gets_no_driver_once_the_only_one_is_reserved(self):
        config = make_config()
        router = make_router()
        acceptance_model = StubAcceptanceModel([0.9])

        driver = make_driver("D1", "Z1")
        drivers_by_id = {"D1": driver}
        zone_states = {
            "Z1": ZoneState("Z1", predicted_demand=0.0),
            "Z2": ZoneState("Z2", predicted_demand=5.0),
            "Z3": ZoneState("Z3", predicted_demand=5.0),
        }
        now = datetime.now(timezone.utc)

        first = find_and_reserve_driver_for_zone(
            "Z2", zone_states, [driver], drivers_by_id, router, acceptance_model, config, now
        )
        self.assertIsNotNone(first)
        self.assertEqual(driver["status"], "reserved")

        second = find_and_reserve_driver_for_zone(
            "Z3", zone_states, [driver], drivers_by_id, router, acceptance_model, config, now
        )
        self.assertIsNone(second, "the same physical driver must not be reserved twice across zones")
        self.assertEqual(zone_states["Z3"].expected_pending_incoming, 0.0)


class SoftReserveExpiryTest(unittest.TestCase):
    """(b) A soft-reserve that expires mid-batch must release the driver back
    to idle and remove its p_accept contribution from expected_pending_incoming
    — without ever crediting confirmed_incoming (mục 2.4 business_design.md:
    a pending reservation is not confirmed supply)."""

    def test_expired_reservation_frees_driver_and_reverts_pending_incoming(self):
        config = make_config()
        router = make_router()
        acceptance_model = StubAcceptanceModel([0.8])

        driver = make_driver("D1", "Z1")
        drivers_by_id = {"D1": driver}
        zone_states = {"Z1": ZoneState("Z1", predicted_demand=0.0), "Z2": ZoneState("Z2", predicted_demand=5.0)}
        now = datetime.now(timezone.utc)

        suggestion = find_and_reserve_driver_for_zone(
            "Z2", zone_states, [driver], drivers_by_id, router, acceptance_model, config, now
        )
        self.assertIsNotNone(suggestion)
        self.assertAlmostEqual(zone_states["Z2"].expected_pending_incoming, 0.8)
        self.assertEqual(driver["status"], "reserved")

        expired_at = now + timedelta(seconds=config["repositioning"]["soft_reserve_ttl_seconds"] + 1)
        self.assertGreater(expired_at, suggestion.expires_at)

        on_suggestion_resolved_without_move(suggestion, zone_states, drivers_by_id, reason="expired")

        self.assertEqual(suggestion.reserve_status, "expired")
        self.assertEqual(driver["status"], "idle", "driver must be released back to idle, not stuck reserved")
        self.assertAlmostEqual(zone_states["Z2"].expected_pending_incoming, 0.0)
        self.assertEqual(zone_states["Z2"].confirmed_incoming, 0, "an expired reservation must never count as confirmed supply")

        # released driver is usable again
        second = find_and_reserve_driver_for_zone(
            "Z2", zone_states, [driver], drivers_by_id, router, acceptance_model, config, now
        )
        self.assertIsNotNone(second)


class DeficitReachesZeroMidBatchTest(unittest.TestCase):
    """(c) Once enough soft-reserves have been made that expected_deficit has
    reached zero, further reservation attempts for the same zone in the same
    batch must stop (the anti-herding guard) instead of continuing to pile on
    drivers the zone no longer needs."""

    def test_no_further_reservation_once_expected_deficit_hits_zero(self):
        config = make_config()
        router = make_router()
        # p_accept = 1.0 so a single reservation fully covers a deficit of 1.
        acceptance_model = StubAcceptanceModel([1.0, 1.0])

        driver1 = make_driver("D1", "Z1")
        driver2 = make_driver("D2", "Z1")
        drivers_by_id = {"D1": driver1, "D2": driver2}
        zone_states = {"Z1": ZoneState("Z1", predicted_demand=0.0), "Z2": ZoneState("Z2", predicted_demand=1.0)}
        now = datetime.now(timezone.utc)

        first = find_and_reserve_driver_for_zone(
            "Z2", zone_states, [driver1, driver2], drivers_by_id, router, acceptance_model, config, now
        )
        self.assertIsNotNone(first)
        self.assertEqual(zone_states["Z2"].expected_deficit, 0.0)

        second = find_and_reserve_driver_for_zone(
            "Z2", zone_states, [driver1, driver2], drivers_by_id, router, acceptance_model, config, now
        )
        self.assertIsNone(second, "zone already covered — must not reserve a second driver it no longer needs")
        self.assertEqual(driver2["status"], "idle", "the untouched second driver must remain idle/available")


class NearestChargingStationTest(unittest.TestCase):
    """`find_nearest_charging_station` must pick the actually-closest station,
    not just the first one in the list — and honestly report `is_fallback`
    (no GOOGLE_ROUTES_API_KEY in this environment, so always True here)."""

    def test_picks_the_geographically_closest_station(self):
        zone_center_by_id = {"Z1": (21.0, 105.8), "Z2": (21.05, 105.85), "Z3": (21.2, 106.0)}
        stations = [
            {"station_id": "CHG-A", "name": "A", "lat": 21.001, "lng": 105.801},  # ~150m from Z1
            {"station_id": "CHG-B", "name": "B", "lat": 21.2, "lng": 106.0},  # far from Z1, exactly at Z3
        ]
        client = GoogleRoutesClient(api_key=None)

        nearest_to_z1 = find_nearest_charging_station("Z1", stations, zone_center_by_id, client)
        self.assertEqual(nearest_to_z1["station_id"], "CHG-A")
        self.assertTrue(nearest_to_z1["is_fallback"])

        nearest_to_z3 = find_nearest_charging_station("Z3", stations, zone_center_by_id, client)
        self.assertEqual(nearest_to_z3["station_id"], "CHG-B")
        self.assertAlmostEqual(nearest_to_z3["distance_m"], 0.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
