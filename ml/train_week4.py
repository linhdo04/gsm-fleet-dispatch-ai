import argparse
import json
from pathlib import Path

from . import cost_model, matching_engine
from .common import PROJECT_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Week 4 pipeline: Cost Prediction Model + Matching Engine demo. "
        "Run `python -m ml.ab_testing --multi-seed` separately (takes longer)."
    )
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    print("== 1/2 Cost Prediction Model ==")
    cost_metrics = cost_model.train(args.output)
    print(json.dumps(cost_metrics, ensure_ascii=False, indent=2))

    print("\n== 2/2 Matching Engine demo (Hungarian + ride-pooling) ==")
    matching_summary = matching_engine.run_demo(args.output)
    print(json.dumps(matching_summary, ensure_ascii=False, indent=2))

    (args.output / "week4_run_summary.json").write_text(
        json.dumps(
            {"cost_model": cost_metrics, "matching_engine": matching_summary},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
