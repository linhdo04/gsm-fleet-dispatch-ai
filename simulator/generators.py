import math
from datetime import datetime
from typing import Dict, Iterable, List

import numpy as np

from .geo import random_point_in_zone
from .models import Driver


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def generate_drivers(
    zones: List[dict], count: int, start_time: datetime, rng: np.random.Generator
) -> List[Driver]:
    weights = np.array([zone["base_demand_weight"] for zone in zones], dtype=float)
    weights /= weights.sum()
    zone_indexes = rng.choice(len(zones), size=count, p=weights)
    drivers = []
    for index, zone_index in enumerate(zone_indexes, start=1):
        zone = zones[int(zone_index)]
        battery = float(np.clip(rng.beta(5.0, 2.0) * 100.0, 12.0, 100.0))
        status = "charging" if battery < 20.0 else "idle"
        lat, lng = random_point_in_zone(zone, rng)
        drivers.append(
            Driver(
                driver_id=f"D{index:04d}",
                zone_id=zone["zone_id"],
                battery_percent=round(battery, 2),
                lat=lat,
                lng=lng,
                status=status,
                available_at=start_time if status == "idle" else None,
                idle_since=start_time if status == "idle" else None,
            )
        )
    return drivers


def time_profile_multiplier(zone_type: str, hour: float, is_weekend: bool) -> float:
    if zone_type == "office":
        if 7 <= hour < 9:
            return 1.45
        if 17 <= hour < 19:
            return 1.55
        return 0.82 if is_weekend else 1.0
    if zone_type == "residential":
        if 6 <= hour < 9 or 17 <= hour < 21:
            return 1.35
    elif zone_type == "commercial":
        if 18 <= hour < 23:
            return 1.5
        if is_weekend and 10 <= hour < 23:
            return 1.3
    elif zone_type == "transport_hub":
        if 5 <= hour < 8 or 20 <= hour < 23:
            return 1.5
    elif zone_type == "university":
        if not is_weekend and (7 <= hour < 9 or 16 <= hour < 18):
            return 1.4
        return 0.75 if is_weekend else 1.0
    elif zone_type == "central_business":
        return 1.25 if 8 <= hour < 22 else 0.8
    elif zone_type == "peripheral":
        return 0.78
    return 1.0


def global_peak_multiplier(hour: float, config: dict) -> float:
    if 7 <= hour < 9:
        return float(config["morning_peak_multiplier"])
    if 17 <= hour < 19:
        return float(config["evening_peak_multiplier"])
    if 0 <= hour < 5:
        return 0.28
    if 5 <= hour < 7 or 22 <= hour < 24:
        return 0.58
    return 1.0


def demand_counts_by_zone(
    zones: List[dict], timestamp: datetime, weather: str, is_holiday: bool,
    config: dict, tick_seconds: int, rng: np.random.Generator
) -> Dict[str, int]:
    local_hour = timestamp.hour + timestamp.minute / 60.0
    is_weekend = timestamp.weekday() >= 5
    raw_weights = np.array(
        [
            zone["base_demand_weight"]
            * time_profile_multiplier(zone["zone_type"], local_hour, is_weekend)
            for zone in zones
        ],
        dtype=float,
    )
    raw_weights /= raw_weights.sum()
    hourly_rate = float(config["normal_requests_per_hour"])
    hourly_rate *= global_peak_multiplier(local_hour, config)
    if weather in {"rain", "heavy_rain", "storm"}:
        hourly_rate *= float(config["rain_multiplier"])
    if is_holiday:
        hourly_rate *= float(config["holiday_multiplier"])
    total_lambda = hourly_rate * tick_seconds / 3600.0
    counts = rng.poisson(total_lambda * raw_weights)
    return {zone["zone_id"]: int(count) for zone, count in zip(zones, counts)}


def generate_weather_for_day(rng: np.random.Generator) -> List[str]:
    roll = rng.random()
    if roll < 0.08:
        return ["heavy_rain"] * 24
    if roll < 0.28:
        start = int(rng.integers(14, 19))
        duration = int(rng.integers(2, 6))
        return ["rain" if start <= hour < start + duration else "cloudy" for hour in range(24)]
    if roll < 0.52:
        return ["cloudy"] * 24
    return ["clear"] * 24


def _idle_minutes(driver: Driver, timestamp: datetime) -> float:
    if driver.idle_since is None:
        return 0.0
    return max(0.0, (timestamp - driver.idle_since).total_seconds() / 60.0)


def expected_acceptance_score(
    driver: Driver, distance_m: float, target_deficit: float, timestamp: datetime
) -> float:
    """The systematic (noise-free) part of the acceptance score — i.e. the
    best a model can predict from observable features alone, since the real
    outcome also depends on a per-instance noise term no model can see (see
    `generate_acceptance_record`). Used to *rank* repositioning candidates
    (in `engine.py`) without peeking at the hidden Bernoulli draw that
    decides whether a given suggestion is actually accepted."""
    idle_minutes = _idle_minutes(driver, timestamp)
    return (
        0.9
        - 0.00042 * distance_m
        + 0.018 * (driver.battery_percent - 50.0)
        + 0.018 * min(idle_minutes, 30.0)
        + 0.055 * min(target_deficit, 15.0)
        + 0.9 * (driver.historical_acceptance_rate - 0.5)
        - 0.35 * driver.recent_suggestions
    )


def generate_acceptance_record(
    driver: Driver, target_zone_id: str, distance_m: float, target_deficit: float,
    timestamp: datetime, rng: np.random.Generator
) -> dict:
    idle_minutes = _idle_minutes(driver, timestamp)
    score = expected_acceptance_score(driver, distance_m, target_deficit, timestamp) + float(
        rng.normal(0.0, 0.28)
    )
    probability = sigmoid(score)
    accepted = bool(rng.random() < probability)
    driver.acceptance_attempts += 1
    driver.acceptance_successes += int(accepted)
    driver.recent_suggestions = min(3, driver.recent_suggestions + 1)
    return {
        "timestamp": timestamp,
        "driver_id": driver.driver_id,
        "from_zone_id": driver.zone_id,
        "target_zone_id": target_zone_id,
        "distance_m": round(distance_m, 1),
        "battery_percent": round(driver.battery_percent, 2),
        "idle_minutes": round(idle_minutes, 2),
        "historical_acceptance_rate": round(driver.historical_acceptance_rate, 4),
        "recent_suggestions": driver.recent_suggestions,
        "target_deficit": round(target_deficit, 2),
        "p_accept_ground_truth": round(probability, 6),
        "accepted": accepted,
    }


def decay_suggestion_counters(drivers: Iterable[Driver]) -> None:
    for driver in drivers:
        driver.recent_suggestions = max(0, driver.recent_suggestions - 1)
