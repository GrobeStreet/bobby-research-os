from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    band: str | None
    alert_id: str | None
    magnitude: float | None = None
    magnitude_error: float | None = None
    limiting_magnitude: float | None = None
    survey: str = "LSST"
    raw_properties: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))

    @property
    def dedupe_key(self) -> tuple[Any, ...]:
        if self.alert_id:
            return (self.survey, self.alert_id)
        return (
            self.survey,
            self.observed_at,
            self.band,
            self.magnitude,
            self.limiting_magnitude,
        )


@dataclass
class BrokerTarget:
    broker: str
    locus_id: str
    ra_deg: float
    dec_deg: float
    first_seen_at: datetime
    observations: list[Observation] = field(default_factory=list)
    grav_wave_events: list[str] = field(default_factory=list)
    lsst_dia_object_id: str | None = None
    tags: list[str] = field(default_factory=list)
    locus_properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.first_seen_at = as_utc(self.first_seen_at)

    @property
    def idempotency_key(self) -> str:
        return f"ANTARES:{self.locus_id}"

    def observations_as_of(self, as_of: datetime) -> list[Observation]:
        cutoff = as_utc(as_of)
        return [o for o in self.observations if o.observed_at <= cutoff]
