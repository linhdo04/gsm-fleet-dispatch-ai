from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Driver:
    driver_id: str
    zone_id: str
    battery_percent: float
    lat: float
    lng: float
    status: str = "idle"
    destination_zone_id: Optional[str] = None
    available_at: Optional[datetime] = None
    idle_since: Optional[datetime] = None
    acceptance_attempts: int = 0
    acceptance_successes: int = 0
    recent_suggestions: int = 0

    @property
    def historical_acceptance_rate(self) -> float:
        if self.acceptance_attempts == 0:
            return 0.5
        return self.acceptance_successes / self.acceptance_attempts
