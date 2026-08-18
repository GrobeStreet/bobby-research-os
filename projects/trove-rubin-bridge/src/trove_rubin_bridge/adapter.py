from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import BrokerTarget, Observation
from .timeutil import mjd_to_datetime


class SchemaError(ValueError):
    """Raised when the documented ANTARES boundary cannot be normalized safely."""


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _properties(obj: Any) -> dict[str, Any]:
    value = _get(obj, "properties", {})
    return dict(value or {})


def _first(props: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in props and props[key] is not None:
            return props[key]
    return None


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _scalar(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        values = [v for v in value if v is not None]
        if not values:
            return None
        if len(values) != 1:
            raise SchemaError(f"Expected one LSST object identity, found {len(values)}")
        return values[0]
    return value


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _looks_like_lsst(alert: Any, props: Mapping[str, Any]) -> bool:
    alert_id = str(_get(alert, "alert_id", _get(alert, "id", "")))
    if alert_id.lower().startswith("lsst:"):
        return True
    if any(str(k).lower().startswith("lsst_") for k in props):
        return True
    return False


def _normalize_gw_events(alert: Any) -> list[dict[str, Any]]:
    raw_events = _get(alert, "grav_wave_events", []) or []
    events: list[dict[str, Any]] = []
    for raw in raw_events:
        if isinstance(raw, Mapping):
            event = {
                "gracedb_id": raw.get("gracedb_id"),
                "contour_level": _float_or_none(raw.get("contour_level")),
                "contour_area": _float_or_none(raw.get("contour_area")),
            }
            events.append(event)
        else:
            events.append({"gracedb_id": str(raw), "contour_level": None, "contour_area": None})
    return events


def _normalize_alert(alert: Any) -> Observation | None:
    props = _properties(alert)
    if not _looks_like_lsst(alert, props):
        return None

    mjd = _get(alert, "mjd", _first(props, "lsst_diaSource_midpointMjdTai", "ant_mjd", "mjd"))
    if mjd is None:
        raise SchemaError("LSST alert is missing MJD/lsst_diaSource_midpointMjdTai/ant_mjd")

    alert_id = _get(alert, "alert_id", _get(alert, "id"))
    band = _first(props, "lsst_diaSource_band", "ant_passband", "band", "filter", "physical_filter")
    magnitude = _float_or_none(_first(props, "ant_mag", "magnitude", "mag"))
    magnitude_error = _float_or_none(
        _first(props, "ant_magerr", "ant_mag_error", "magnitude_error", "magerr")
    )
    limiting_magnitude = _float_or_none(
        _first(props, "ant_maglim", "limiting_magnitude", "diffmaglim")
    )

    return Observation(
        observed_at=mjd_to_datetime(float(mjd)),
        band=str(band) if band is not None else None,
        alert_id=str(alert_id) if alert_id is not None else None,
        magnitude=magnitude,
        magnitude_error=magnitude_error,
        limiting_magnitude=limiting_magnitude,
        grav_wave_events=_normalize_gw_events(alert),
        raw_properties=props,
    )


def _extract_lsst_id(locus_props: Mapping[str, Any]) -> str | None:
    value = _nested(locus_props, "survey", "lsst", "dia_object_id")
    if value is None:
        value = _first(
            locus_props,
            "lsst_dia_object_id",
            "lsst_object_id",
            "dia_object_id",
            "diaObjectId",
        )
    value = _scalar(value)
    return str(value) if value is not None else None


def normalize_antares_locus(locus: Any) -> BrokerTarget:
    locus_id = _get(locus, "locus_id", _get(locus, "id"))
    ra = _get(locus, "ra")
    dec = _get(locus, "dec")
    if locus_id is None or ra is None or dec is None:
        raise SchemaError("Locus requires locus_id/id, ra, and dec")

    alerts: Iterable[Any] = _get(locus, "alerts", []) or []
    observations = []
    for alert in alerts:
        normalized = _normalize_alert(alert)
        if normalized is not None:
            observations.append(normalized)

    if not observations:
        raise SchemaError("Locus contains no recognizable LSST/Rubin alerts")

    observations.sort(key=lambda o: (o.observed_at, o.alert_id or ""))
    locus_props = _properties(locus)
    lsst_id = _extract_lsst_id(locus_props)
    if lsst_id is None:
        ids_from_alerts = {
            str(o.raw_properties.get("lsst_diaSource_diaObjectId"))
            for o in observations
            if o.raw_properties.get("lsst_diaSource_diaObjectId") is not None
        }
        if len(ids_from_alerts) == 1:
            lsst_id = ids_from_alerts.pop()
        elif len(ids_from_alerts) > 1:
            raise SchemaError("LSST alerts disagree on DiaObject identity")

    gw_ids = []
    seen_gw = set()
    for obs in observations:
        for event_id in obs.gracedb_ids:
            if event_id not in seen_gw:
                seen_gw.add(event_id)
                gw_ids.append(event_id)

    tags = [str(x) for x in (_get(locus, "tags", []) or [])]

    return BrokerTarget(
        broker="ANTARES",
        locus_id=str(locus_id),
        ra_deg=float(ra),
        dec_deg=float(dec),
        first_seen_at=observations[0].observed_at,
        observations=observations,
        grav_wave_events=gw_ids,
        lsst_dia_object_id=lsst_id,
        tags=tags,
        locus_properties=locus_props,
    )
