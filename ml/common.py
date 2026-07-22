import json
from pathlib import Path
from typing import Tuple

import holidays
import pandas as pd
from zoneinfo import ZoneInfo

from simulator.validate_outputs import read_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "generated"
CONFIG_PATH = PROJECT_ROOT / "data" / "simulation_config.json"
ZONES_PATH = PROJECT_ROOT / "data" / "hanoi_zones.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_zones() -> pd.DataFrame:
    zones = json.loads(ZONES_PATH.read_text(encoding="utf-8"))
    frame = pd.DataFrame(zones)[["zone_id", "zone_type", "base_demand_weight", "peak_profile"]]
    return frame


def load_demand_events(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return read_dataset(data_dir / "demand_events")


def load_supply_snapshots(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return read_dataset(data_dir / "supply_snapshots")


def load_acceptance_history(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return read_dataset(data_dir / "acceptance_history")


def add_local_time_features(df: pd.DataFrame, timestamp_col: str, config: dict) -> pd.DataFrame:
    local_tz = ZoneInfo(config["timezone"])
    local_time = df[timestamp_col].dt.tz_convert(local_tz)
    df = df.copy()
    df["local_date"] = local_time.dt.date
    df["hour"] = local_time.dt.hour
    df["day_of_week"] = local_time.dt.dayofweek
    df["is_weekend"] = df["day_of_week"] >= 5
    return df


def add_holiday_feature(df: pd.DataFrame, date_col: str = "local_date") -> pd.DataFrame:
    vn_holidays = holidays.country_holidays("VN")
    df = df.copy()
    df["is_holiday"] = df[date_col].apply(lambda d: d in vn_holidays)
    return df


def build_hourly_weather_lookup(demand_events: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Weather is generated once per city per local hour, so any request
    recorded within (local_date, hour) carries the weather label for that
    slot. Grouping demand_events gives a lookup usable by datasets (like
    supply_snapshots) that were not tagged with weather at generation time."""
    tagged = add_local_time_features(demand_events, "request_time", config)
    lookup = (
        tagged.groupby(["local_date", "hour"])["weather"]
        .agg(lambda values: values.mode().iat[0])
        .reset_index()
    )
    return lookup


def attach_weather(df: pd.DataFrame, weather_lookup: pd.DataFrame) -> pd.DataFrame:
    merged = df.merge(weather_lookup, on=["local_date", "hour"], how="left")
    merged["weather"] = merged["weather"].fillna("clear")
    return merged


def chronological_split(
    df: pd.DataFrame, date_col: str, train_days: int, val_days: int
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ordered_days = sorted(df[date_col].unique())
    train_cutoff = ordered_days[train_days - 1]
    val_cutoff = ordered_days[train_days + val_days - 1]
    train = df[df[date_col] <= train_cutoff]
    val = df[(df[date_col] > train_cutoff) & (df[date_col] <= val_cutoff)]
    test = df[df[date_col] > val_cutoff]
    return train, val, test
