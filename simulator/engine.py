import json
import math
from collections import Counter, defaultdict, deque
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import holidays
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from .generators import (
    decay_suggestion_counters,
    demand_counts_by_zone,
    expected_acceptance_score,
    generate_acceptance_record,
    generate_drivers,
    generate_weather_for_day,
)
from .geo import random_point_in_zone
from .models import Driver
from .supply_tracker import build_supply_snapshots


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class FleetSimulator:
    def __init__(
        self,
        config_path: Path = PROJECT_ROOT / "data" / "simulation_config.json",
        zones_path: Path = PROJECT_ROOT / "data" / "hanoi_zones.json",
        seed: Optional[int] = None,
    ) -> None:
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.zones = json.loads(zones_path.read_text(encoding="utf-8"))
        if len(self.zones) != self.config["simulation"]["zone_count"]:
            raise ValueError("zone_count does not match hanoi_zones.json")
        self.seed = int(seed if seed is not None else self.config["random_seed"])
        self.rng = np.random.default_rng(self.seed)
        self.local_tz = ZoneInfo(self.config["timezone"])
        self.zone_by_id = {zone["zone_id"]: zone for zone in self.zones}
        self.zone_ids = list(self.zone_by_id)
        self.zone_distances = self._build_zone_distances()
        self.nearest_zones = {
            zone_id: sorted(self.zone_ids, key=lambda target: self.zone_distances[(zone_id, target)])
            for zone_id in self.zone_ids
        }
        self.destination_weights = np.array(
            [zone["base_demand_weight"] for zone in self.zones], dtype=float
        )
        self.destination_weights /= self.destination_weights.sum()
        self.drivers: List[Driver] = []
        self.waiting_requests: Dict[str, Deque[dict]] = defaultdict(deque)
        self.request_sequence = 0
        self.vn_holidays = holidays.country_holidays("VN")

    def _build_zone_distances(self) -> Dict[Tuple[str, str], float]:
        distances = {}
        for source in self.zones:
            for target in self.zones:
                distances[(source["zone_id"], target["zone_id"])] = haversine_m(
                    source["center_lat"], source["center_lng"],
                    target["center_lat"], target["center_lng"]
                )
        return distances

    def _local_midnight_utc(self, day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=self.local_tz).astimezone(timezone.utc)

    def initialize(self, start_date: date) -> None:
        start_time = self._local_midnight_utc(start_date)
        self.drivers = generate_drivers(
            self.zones,
            int(self.config["simulation"]["initial_driver_count"]),
            start_time,
            self.rng,
        )
        for driver in self.drivers:
            if driver.status == "charging":
                driver.available_at = start_time + timedelta(minutes=45)

    def _release_drivers(self, timestamp: datetime) -> None:
        battery_cfg = self.config["battery"]
        for driver in self.drivers:
            if driver.available_at is None or driver.available_at > timestamp:
                continue
            if driver.status == "busy":
                if driver.destination_zone_id is not None:
                    driver.zone_id = driver.destination_zone_id
                    driver.lat, driver.lng = random_point_in_zone(self.zone_by_id[driver.zone_id], self.rng)
                driver.destination_zone_id = None
                if driver.battery_percent < battery_cfg["low_battery_threshold_percent"]:
                    driver.status = "charging"
                    driver.available_at = timestamp + timedelta(minutes=45)
                    driver.idle_since = None
                else:
                    driver.status = "idle"
                    driver.available_at = None
                    driver.idle_since = timestamp
            elif driver.status == "incoming":
                if driver.destination_zone_id is not None:
                    driver.zone_id = driver.destination_zone_id
                    driver.lat, driver.lng = random_point_in_zone(self.zone_by_id[driver.zone_id], self.rng)
                driver.destination_zone_id = None
                if driver.battery_percent < battery_cfg["low_battery_threshold_percent"]:
                    driver.status = "charging"
                    driver.available_at = timestamp + timedelta(minutes=45)
                    driver.idle_since = None
                else:
                    driver.status = "idle"
                    driver.available_at = None
                    driver.idle_since = timestamp
            elif driver.status == "charging":
                driver.battery_percent = float(battery_cfg["charging_target_percent"])
                driver.status = "idle"
                driver.available_at = None
                driver.idle_since = timestamp

    def _expire_waiting_requests(self, timestamp: datetime) -> int:
        ttl = timedelta(seconds=self.config["demand"]["customer_cancellation_after_seconds"])
        cancelled = 0
        for queue in self.waiting_requests.values():
            while queue and timestamp - queue[0]["request_time"] >= ttl:
                queue.popleft()
                cancelled += 1
        return cancelled

    def _generate_requests(
        self, timestamp: datetime, weather: str, is_holiday: bool
    ) -> Tuple[List[dict], Dict[str, int]]:
        local_timestamp = timestamp.astimezone(self.local_tz)
        counts = demand_counts_by_zone(
            self.zones,
            local_timestamp,
            weather,
            is_holiday,
            self.config["demand"],
            int(self.config["simulation"]["planning_tick_seconds"]),
            self.rng,
        )
        records = []
        for zone in self.zones:
            zone_id = zone["zone_id"]
            for _ in range(counts[zone_id]):
                self.request_sequence += 1
                request = {
                    "request_id": f"R{self.request_sequence:09d}",
                    "request_time": timestamp,
                    "pickup_zone_id": zone_id,
                    "pickup_lat": zone["center_lat"],
                    "pickup_lng": zone["center_lng"],
                    "weather": weather,
                    "is_holiday": bool(is_holiday),
                    "status_at_generation": "waiting",
                    "maximum_wait_seconds": int(
                        self.config["demand"]["customer_cancellation_after_seconds"]
                    ),
                }
                self.waiting_requests[zone_id].append(request)
                records.append(request.copy())
        return records, counts

    def _idle_drivers_by_zone(self) -> Dict[str, List[Driver]]:
        result: Dict[str, List[Driver]] = defaultdict(list)
        for driver in self.drivers:
            if driver.status == "idle":
                result[driver.zone_id].append(driver)
        for drivers in result.values():
            drivers.sort(key=lambda item: (-item.battery_percent, item.driver_id))
        return result

    def _find_driver(self, pickup_zone_id: str, idle: Dict[str, List[Driver]]) -> Optional[Driver]:
        minimum_battery = float(self.config["battery"]["minimum_trip_reserve_percent"])
        for zone_id in self.nearest_zones[pickup_zone_id]:
            if self.zone_distances[(zone_id, pickup_zone_id)] > self.config["repositioning"]["candidate_radius_m"]:
                break
            while idle.get(zone_id):
                driver = idle[zone_id].pop()
                if driver.status == "idle" and driver.battery_percent >= minimum_battery:
                    return driver
        return None

    def _match_waiting_requests(self, timestamp: datetime) -> Tuple[Counter, int, float, float]:
        idle = self._idle_drivers_by_zone()
        outgoing = Counter()
        matched = 0
        deadhead_m = 0.0
        wait_seconds_total = 0.0
        for pickup_zone_id in self.zone_ids:
            queue = self.waiting_requests[pickup_zone_id]
            while queue:
                driver = self._find_driver(pickup_zone_id, idle)
                if driver is None:
                    break
                request = queue.popleft()
                destination_index = int(self.rng.choice(len(self.zones), p=self.destination_weights))
                destination_zone_id = self.zones[destination_index]["zone_id"]
                pickup_distance = self.zone_distances[(driver.zone_id, pickup_zone_id)] * 1.3 + 350.0
                trip_distance = self.zone_distances[(pickup_zone_id, destination_zone_id)] * 1.3 + 2500.0
                duration_minutes = max(8.0, (pickup_distance + trip_distance) / 420.0)
                duration_minutes *= float(self.rng.lognormal(mean=0.0, sigma=0.18))
                energy_percent = (pickup_distance + trip_distance) / 1000.0 * 0.32
                driver.battery_percent = max(0.0, driver.battery_percent - energy_percent)
                outgoing[driver.zone_id] += 1
                driver.status = "busy"
                driver.destination_zone_id = destination_zone_id
                driver.available_at = timestamp + timedelta(minutes=duration_minutes)
                driver.idle_since = None
                matched += 1
                deadhead_m += pickup_distance
                wait_seconds_total += (timestamp - request["request_time"]).total_seconds()
        return outgoing, matched, deadhead_m, wait_seconds_total

    def _acceptance_records(
        self, timestamp: datetime, demand_counts: Dict[str, int]
    ) -> List[dict]:
        idle = [driver for driver in self.drivers if driver.status == "idle"]
        if not idle:
            return []
        idle_count = Counter(driver.zone_id for driver in idle)
        targets = sorted(
            (
                (zone_id, demand_counts.get(zone_id, 0) - idle_count[zone_id])
                for zone_id in self.zone_ids
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        records = []
        used_drivers = set()
        for target_zone_id, deficit in targets:
            if deficit <= 0:
                continue
            target_zone = self.zone_by_id[target_zone_id]
            candidates = sorted(
                (
                    driver for driver in idle
                    if driver.driver_id not in used_drivers
                    and self.zone_distances[(driver.zone_id, target_zone_id)]
                    <= self.config["repositioning"]["candidate_radius_m"]
                ),
                key=lambda driver: haversine_m(
                    driver.lat, driver.lng, target_zone["center_lat"], target_zone["center_lng"]
                ),
            )[: min(3, int(math.ceil(deficit)))]
            for driver in candidates:
                used_drivers.add(driver.driver_id)
                distance_m = (
                    haversine_m(driver.lat, driver.lng, target_zone["center_lat"], target_zone["center_lng"]) * 1.3
                )
                records.append(
                    generate_acceptance_record(
                        driver,
                        target_zone_id,
                        distance_m,
                        float(deficit),
                        timestamp,
                        self.rng,
                    )
                )
        return records

    def _reposition_drivers(
        self, timestamp: datetime, demand_counts: Dict[str, int], scenario: str, outgoing: Counter
    ) -> Tuple[int, float]:
        """Tuần 4 A/B testing hook — implements report.md's 3 scenarios:

        - A_PASSIVE: no-op, matching stays purely reactive (unchanged Tuần 2 behaviour).
        - B_REPOSITION_NO_RESERVE: reposition idle drivers toward deficit zones, but the
          deficit formula ignores drivers already `incoming` — demonstrating herding,
          since a zone keeps getting suggested more drivers every tick without the
          system realizing help is already on the way.
        - C_REPOSITION_SOFT_RESERVE: same, but deficit subtracts `incoming` drivers
          immediately (the soft-reserve anti-herding mechanism from Tuần 1/3).

        Candidates are ranked by `expected_acceptance_score` (the noise-free part of
        the Acceptance Model's generative formula — see generators.py) rather than raw
        distance, matching Tuần 3's "p_accept ranks candidates" design. Whether a
        suggestion actually succeeds is still a real stochastic draw
        (`generate_acceptance_record`), not guaranteed — a driver can decline.
        """
        if scenario == "A_PASSIVE":
            return 0, 0.0

        idle_by_zone = self._idle_drivers_by_zone()
        incoming_counts: Counter = Counter()
        if scenario == "C_REPOSITION_SOFT_RESERVE":
            for driver in self.drivers:
                if driver.status == "incoming" and driver.destination_zone_id:
                    incoming_counts[driver.destination_zone_id] += 1

        min_battery = float(self.config["battery"]["minimum_trip_reserve_percent"])
        candidate_radius = float(self.config["repositioning"]["candidate_radius_m"])
        targets = sorted(
            (
                (
                    zone_id,
                    demand_counts.get(zone_id, 0)
                    - len(idle_by_zone.get(zone_id, []))
                    - incoming_counts.get(zone_id, 0),
                )
                for zone_id in self.zone_ids
            ),
            key=lambda item: item[1],
            reverse=True,
        )

        used_driver_ids = set()
        repositioned = 0
        deadhead_m = 0.0
        for target_zone_id, deficit in targets:
            if deficit <= 0:
                continue
            target_zone = self.zone_by_id[target_zone_id]
            candidates = [
                driver
                for zone_id in self.nearest_zones[target_zone_id]
                if self.zone_distances[(zone_id, target_zone_id)] <= candidate_radius
                for driver in idle_by_zone.get(zone_id, [])
                if driver.driver_id not in used_driver_ids
                and driver.zone_id != target_zone_id
                and driver.battery_percent >= min_battery
            ]
            if not candidates:
                continue
            budget = min(len(candidates), max(1, math.ceil(deficit)))
            ranked = sorted(
                candidates,
                key=lambda driver: expected_acceptance_score(
                    driver,
                    haversine_m(driver.lat, driver.lng, target_zone["center_lat"], target_zone["center_lng"]) * 1.3,
                    float(deficit),
                    timestamp,
                ),
                reverse=True,
            )
            for driver in ranked[:budget]:
                used_driver_ids.add(driver.driver_id)
                distance_m = (
                    haversine_m(driver.lat, driver.lng, target_zone["center_lat"], target_zone["center_lng"]) * 1.3
                )
                record = generate_acceptance_record(
                    driver, target_zone_id, distance_m, float(deficit), timestamp, self.rng
                )
                if not record["accepted"]:
                    continue
                origin_zone_id = driver.zone_id
                travel_minutes = max(3.0, distance_m / 500.0)
                driver.status = "incoming"
                driver.destination_zone_id = target_zone_id
                driver.available_at = timestamp + timedelta(minutes=travel_minutes)
                driver.idle_since = None
                driver.battery_percent = max(0.0, driver.battery_percent - distance_m / 1000.0 * 0.32)
                idle_by_zone[origin_zone_id].remove(driver)
                outgoing[origin_zone_id] += 1
                repositioned += 1
                deadhead_m += distance_m
        return repositioned, deadhead_m

    def _driver_snapshot(self) -> List[dict]:
        return [
            {
                "driver_id": driver.driver_id,
                "zone_id": driver.zone_id,
                "lat": round(driver.lat, 7),
                "lng": round(driver.lng, 7),
                "battery_percent": round(driver.battery_percent, 2),
                "status": driver.status,
                "destination_zone_id": driver.destination_zone_id,
                "available_at": driver.available_at,
            }
            for driver in self.drivers
        ]

    @staticmethod
    def _write_partition(rows: List[dict], directory: Path, day: date) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(rows)
        frame.to_parquet(directory / f"day={day.isoformat()}.parquet", index=False)

    def run(
        self, start_date: date, days: int, output_dir: Path, scenario: str = "A_PASSIVE"
    ) -> dict:
        if days <= 0:
            raise ValueError("days must be positive")
        output_dir.mkdir(parents=True, exist_ok=True)
        self.initialize(start_date)
        tick_seconds = int(self.config["simulation"]["planning_tick_seconds"])
        ticks_per_day = 86_400 // tick_seconds
        run_totals = Counter()

        for day_offset in range(days):
            current_day = start_date + timedelta(days=day_offset)
            day_start = self._local_midnight_utc(current_day)
            weather_by_hour = generate_weather_for_day(self.rng)
            demand_rows: List[dict] = []
            supply_rows: List[dict] = []
            acceptance_rows: List[dict] = []

            for tick in range(ticks_per_day):
                timestamp = day_start + timedelta(seconds=tick * tick_seconds)
                local_time = timestamp.astimezone(self.local_tz)
                weather = weather_by_hour[local_time.hour]
                is_holiday = local_time.date() in self.vn_holidays
                self._release_drivers(timestamp)
                cancelled = self._expire_waiting_requests(timestamp)
                new_requests, demand_counts = self._generate_requests(timestamp, weather, is_holiday)
                acceptance_rows.extend(self._acceptance_records(timestamp, demand_counts))
                outgoing, matched, match_deadhead_m, wait_seconds_total = self._match_waiting_requests(
                    timestamp
                )
                repositioned, reposition_deadhead_m = self._reposition_drivers(
                    timestamp, demand_counts, scenario, outgoing
                )
                supply_rows.extend(
                    build_supply_snapshots(
                        self.drivers,
                        self.zones,
                        timestamp,
                        int(self.config["forecast"]["horizon_seconds"]),
                        outgoing,
                        demand_counts,
                    )
                )
                demand_rows.extend(new_requests)
                run_totals.update(
                    generated_requests=len(new_requests),
                    matched_requests=matched,
                    cancelled_requests=cancelled,
                    acceptance_samples=0,
                    repositioned_drivers=repositioned,
                )
                run_totals["deadhead_m"] += match_deadhead_m + reposition_deadhead_m
                run_totals["wait_seconds_total"] += wait_seconds_total
                run_totals["wait_count"] += matched
                if tick % 12 == 0:
                    decay_suggestion_counters(self.drivers)

            self._write_partition(demand_rows, output_dir / "demand_events", current_day)
            self._write_partition(supply_rows, output_dir / "supply_snapshots", current_day)
            self._write_partition(acceptance_rows, output_dir / "acceptance_history", current_day)
            run_totals.update(acceptance_samples=len(acceptance_rows))

        drivers_path = output_dir / "drivers_final.json"
        drivers_path.write_text(
            json.dumps(self._driver_snapshot(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        float_keys = {"deadhead_m", "wait_seconds_total"}
        summary = {
            "schema_version": "1.0.0",
            "seed": self.seed,
            "start_date": start_date.isoformat(),
            "days": days,
            "zone_count": len(self.zones),
            "driver_count": len(self.drivers),
            "scenario": scenario,
            **{
                key: (round(float(value), 1) if key in float_keys else int(value))
                for key, value in run_totals.items()
            },
        }
        (output_dir / "simulation_run.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary
