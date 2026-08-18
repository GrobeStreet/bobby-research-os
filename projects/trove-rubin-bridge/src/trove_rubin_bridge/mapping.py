from __future__ import annotations

from typing import Any

from .models import BrokerTarget


def build_trove_handoff(target: BrokerTarget) -> dict[str, Any]:
    reduced_data = []
    for obs in target.observations:
        value: dict[str, Any] = {"filter": obs.band}
        if obs.magnitude is not None:
            value["magnitude"] = obs.magnitude
            if obs.magnitude_error is not None:
                value["error"] = obs.magnitude_error
        elif obs.limiting_magnitude is not None:
            value["limit"] = obs.limiting_magnitude

        reduced_data.append(
            {
                "timestamp": obs.observed_at.isoformat(),
                "data_type": "photometry",
                "source_name": "Rubin/ANTARES",
                "source_location": obs.alert_id,
                "value": value,
            }
        )

    return {
        "target": {
            "name": target.lsst_dia_object_id or target.locus_id,
            "type": "SIDEREAL",
            "ra": target.ra_deg,
            "dec": target.dec_deg,
            "permissions": "PUBLIC",
        },
        "external_identity": {
            "idempotency_key": target.idempotency_key,
            "antares_locus_id": target.locus_id,
            "lsst_dia_object_id": target.lsst_dia_object_id,
        },
        "grav_wave_events": list(target.grav_wave_events),
        "reduced_data": reduced_data,
    }
