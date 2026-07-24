import argparse
import json
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .common import (
    PROJECT_ROOT,
    add_local_time_features,
    chronological_split,
    load_acceptance_history,
    load_config,
)
from .mlflow_tracking import log_training_run

FEATURE_COLUMNS = [
    "distance_m",
    "battery_percent",
    "idle_minutes",
    "historical_acceptance_rate",
    "recent_suggestions",
    "target_deficit",
    "hour",
    "is_weekend",
]
TARGET_COLUMN = "accepted"
# p_accept_ground_truth is the hidden generative probability used only to
# label the simulator's synthetic outcomes — never a training feature, per
# docs/week2_simulator.md.
ORACLE_COLUMN = "p_accept_ground_truth"


def build_dataset(config: dict):
    acceptance = load_acceptance_history()
    acceptance = add_local_time_features(acceptance, "timestamp", config)
    acceptance["is_weekend"] = acceptance["is_weekend"].astype(int)
    acceptance[TARGET_COLUMN] = acceptance[TARGET_COLUMN].astype(int)
    return acceptance


def evaluate(model, frame) -> dict:
    if frame.empty:
        return {"accuracy": None, "auc": None, "rows": 0}
    probabilities = model.predict_proba(frame[FEATURE_COLUMNS])[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    metrics = {
        "accuracy": round(float(accuracy_score(frame[TARGET_COLUMN], predictions)), 4),
        "auc": round(float(roc_auc_score(frame[TARGET_COLUMN], probabilities)), 4),
        "rows": int(len(frame)),
    }
    if ORACLE_COLUMN in frame.columns:
        metrics["oracle_auc"] = round(
            float(roc_auc_score(frame[TARGET_COLUMN], frame[ORACLE_COLUMN])), 4
        )
    return metrics


def train(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    seed = int(config["random_seed"])
    split_days = config["experiments"]["forecast_split_days"]

    dataset = build_dataset(config)
    train_df, val_df, test_df = chronological_split(
        dataset, "local_date", split_days["train"], split_days["validation"]
    )

    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, random_state=seed),
    )
    model.fit(train_df[FEATURE_COLUMNS], train_df[TARGET_COLUMN])

    metrics = {
        "model": "LogisticRegression (scikit-learn, StandardScaler pipeline)",
        "features": FEATURE_COLUMNS,
        "train": evaluate(model, train_df),
        "validation": evaluate(model, val_df),
        "test": evaluate(model, test_df),
    }

    model_path = output_dir / "acceptance_model.joblib"
    metrics_path = output_dir / "acceptance_metrics.json"
    joblib.dump(model, model_path)
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log_training_run(
        experiment_name="fleet-dispatch-acceptance",
        run_name="acceptance-logistic-regression",
        model=model,
        registered_model_name="fleet-dispatch-acceptance-model",
        params={
            "model": "LogisticRegression",
            "random_seed": seed,
            "max_iter": 1000,
            "features": ",".join(FEATURE_COLUMNS),
        },
        metrics=metrics,
        artifacts=[model_path, metrics_path],
        input_example=test_df[FEATURE_COLUMNS].head(5),
        pyfunc_predict_fn="predict_proba",
    )
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the Week 3 Acceptance Probability Model")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = train(args.output)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
