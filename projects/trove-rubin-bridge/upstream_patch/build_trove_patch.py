from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

BRIDGE_ROOT = Path(os.environ["TROVE_RUBIN_BRIDGE_ROOT"])
TROVE_ROOT = Path(os.environ["TROVE_ROOT"])
REAL_FIXTURE = BRIDGE_ROOT / "fixtures" / "real_multi" / "antares_lsst_multi.json"
UPSTREAM_DIR = BRIDGE_ROOT / "upstream_patch"
PATCH_PATH = UPSTREAM_DIR / "trove-rubin-issue-23.patch"

RUBIN_MODULE = r'''from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timezone
from typing import Any

from astropy.time import Time
from django.db import IntegrityError, transaction
from tom_dataproducts.models import ReducedDatum
from trove_targets.models import Target

from .hooks import target_post_save

logger = logging.getLogger(__name__)

DEFER_TARGET_POST_SAVE_ATTR = "_trove_defer_target_post_save"
SOURCE_NAME = "Rubin/ANTARES"


@dataclass(frozen=True)
class RubinIngestResult:
    target_id: int | None
    target_created: bool
    observations_created: int
    observations_duplicate: int
    vetting_invocations: int


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _properties(obj: Any) -> dict[str, Any]:
    return dict(_get(obj, "properties", {}) or {})


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _scalar(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        values = [item for item in value if item is not None]
        if not values:
            return None
        if len(values) != 1:
            raise ValueError(f"Expected one Rubin DIA Object ID, found {len(values)}")
        return values[0]
    return value


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_rubin_alert(alert: Any, properties: Mapping[str, Any]) -> bool:
    alert_id = str(_get(alert, "alert_id", ""))
    return alert_id.lower().startswith("lsst:") or any(
        str(key).lower().startswith("lsst_") for key in properties
    )


def _observed_at(alert: Any, properties: Mapping[str, Any]):
    # Rubin names this field explicitly as TAI. Convert it to an aware UTC datetime
    # before storing it in TROVE. ANTARES' generic MJD is the fallback only.
    midpoint_mjd_tai = properties.get("lsst_diaSource_midpointMjdTai")
    if midpoint_mjd_tai is not None:
        return Time(float(midpoint_mjd_tai), format="mjd", scale="tai").to_datetime(
            timezone=timezone.utc
        )

    mjd = _get(alert, "mjd", _first(properties, "ant_mjd", "mjd"))
    if mjd is None:
        raise ValueError("Rubin alert is missing an observation MJD")
    return Time(float(mjd), format="mjd", scale="utc").to_datetime(
        timezone=timezone.utc
    )


def _photometry_value(properties: Mapping[str, Any]) -> dict[str, Any] | None:
    band = _first(
        properties,
        "lsst_diaSource_band",
        "ant_passband",
        "band",
        "filter",
    )
    magnitude = _float_or_none(_first(properties, "ant_mag", "magnitude", "mag"))
    magnitude_error = _float_or_none(
        _first(properties, "ant_magerr", "ant_mag_error", "magnitude_error", "magerr")
    )
    limiting_magnitude = _float_or_none(
        _first(properties, "ant_maglim", "limiting_magnitude", "diffmaglim")
    )

    value: dict[str, Any] = {"filter": str(band) if band is not None else None}
    if magnitude is not None:
        value["magnitude"] = magnitude
        if magnitude_error is not None:
            value["error"] = magnitude_error
        return value
    if limiting_magnitude is not None:
        value["limit"] = limiting_magnitude
        return value
    return None


def _extract_lsst_id(locus: Any, rubin_alerts: list[Any]) -> str | None:
    locus_properties = _properties(locus)
    value = _nested(locus_properties, "survey", "lsst", "dia_object_id")
    if value is None:
        value = _first(
            locus_properties,
            "lsst_dia_object_id",
            "lsst_object_id",
            "dia_object_id",
            "diaObjectId",
        )
    value = _scalar(value)
    if value is not None:
        return str(value)

    ids = {
        str(_properties(alert).get("lsst_diaSource_diaObjectId"))
        for alert in rubin_alerts
        if _properties(alert).get("lsst_diaSource_diaObjectId") is not None
    }
    if len(ids) > 1:
        raise ValueError("Rubin alerts disagree on DIA Object identity")
    return ids.pop() if ids else None


def _target_name(locus: Any, rubin_alerts: list[Any]) -> str:
    lsst_id = _extract_lsst_id(locus, rubin_alerts)
    if lsst_id:
        return f"LSST{lsst_id}"
    locus_id = _get(locus, "locus_id", _get(locus, "id"))
    if locus_id is None:
        raise ValueError("ANTARES locus is missing locus_id")
    return str(locus_id)


def _get_or_create_target_without_science(locus: Any, rubin_alerts: list[Any]):
    name = _target_name(locus, rubin_alerts)
    existing = Target.objects.filter(name=name).first()
    if existing is not None:
        return existing, False

    ra = _get(locus, "ra")
    dec = _get(locus, "dec")
    if ra is None or dec is None:
        raise ValueError("ANTARES locus is missing coordinates")

    try:
        with transaction.atomic():
            target = Target(
                name=name,
                type="SIDEREAL",
                ra=float(ra),
                dec=float(dec),
                permissions="PUBLIC",
            )
            setattr(target, DEFER_TARGET_POST_SAVE_ATTR, True)
            try:
                target.save()
            finally:
                if hasattr(target, DEFER_TARGET_POST_SAVE_ATTR):
                    delattr(target, DEFER_TARGET_POST_SAVE_ATTR)
        return target, True
    except IntegrityError:
        # A second consumer may have won the unique-name race.
        return Target.objects.get(name=name), False


def _persist_rubin_observations(target: Target, rubin_alerts: list[Any]) -> tuple[int, int]:
    created_count = 0
    duplicate_count = 0

    for alert in rubin_alerts:
        properties = _properties(alert)
        value = _photometry_value(properties)
        if value is None:
            continue

        alert_id = str(_get(alert, "alert_id", "") or "")
        if alert_id and ReducedDatum.objects.filter(
            target=target,
            data_type="photometry",
            source_name=SOURCE_NAME,
            source_location=alert_id,
        ).exists():
            duplicate_count += 1
            continue

        datum, created = ReducedDatum.objects.get_or_create(
            target=target,
            data_type="photometry",
            timestamp=_observed_at(alert, properties),
            value=value,
            defaults={
                "source_name": SOURCE_NAME,
                "source_location": alert_id,
            },
        )
        if created:
            created_count += 1
            continue

        duplicate_count += 1
        changed = False
        if not datum.source_name:
            datum.source_name = SOURCE_NAME
            changed = True
        if alert_id and not datum.source_location:
            datum.source_location = alert_id
            changed = True
        if changed:
            datum.save()

    return created_count, duplicate_count


def ingest_antares_rubin_locus(locus: Any) -> RubinIngestResult:
    """Persist Rubin photometry from an ANTARES locus, then run TROVE science once.

    ANTARES loci can contain cross-survey history, so only Rubin/LSST alerts are
    considered. Target creation defers TROVE's automatic target-post-save science
    until the Rubin photometry has been stored. Duplicate broker delivery is a no-op
    for vetting.
    """

    alerts = list(_get(locus, "alerts", []) or [])
    rubin_alerts = [alert for alert in alerts if _is_rubin_alert(alert, _properties(alert))]
    usable_alerts = [alert for alert in rubin_alerts if _photometry_value(_properties(alert))]

    if not usable_alerts:
        logger.info("ANTARES locus %s contains no usable Rubin photometry", _get(locus, "locus_id"))
        return RubinIngestResult(None, False, 0, 0, 0)

    with transaction.atomic():
        target, target_created = _get_or_create_target_without_science(locus, rubin_alerts)
        created_count, duplicate_count = _persist_rubin_observations(target, rubin_alerts)

        vetting_invocations = 0
        if created_count:
            # TROVE's current science work is under the hook's created=True branch.
            # The observations already exist before this call.
            target_post_save(target, created=True)
            vetting_invocations = 1

    return RubinIngestResult(
        target_id=target.id,
        target_created=target_created,
        observations_created=created_count,
        observations_duplicate=duplicate_count,
        vetting_invocations=vetting_invocations,
    )
'''

TEST_MODULE = r'''import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from astropy.time import Time
from django.conf import settings
from tom_dataproducts.models import ReducedDatum
from trove_targets.models import Target

from custom_code import hooks
from custom_code.alertstream_handlers import handle_antares_rubin_locus
from custom_code import rubin_alerts

FIXTURE = Path(__file__).parent / "data" / "antares_rubin_locus.json"
DB_MARK = pytest.mark.django_db(transaction=True, databases=["default", "catalogs"])


def _as_locus(payload):
    locus = payload["locus"]
    alerts = [SimpleNamespace(**alert) for alert in locus["alerts"]]
    return SimpleNamespace(
        locus_id=locus["locus_id"],
        ra=locus["ra"],
        dec=locus["dec"],
        properties=locus["properties"],
        tags=locus.get("tags", []),
        alerts=alerts,
    )


def _load_locus():
    return _as_locus(json.loads(FIXTURE.read_text()))


@DB_MARK
def test_real_antares_locus_ingests_only_rubin_and_duplicate_delivery_does_not_revet(monkeypatch):
    locus = _load_locus()
    vet_counts = []

    def fake_target_post_save(target, *, created=True, **kwargs):
        assert created is True
        vet_counts.append(
            ReducedDatum.objects.filter(
                target=target,
                data_type="photometry",
                source_name="Rubin/ANTARES",
            ).count()
        )
        return [], None

    monkeypatch.setattr(rubin_alerts, "target_post_save", fake_target_post_save)

    first = handle_antares_rubin_locus(locus)
    assert first.target_created is True
    assert first.observations_created == 2
    assert first.vetting_invocations == 1
    assert vet_counts == [2]

    target = Target.objects.get(pk=first.target_id)
    rows = ReducedDatum.objects.filter(target=target, source_name="Rubin/ANTARES")
    assert rows.count() == 2
    assert all(row.source_location.startswith("lsst:") for row in rows)

    second = handle_antares_rubin_locus(locus)
    assert second.target_created is False
    assert second.observations_created == 0
    assert second.observations_duplicate == 2
    assert second.vetting_invocations == 0
    assert vet_counts == [2]
    assert ReducedDatum.objects.filter(target=target).count() == 2


@DB_MARK
def test_real_incremental_rubin_delivery_vets_once_per_new_batch(monkeypatch):
    payload = json.loads(FIXTURE.read_text())
    rubin_alerts = [
        alert for alert in payload["locus"]["alerts"] if alert["alert_id"].startswith("lsst:")
    ]
    non_rubin = [
        alert for alert in payload["locus"]["alerts"] if not alert["alert_id"].startswith("lsst:")
    ]
    assert len(rubin_alerts) == 2
    assert non_rubin

    partial_payload = deepcopy(payload)
    partial_payload["locus"]["alerts"] = non_rubin[:1] + rubin_alerts[:1]

    counts = []

    def fake_target_post_save(target, *, created=True, **kwargs):
        counts.append(ReducedDatum.objects.filter(target=target).count())
        return [], None

    monkeypatch.setattr(rubin_alerts_module := rubin_alerts, "target_post_save", fake_target_post_save)

    first = handle_antares_rubin_locus(_as_locus(partial_payload))
    second = handle_antares_rubin_locus(_as_locus(payload))
    third = handle_antares_rubin_locus(_as_locus(payload))

    assert first.observations_created == 1
    assert first.vetting_invocations == 1
    assert second.observations_created == 1
    assert second.observations_duplicate == 1
    assert second.vetting_invocations == 1
    assert third.observations_created == 0
    assert third.observations_duplicate == 2
    assert third.vetting_invocations == 0
    assert counts == [1, 2]


@DB_MARK
def test_defer_marker_prevents_premature_trove_science(monkeypatch):
    calls = []
    monkeypatch.setattr(hooks, "vet_basic", lambda *args, **kwargs: calls.append("vet_basic"))
    monkeypatch.setattr(hooks, "associate_nle_with_target", lambda *args, **kwargs: [])

    target = SimpleNamespace(_trove_defer_target_post_save=True)
    messages, status = hooks.target_post_save(target, created=True)

    assert messages == []
    assert status is None
    assert calls == []


def test_rubin_midpoint_mjd_tai_is_converted_to_utc():
    payload = json.loads(FIXTURE.read_text())
    alert = next(
        alert for alert in payload["locus"]["alerts"] if alert["alert_id"].startswith("lsst:")
    )
    properties = alert["properties"]
    stored = rubin_alerts._observed_at(SimpleNamespace(**alert), properties)
    expected = Time(
        float(properties["lsst_diaSource_midpointMjdTai"]),
        format="mjd",
        scale="tai",
    ).to_datetime(timezone=stored.tzinfo)
    assert stored == expected
'''


def insert_after(text: str, needle: str, addition: str) -> str:
    if needle not in text:
        raise RuntimeError(f"Insertion point not found: {needle!r}")
    return text.replace(needle, needle + addition, 1)


def build_fixture() -> None:
    payload = json.loads(REAL_FIXTURE.read_text())
    locus = payload["locus"]
    rubin = [a for a in locus["alerts"] if str(a.get("alert_id", "")).startswith("lsst:")]
    non_rubin = [a for a in locus["alerts"] if not str(a.get("alert_id", "")).startswith("lsst:")]
    if len(rubin) < 2 or not non_rubin:
        raise RuntimeError("Frozen live fixture does not contain expected 2 Rubin + cross-survey alerts")

    compact = {
        "fixture_provenance": {
            **payload.get("fixture_provenance", {}),
            "derived_for_upstream_test": True,
            "derivation": "one real non-Rubin alert plus both real Rubin alerts from frozen ANTARES locus",
        },
        "locus": {
            "locus_id": locus["locus_id"],
            "ra": locus["ra"],
            "dec": locus["dec"],
            "properties": locus["properties"],
            "tags": locus.get("tags", []),
            "alerts": [non_rubin[0], *rubin[:2]],
        },
    }
    out = TROVE_ROOT / "tests" / "data" / "antares_rubin_locus.json"
    out.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n")


def modify_trove() -> None:
    # 1. New self-contained Rubin/ANTARES ingestion implementation.
    (TROVE_ROOT / "custom_code" / "rubin_alerts.py").write_text(RUBIN_MODULE)

    # 2. Tiny instance-local defer guard in the existing target hook.
    hooks_path = TROVE_ROOT / "custom_code" / "hooks.py"
    hooks = hooks_path.read_text()
    hook_needle = '    logger.info("Target post save hook: %s created: %s", target, created)\n\n'
    hooks = insert_after(
        hooks,
        hook_needle,
        '    if getattr(target, "_trove_defer_target_post_save", False):\n'
        '        return [], None\n\n',
    )
    hooks_path.write_text(hooks)

    # 3. Real alertstream handler entrypoint.
    handler_path = TROVE_ROOT / "custom_code" / "alertstream_handlers.py"
    handler = handler_path.read_text()
    import_needle = "from .hooks import (\n    target_post_save,\n    associate_targets_with_nle,\n)\n"
    handler = insert_after(
        handler,
        import_needle,
        "from .rubin_alerts import ingest_antares_rubin_locus\n",
    )
    handler += '''\n\ndef handle_antares_rubin_locus(locus):\n    """Ingest a Rubin/LSST ANTARES locus and run TROVE vetting only for new evidence."""\n    result = ingest_antares_rubin_locus(locus)\n    logger.info(\n        "ANTARES Rubin locus %s: target_created=%s observations_created=%s "\n        "duplicates=%s vetting_invocations=%s",\n        getattr(locus, "locus_id", None),\n        result.target_created,\n        result.observations_created,\n        result.observations_duplicate,\n        result.vetting_invocations,\n    )\n    return result\n'''
    handler_path.write_text(handler)

    # 4. Opt-in ANTARES settings. Existing deployments remain unchanged unless all
    # required settings are supplied.
    settings_path = TROVE_ROOT / "trove_tom" / "settings.py"
    settings = settings_path.read_text()
    stream_needle = '''ALERT_STREAMS = [\n    {\n        "ACTIVE": True,\n        "NAME": "tom_alertstreams.alertstreams.hopskotch.HopskotchAlertStream",\n        "OPTIONS": {\n            "URL": "kafka://kafka.scimma.org/",\n            "GROUP_ID": os.getenv("SCIMMA_AUTH_USERNAME", SCIMMA_AUTH_USERNAME)\n            + "-"\n            + os.getenv("HOPSKOTCH_GROUP_ID", HOPSKOTCH_GROUP_ID),\n            "USERNAME": os.getenv("SCIMMA_AUTH_USERNAME", SCIMMA_AUTH_USERNAME),\n            "PASSWORD": os.getenv("SCIMMA_AUTH_PASSWORD", SCIMMA_AUTH_PASSWORD),\n            "TOPIC_HANDLERS": {\n                "gcn.notices.einstein_probe.wxt.alert": "custom_code.alertstream_handlers.handle_einstein_probe_alert",\n                "igwn.gwalert": "custom_code.alertstream_handlers.handle_message_and_send_alerts",\n                "icecube.HE-tracks": "tom_alertstreams.alertstreams.hopskotch.alert_logger",\n            },\n        },\n    },\n]\n'''
    stream_addition = '''\n_antares_api_key = os.getenv("ANTARES_API_KEY", globals().get("ANTARES_API_KEY", ""))\n_antares_api_secret = os.getenv(\n    "ANTARES_API_SECRET", globals().get("ANTARES_API_SECRET", "")\n)\n_antares_rubin_topic = os.getenv(\n    "ANTARES_RUBIN_TOPIC", globals().get("ANTARES_RUBIN_TOPIC", "")\n)\n_antares_group = os.getenv("ANTARES_GROUP", globals().get("ANTARES_GROUP", ""))\n\nif _antares_api_key and _antares_api_secret and _antares_rubin_topic:\n    _antares_options = {\n        "API_KEY": _antares_api_key,\n        "API_SECRET": _antares_api_secret,\n        "TOPIC_HANDLERS": {\n            _antares_rubin_topic: "custom_code.alertstream_handlers.handle_antares_rubin_locus"\n        },\n    }\n    if _antares_group:\n        _antares_options["GROUP"] = _antares_group\n\n    ALERT_STREAMS.append(\n        {\n            "ACTIVE": True,\n            "NAME": "tom_alertstreams.alertstreams.antares.AntaresAlertStream",\n            "OPTIONS": _antares_options,\n        }\n    )\n'''
    settings = insert_after(settings, stream_needle, stream_addition)
    settings_path.write_text(settings)

    # 5. Operator-facing configuration template.
    local_path = TROVE_ROOT / "trove_tom" / "settings_local.template.py"
    local = local_path.read_text()
    local_needle = "ATLAS_API_KEY = ''      # API key for the ATLAS forced photometry server\n"
    local = insert_after(
        local,
        local_needle,
        "ANTARES_API_KEY = ''    # ANTARES streaming API key\n"
        "ANTARES_API_SECRET = '' # ANTARES streaming API secret\n"
        "ANTARES_RUBIN_TOPIC = '' # ANTARES Kafka output topic for Rubin loci selected for TROVE\n"
        "ANTARES_GROUP = ''      # optional ANTARES Kafka consumer group\n",
    )
    local_path.write_text(local)

    # 6. Tests + compact fixture derived from the frozen live ANTARES locus.
    (TROVE_ROOT / "tests" / "test_rubin_alertstream.py").write_text(TEST_MODULE)
    build_fixture()


def generate_patch() -> None:
    UPSTREAM_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary"],
        cwd=TROVE_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    PATCH_PATH.write_text(result.stdout)
    if not result.stdout.strip():
        raise RuntimeError("Generated upstream patch is empty")

    changed = subprocess.run(
        ["git", "status", "--short"],
        cwd=TROVE_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    (UPSTREAM_DIR / "changed-files.txt").write_text(changed)


if __name__ == "__main__":
    modify_trove()
    generate_patch()
    print(PATCH_PATH)
