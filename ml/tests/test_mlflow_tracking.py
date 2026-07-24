import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from ml.mlflow_tracking import (
    DEFAULT_TRACKING_URI,
    _flatten_numeric_metrics,
    log_training_run,
)


class MlflowTrackingTests(unittest.TestCase):
    def test_default_uri_uses_ipv4_loopback(self):
        self.assertEqual(DEFAULT_TRACKING_URI, "http://127.0.0.1:5000")

    def test_flatten_metrics_keeps_only_finite_numbers(self):
        self.assertEqual(
            _flatten_numeric_metrics(
                {
                    "test": {"mae": 1.25, "rows": 10},
                    "enabled": True,
                    "missing": None,
                    "nan": math.nan,
                    "label": "model",
                }
            ),
            {"test.mae": 1.25, "test.rows": 10.0},
        )

    @patch("ml.mlflow_tracking.mlflow.sklearn.log_model")
    @patch("ml.mlflow_tracking.mlflow.log_artifact")
    @patch("ml.mlflow_tracking.mlflow.log_metrics")
    @patch("ml.mlflow_tracking.mlflow.log_params")
    @patch("ml.mlflow_tracking.mlflow.set_tags")
    @patch("ml.mlflow_tracking.mlflow.start_run")
    @patch("ml.mlflow_tracking.mlflow.set_experiment")
    @patch("ml.mlflow_tracking.mlflow.set_tracking_uri")
    def test_logs_signature_example_and_artifact(
        self,
        set_tracking_uri,
        set_experiment,
        start_run,
        set_tags,
        log_params,
        log_metrics,
        log_artifact,
        log_model,
    ):
        run = MagicMock()
        run.info.run_id = "run-123"
        start_run.return_value.__enter__.return_value = run
        model = MagicMock()
        model.predict.return_value = [1.0, 2.0]
        example = pd.DataFrame({"feature": [1.0, 2.0]})

        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "metrics.json"
            artifact.write_text("{}", encoding="utf-8")
            run_id = log_training_run(
                experiment_name="experiment",
                run_name="run",
                model=model,
                registered_model_name="registered-model",
                params={"max_iter": 10},
                metrics={"test": {"mae": 1.0}},
                artifacts=[artifact],
                input_example=example,
            )

        self.assertEqual(run_id, "run-123")
        set_tracking_uri.assert_called_once_with(DEFAULT_TRACKING_URI)
        set_experiment.assert_called_once_with("experiment")
        log_artifact.assert_called_once_with(
            str(artifact), artifact_path="training-artifacts"
        )
        kwargs = log_model.call_args.kwargs
        self.assertEqual(kwargs["registered_model_name"], "registered-model")
        pd.testing.assert_frame_equal(kwargs["input_example"], example)
        self.assertIsNotNone(kwargs["signature"])


if __name__ == "__main__":
    unittest.main()
