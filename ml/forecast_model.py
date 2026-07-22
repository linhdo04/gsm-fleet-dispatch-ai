import argparse
import json
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .common import (
    PROJECT_ROOT,
    add_holiday_feature,
    add_local_time_features,
    attach_weather,
    build_hourly_weather_lookup,
    chronological_split,
    load_config,
    load_demand_events,
    load_supply_snapshots,
    load_zones,
)

NUMERIC_FEATURES = ["hour", "day_of_week", "is_weekend", "is_holiday", "base_demand_weight"]
CATEGORICAL_FEATURES = ["zone_id", "zone_type", "weather", "peak_profile"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET_COLUMN = "actual_demand"


def build_dataset(config: dict) -> pd.DataFrame:
    supply = load_supply_snapshots()
    supply = add_local_time_features(supply, "timestamp", config)
    supply = add_holiday_feature(supply)

    demand_events = load_demand_events()
    weather_lookup = build_hourly_weather_lookup(demand_events, config)
    supply = attach_weather(supply, weather_lookup)

    zones = load_zones()
    supply = supply.merge(zones[["zone_id", "base_demand_weight", "peak_profile"]], on="zone_id", how="left")

    for col in NUMERIC_FEATURES:
        if supply[col].dtype == bool:
            supply[col] = supply[col].astype(int)
    for col in CATEGORICAL_FEATURES:
        supply[col] = supply[col].astype("category")

    return supply


def evaluate(model, frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"mae": None, "rmse": None, "rows": 0}
    predictions = model.predict(frame[FEATURE_COLUMNS])
    predictions = np.clip(predictions, 0, None)
    mae = mean_absolute_error(frame[TARGET_COLUMN], predictions)
    rmse = float(np.sqrt(mean_squared_error(frame[TARGET_COLUMN], predictions)))
    return {"mae": round(float(mae), 4), "rmse": round(rmse, 4), "rows": int(len(frame))}


def plot_forecast_vs_actual(model, test_frame: pd.DataFrame, output_path: Path) -> None:
    frame = test_frame.copy()
    frame["predicted_demand"] = np.clip(model.predict(frame[FEATURE_COLUMNS]), 0, None)
    by_hour = frame.groupby("hour")[[TARGET_COLUMN, "predicted_demand"]].mean().reset_index()

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(by_hour["hour"], by_hour[TARGET_COLUMN], marker="o", label="Thực tế (actual_demand)", color="#2a78d6")
    ax.plot(by_hour["hour"], by_hour["predicted_demand"], marker="o", label="Dự báo (predicted)", color="#eb6834", linestyle="--")
    ax.axvspan(7, 9, alpha=0.12, color="orange")
    ax.axvspan(17, 19, alpha=0.12, color="red")
    ax.set(
        title="Demand Forecast Model — trung bình request/zone/5 phút theo giờ (tập test)",
        xlabel="Giờ trong ngày (local)",
        ylabel="Request/zone/5 phút",
    )
    ax.set_xticks(range(0, 24, 2))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def train(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    seed = int(config["random_seed"])
    split_days = config["experiments"]["forecast_split_days"]

    dataset = build_dataset(config)
    train_df, val_df, test_df = chronological_split(
        dataset, "local_date", split_days["train"], split_days["validation"]
    )

    model = HistGradientBoostingRegressor(
        categorical_features="from_dtype",
        max_iter=300,
        max_depth=8,
        learning_rate=0.08,
        random_state=seed,
    )
    model.fit(train_df[FEATURE_COLUMNS], train_df[TARGET_COLUMN])

    metrics = {
        "model": "HistGradientBoostingRegressor (scikit-learn — thay thế XGBoost do môi trường chưa cài được xgboost)",
        "target": config["forecast"]["target"],
        "features": FEATURE_COLUMNS,
        "train": evaluate(model, train_df),
        "validation": evaluate(model, val_df),
        "test": evaluate(model, test_df),
    }

    joblib.dump(model, output_dir / "forecast_model.joblib")
    (output_dir / "forecast_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    plot_forecast_vs_actual(model, test_df, output_dir / "forecast_vs_actual.png")
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the Week 3 Demand Forecast Model")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = train(args.output)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
