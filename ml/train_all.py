import argparse
import json
from pathlib import Path

from . import acceptance_model, forecast_model, repositioning_suggester
from .common import PROJECT_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full Week 3 Forecast + Suggester pipeline end-to-end")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ml" / "artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    print("== 1/3 Demand Forecast Model ==")
    forecast_metrics = forecast_model.train(args.output)
    print(json.dumps(forecast_metrics, ensure_ascii=False, indent=2))

    print("\n== 2/3 Acceptance Probability Model ==")
    acceptance_metrics = acceptance_model.train(args.output)
    print(json.dumps(acceptance_metrics, ensure_ascii=False, indent=2))

    print("\n== 3/3 Repositioning Suggester demo ==")
    suggester_summary = repositioning_suggester.run(args.output)
    print(json.dumps(suggester_summary, ensure_ascii=False, indent=2))

    (args.output / "week3_run_summary.json").write_text(
        json.dumps(
            {
                "forecast": forecast_metrics,
                "acceptance": acceptance_metrics,
                "repositioning_suggester": suggester_summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
