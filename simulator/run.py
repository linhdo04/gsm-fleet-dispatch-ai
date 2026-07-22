import argparse
import json
from datetime import date
from pathlib import Path

from simulator.engine import FleetSimulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the GSM synthetic fleet simulator")
    parser.add_argument("--days", type=int, default=1, help="Number of consecutive days")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 5))
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output", type=Path, default=Path("data/generated"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    simulator = FleetSimulator(seed=args.seed)
    summary = simulator.run(args.start_date, args.days, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
