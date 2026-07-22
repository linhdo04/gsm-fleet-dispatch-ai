import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

from .common import PROJECT_ROOT, load_config, load_zones
from .repositioning_suggester import build_zone_distances

NUMERIC_FEATURES = ["distance_m", "hour", "day_of_week", "is_weekend", "is_holiday"]
CATEGORICAL_FEATURES = ["weather", "origin_zone_type", "destination_zone_type"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET_COLUMN = "duration_minutes"

WEATHER_OPTIONS = ["clear", "cloudy", "rain", "heavy_rain"]
BASE_SPEED_M_PER_MIN = 420.0  # same baseline speed constant already used in simulator/engine.py


def traffic_factor(hour: int) -> float:
    """Congestion multiplier by hour of day — a stand-in for real traffic
    data (no live traffic feed available in this environment)."""
    if 7 <= hour < 9 or 17 <= hour < 19:
        return 1.6
    if 9 <= hour < 17:
        return 1.15
    if 0 <= hour < 5:
        return 0.8
    return 1.0


def weather_speed_multiplier(weather: str) -> float:
    return {"clear": 1.0, "cloudy": 1.05, "rain": 1.3, "heavy_rain": 1.6}.get(weather, 1.0)


def generate_training_trips(config: dict, zones: pd.DataFrame, rows: int, seed: int) -> pd.DataFrame:
    """Synthetic route-cost dataset — decoupled from the live simulator's
    own matching duration (report.md is explicit that Cost Prediction
    training uses simulated route cost data, not the matching engine's
    internal state), because the simulator never persisted a trip-level
    duration dataset. Congestion combines traffic_factor(hour) and
    weather_speed_multiplier() with an exponent > 1 so the two interact
    *non-linearly* — e.g. rain during rush hour is worse than the sum of
    rain alone + rush hour alone — matching report.md's requirement."""
    rng = np.random.default_rng(seed)
    full_zones = pd.DataFrame(json.loads((PROJECT_ROOT / "data" / "hanoi_zones.json").read_text(encoding="utf-8")))
    zone_distances = build_zone_distances(full_zones[["zone_id", "center_lat", "center_lng"]])
    zone_ids = zones["zone_id"].tolist()
    zone_type_by_id = dict(zip(zones["zone_id"], zones["zone_type"]))

    origin_idx = rng.integers(0, len(zone_ids), size=rows)
    dest_idx = rng.integers(0, len(zone_ids), size=rows)
    hours = rng.integers(0, 24, size=rows)
    day_of_week = rng.integers(0, 7, size=rows)
    weather = rng.choice(WEATHER_OPTIONS, size=rows, p=[0.55, 0.25, 0.15, 0.05])
    is_holiday = rng.random(rows) < float(config["demand"].get("holiday_multiplier", 1.2)) / 20.0

    records = []
    for i in range(rows):
        origin_zone_id = zone_ids[origin_idx[i]]
        dest_zone_id = zone_ids[dest_idx[i]]
        distance_m = zone_distances[(origin_zone_id, dest_zone_id)] * 1.3 + 350.0
        hour = int(hours[i])
        congestion = (traffic_factor(hour) * weather_speed_multiplier(weather[i])) ** 1.3
        base_minutes = max(3.0, distance_m / BASE_SPEED_M_PER_MIN)
        noise = float(rng.lognormal(mean=0.0, sigma=0.2))
        duration_minutes = base_minutes * congestion * noise
        records.append(
            {
                "origin_zone_id": origin_zone_id,
                "destination_zone_id": dest_zone_id,
                "origin_zone_type": zone_type_by_id[origin_zone_id],
                "destination_zone_type": zone_type_by_id[dest_zone_id],
                "distance_m": round(distance_m, 1),
                "hour": hour,
                "day_of_week": int(day_of_week[i]),
                "is_weekend": int(day_of_week[i] >= 5),
                "is_holiday": int(is_holiday[i]),
                "weather": weather[i],
                "duration_minutes": round(duration_minutes, 2),
            }
        )
    frame = pd.DataFrame(records)
    for col in CATEGORICAL_FEATURES:
        frame[col] = frame[col].astype("category")
    return frame


def naive_linear_baseline_mae(frame: pd.DataFrame) -> float:
    """The `w1*distance + w2*wait + w3*battery` fixed-formula baseline
    report.md says the Cost Prediction Model should replace — approximated
    here by pure distance/speed with no traffic or weather term at all."""
    predicted = np.maximum(3.0, frame["distance_m"] / BASE_SPEED_M_PER_MIN)
    return float(mean_absolute_error(frame[TARGET_COLUMN], predicted))


def train(output_dir: Path, rows: int = 40_000) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    seed = int(config["random_seed"])
    zones = load_zones()

    dataset = generate_training_trips(config, zones, rows, seed)
    train_df, test_df = train_test_split(dataset, test_size=0.2, random_state=seed)

    model = HistGradientBoostingRegressor(
        categorical_features="from_dtype", max_iter=300, max_depth=8, learning_rate=0.08, random_state=seed
    )
    model.fit(train_df[FEATURE_COLUMNS], train_df[TARGET_COLUMN])

    predictions = model.predict(test_df[FEATURE_COLUMNS])
    metrics = {
        "model": "HistGradientBoostingRegressor (scikit-learn — thay thế LightGBM/XGBoost)",
        "target": TARGET_COLUMN,
        "features": FEATURE_COLUMNS,
        "rows": {"train": len(train_df), "test": len(test_df)},
        "test_mae_minutes": round(mean_absolute_error(test_df[TARGET_COLUMN], predictions), 3),
        "naive_linear_baseline_mae_minutes": round(naive_linear_baseline_mae(test_df), 3),
    }

    joblib.dump(model, output_dir / "cost_model.joblib")
    (output_dir / "cost_model_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics


def predicted_segment_cost(model, origin_zone_type: str, destination_zone_type: str, distance_m: float, hour: int, day_of_week: int, weather: str, is_holiday: bool) -> float:
    """`predicted_segment_cost(origin, destination, context)` from report.md's
    Matching Engine design — thin wrapper so callers don't need to know the
    model's internal feature layout."""
    frame = pd.DataFrame(
        [
            {
                "distance_m": distance_m,
                "hour": hour,
                "day_of_week": day_of_week,
                "is_weekend": int(day_of_week >= 5),
                "is_holiday": int(is_holiday),
                "weather": weather,
                "origin_zone_type": origin_zone_type,
                "destination_zone_type": destination_zone_type,
            }
        ]
    )
    for col in CATEGORICAL_FEATURES:
        frame[col] = frame[col].astype("category")
    return float(model.predict(frame[FEATURE_COLUMNS])[0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the Week 4 Cost Prediction Model")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    parser.add_argument("--rows", type=int, default=40_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = train(args.output, args.rows)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
