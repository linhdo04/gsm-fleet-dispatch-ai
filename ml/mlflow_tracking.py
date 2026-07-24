import math
import os
from pathlib import Path
from typing import Any, Iterable

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.models import infer_signature
from pandas.api.types import is_integer_dtype

DEFAULT_TRACKING_URI = "http://127.0.0.1:5000"


def _flatten_numeric_metrics(
    values: dict[str, Any], prefix: str = ""
) -> dict[str, float]:
    flattened: dict[str, float] = {}
    for key, value in values.items():
        metric_name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened.update(_flatten_numeric_metrics(value, metric_name))
        elif (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value is not None
        ):
            numeric_value = float(value)
            if math.isfinite(numeric_value):
                flattened[metric_name] = numeric_value
    return flattened


def log_training_run(
    *,
    experiment_name: str,
    run_name: str,
    model: Any,
    registered_model_name: str,
    params: dict[str, Any],
    metrics: dict[str, Any],
    artifacts: Iterable[Path],
    input_example: pd.DataFrame,
    pyfunc_predict_fn: str = "predict",
) -> str:
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    # Pandas date accessors commonly produce int32, while JSON request bodies
    # are materialized as int64. MLflow enforces integer widths strictly, so
    # normalizing here keeps the registered model usable by typical clients.
    input_example = input_example.copy()
    for column in input_example.columns:
        if is_integer_dtype(input_example[column].dtype):
            input_example[column] = input_example[column].astype("int64")

    prediction = getattr(model, pyfunc_predict_fn)(input_example)
    signature = infer_signature(input_example, prediction)

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags(
            {
                "project": "gsm-fleet-dispatch-ai",
                "training_entrypoint": "python-module",
            }
        )
        mlflow.log_params({key: str(value) for key, value in params.items()})
        mlflow.log_metrics(_flatten_numeric_metrics(metrics))
        for artifact in artifacts:
            if not artifact.is_file():
                raise FileNotFoundError(f"MLflow artifact does not exist: {artifact}")
            mlflow.log_artifact(str(artifact), artifact_path="training-artifacts")
        mlflow.sklearn.log_model(
            sk_model=model,
            name="model",
            registered_model_name=registered_model_name,
            serialization_format="cloudpickle",
            signature=signature,
            input_example=input_example,
            pyfunc_predict_fn=pyfunc_predict_fn,
        )
        return run.info.run_id
