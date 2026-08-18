from __future__ import annotations

from datetime import datetime

from .models import BrokerTarget, as_utc


def eligible_for_event(
    target: BrokerTarget,
    event_id: str,
    event_time: datetime,
    min_days: float = -1.0,
    max_days: float = 10.0,
) -> bool:
    if event_id not in target.grav_wave_events:
        return False
    delta_days = (target.first_seen_at - as_utc(event_time)).total_seconds() / 86400.0
    return min_days < delta_days < max_days
