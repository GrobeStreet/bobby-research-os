from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

BRIDGE_ROOT = Path(os.environ["TROVE_RUBIN_BRIDGE_ROOT"])
TROVE_ROOT = Path(os.environ["TROVE_ROOT"])
REAL_FIXTURE = BRIDGE_ROOT / "fixtures" / "real_multi" / "antares_lsst_multi.json"
OUT_DIR = BRIDGE_ROOT / "upstream_patch_v2"
PATCH_PATH = OUT_DIR / "0001-rubin-evidence-core.patch"

MODEL_ADDITION = r'''

class RubinAlertEvidence(models.Model):
    """An immutable scientific-evidence snapshot received from a Rubin alert broker.

    ``raw_alert`` is authoritative. The extracted columns exist only for indexing,
    routing, and inspection; they must not be treated as a scientific interpretation
    of the alert.
    """

    broker = models.CharField(max_length=50, default="ANTARES")
    locus_id = models.CharField(max_length=100, db_index=True)
    source_record_id = models.CharField(max_length=200, db_index=True)
    payload_sha256 = models.CharField(max_length=64, db_index=True)

    dia_object_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    dia_source_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    ss_object_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    midpoint_mjd_tai = models.FloatField(null=True, blank=True)
    band = models.CharField(max_length=20, blank=True, default="")
    psf_flux = models.FloatField(null=True, blank=True)
    psf_flux_err = models.FloatField(null=True, blank=True)
    reliability = models.FloatField(null=True, blank=True)

    quality_flags = models.JSONField(default=dict)
    grav_wave_events = models.JSONField(default=list)
    raw_alert = models.JSONField()

    received_at = models.DateTimeField(auto_now_add=True)
    last_received_at = models.DateTimeField(auto_now=True)
    delivery_count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker", "source_record_id", "payload_sha256"],
                name="unique_rubin_evidence_snapshot",
            )
        ]
        indexes = [
            models.Index(fields=["broker", "dia_object_id"], name="rubin_ev_broker_obj_idx"),
            models.Index(fields=["broker", "dia_source_id"], name="rubin_ev_broker_src_idx"),
        ]
'''

MIGRATION = r'''from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("custom_code", "0015_alter_credibleregioncontour_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="RubinAlertEvidence",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("broker", models.CharField(default="ANTARES", max_length=50)),
                ("locus_id", models.CharField(db_index=True, max_length=100)),
                ("source_record_id", models.CharField(db_index=True, max_length=200)),
                ("payload_sha256", models.CharField(db_index=True, max_length=64)),
                ("dia_object_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("dia_source_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("ss_object_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("midpoint_mjd_tai", models.FloatField(blank=True, null=True)),
                ("band", models.CharField(blank=True, default="", max_length=20)),
                ("psf_flux", models.FloatField(blank=True, null=True)),
                ("psf_flux_err", models.FloatField(blank=True, null=True)),
                ("reliability", models.FloatField(blank=True, null=True)),
                ("quality_flags", models.JSONField(default=dict)),
                ("grav_wave_events", models.JSONField(default=list)),
                ("raw_alert", models.JSONField()),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("last_received_at", models.DateTimeField(auto_now=True)),
                ("delivery_count", models.PositiveIntegerField(default=1)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["broker", "dia_object_id"], name="rubin_ev_broker_obj_idx"),
                    models.Index(fields=["broker", "dia_source_id"], name="rubin_ev_broker_src_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("broker", "source_record_id", "payload_sha256"),
                        name="unique_rubin_evidence_snapshot",
                    )
                ],
            },
        ),
    ]
'''

EVIDENCE_MODULE = r'''from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import RubinAlertEvidence

BROKER = "ANTARES"
_NONFINITE_KEY = "__trove_nonfinite_float__"
_BYTES_KEY = "__trove_bytes_base64__"


@dataclass(frozen=True)
class RubinEvidenceIngestResult:
    alerts_seen: int
    rubin_alerts_seen: int
    snapshots_created: int
    duplicate_deliveries: int
    changed_payload_snapshots: int


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _json_safe(value: Any) -> Any:
    """Encode broker values without assigning scientific meaning to them."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            label = "NaN"
        elif value > 0:
            label = "+Infinity"
        else:
            label = "-Infinity"
        return {_NONFINITE_KEY: label}
    if isinstance(value, bytes):
        return {_BYTES_KEY: base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_safe(item) for item in value), key=lambda item: repr(item))

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _json_safe(item_method())
        except (TypeError, ValueError):
            pass

    # ANTARES alert properties are expected to be JSON-like. Unknown values are
    # preserved explicitly as typed reprs rather than coerced into scientific data.
    return {
        "__trove_python_type__": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
        "__trove_python_repr__": repr(value),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _alert_payload(alert: Any) -> dict[str, Any]:
    return _json_safe(
        {
            "alert_id": _get(alert, "alert_id"),
            "mjd": _get(alert, "mjd"),
            "processed_at": _get(alert, "processed_at"),
            "properties": _get(alert, "properties", {}) or {},
            "grav_wave_events": _get(alert, "grav_wave_events", []) or [],
        }
    )


def _is_rubin_alert(alert: Any) -> bool:
    alert_id = str(_get(alert, "alert_id", "") or "")
    properties = _get(alert, "properties", {}) or {}
    return alert_id.lower().startswith("lsst:") or any(
        str(key).lower().startswith("lsst_") for key in properties
    )


def _string_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _finite_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quality_flags(properties: Mapping[str, Any]) -> dict[str, bool]:
    # Convenience index only. Preserve every Rubin DiaSource boolean without
    # deciding whether True/False means scientifically usable or unusable.
    return {
        str(key): bool(value)
        for key, value in properties.items()
        if str(key).startswith("lsst_diaSource_") and isinstance(value, bool)
    }


def _snapshot_defaults(locus: Any, alert: Any, raw_alert: dict[str, Any]) -> dict[str, Any]:
    properties = _get(alert, "properties", {}) or {}
    return {
        "locus_id": _string_or_empty(_get(locus, "locus_id")),
        "dia_object_id": _string_or_empty(properties.get("lsst_diaSource_diaObjectId")),
        "dia_source_id": _string_or_empty(properties.get("lsst_diaSource_diaSourceId")),
        "ss_object_id": _string_or_empty(properties.get("lsst_diaSource_ssObjectId")),
        "midpoint_mjd_tai": _finite_float_or_none(properties.get("lsst_diaSource_midpointMjdTai")),
        "band": _string_or_empty(properties.get("lsst_diaSource_band")),
        # Signed values are copied exactly as numeric convenience fields. No abs(),
        # magnitude conversion, detection classification, or upper-limit inference.
        "psf_flux": _finite_float_or_none(properties.get("lsst_diaSource_psfFlux")),
        "psf_flux_err": _finite_float_or_none(properties.get("lsst_diaSource_psfFluxErr")),
        "reliability": _finite_float_or_none(properties.get("lsst_diaSource_reliability")),
        "quality_flags": _quality_flags(properties),
        "grav_wave_events": _json_safe(_get(alert, "grav_wave_events", []) or []),
        "raw_alert": raw_alert,
    }


def ingest_antares_rubin_evidence(locus: Any) -> RubinEvidenceIngestResult:
    """Persist Rubin alert evidence from one ANTARES Locus without interpreting it."""

    alerts = list(_get(locus, "alerts", []) or [])
    rubin_alerts = [alert for alert in alerts if _is_rubin_alert(alert)]

    created_count = 0
    duplicate_count = 0
    changed_count = 0

    with transaction.atomic():
        for alert in rubin_alerts:
            raw_alert = _alert_payload(alert)
            digest = hashlib.sha256(_canonical_json_bytes(raw_alert)).hexdigest()
            source_record_id = _string_or_empty(_get(alert, "alert_id")) or f"UNIDENTIFIED:{digest}"

            had_other_snapshot = RubinAlertEvidence.objects.filter(
                broker=BROKER,
                source_record_id=source_record_id,
            ).exclude(payload_sha256=digest).exists()

            evidence, created = RubinAlertEvidence.objects.get_or_create(
                broker=BROKER,
                source_record_id=source_record_id,
                payload_sha256=digest,
                defaults=_snapshot_defaults(locus, alert, raw_alert),
            )

            if created:
                created_count += 1
                if had_other_snapshot:
                    changed_count += 1
                continue

            duplicate_count += 1
            RubinAlertEvidence.objects.filter(pk=evidence.pk).update(
                delivery_count=F("delivery_count") + 1,
                last_received_at=timezone.now(),
            )

    return RubinEvidenceIngestResult(
        alerts_seen=len(alerts),
        rubin_alerts_seen=len(rubin_alerts),
        snapshots_created=created_count,
        duplicate_deliveries=duplicate_count,
        changed_payload_snapshots=changed_count,
    )
'''

TEST_MODULE = r'''import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_code.models import RubinAlertEvidence
from custom_code.rubin_evidence import ingest_antares_rubin_evidence
from tom_dataproducts.models import ReducedDatum
from trove_targets.models import Target

FIXTURE = Path(__file__).parent / "data" / "antares_rubin_evidence.json"
DB_MARK = pytest.mark.django_db(transaction=True, databases=["default", "catalogs"])


def _as_locus(payload):
    locus = payload["locus"]
    alerts = [SimpleNamespace(**alert) for alert in locus["alerts"]]
    return SimpleNamespace(
        locus_id=locus["locus_id"],
        ra=locus["ra"],
        dec=locus["dec"],
        properties=locus.get("properties", {}),
        tags=locus.get("tags", []),
        alerts=alerts,
    )


def _payload():
    return json.loads(FIXTURE.read_text())


@DB_MARK
def test_real_negative_difference_flux_is_preserved_not_reinterpreted():
    result = ingest_antares_rubin_evidence(_as_locus(_payload()))

    assert result.rubin_alerts_seen == 2
    assert result.snapshots_created == 2
    evidence = RubinAlertEvidence.objects.order_by("source_record_id").first()
    assert evidence.psf_flux is not None
    assert evidence.psf_flux < 0
    assert evidence.raw_alert["properties"]["lsst_diaSource_psfFlux"] == evidence.psf_flux

    # Ingress is evidence-only: no target, photometry, or detection/upper-limit
    # interpretation is created as a side effect.
    assert Target.objects.count() == 0
    assert ReducedDatum.objects.count() == 0


@DB_MARK
def test_cross_survey_history_is_not_persisted_as_rubin_evidence():
    payload = _payload()
    assert any(not alert["alert_id"].startswith("lsst:") for alert in payload["locus"]["alerts"])

    result = ingest_antares_rubin_evidence(_as_locus(payload))

    assert result.alerts_seen == 3
    assert result.rubin_alerts_seen == 2
    assert RubinAlertEvidence.objects.count() == 2
    assert all(row.source_record_id.startswith("lsst:") for row in RubinAlertEvidence.objects.all())


@DB_MARK
def test_exact_redelivery_creates_no_new_snapshot_and_counts_delivery():
    locus = _as_locus(_payload())

    first = ingest_antares_rubin_evidence(locus)
    second = ingest_antares_rubin_evidence(locus)

    assert first.snapshots_created == 2
    assert first.duplicate_deliveries == 0
    assert second.snapshots_created == 0
    assert second.duplicate_deliveries == 2
    assert RubinAlertEvidence.objects.count() == 2
    assert set(RubinAlertEvidence.objects.values_list("delivery_count", flat=True)) == {2}


@DB_MARK
def test_changed_payload_for_same_alert_id_is_preserved_as_new_snapshot():
    payload = _payload()
    ingest_antares_rubin_evidence(_as_locus(payload))

    changed = deepcopy(payload)
    alert = next(a for a in changed["locus"]["alerts"] if a["alert_id"].startswith("lsst:"))
    source_record_id = alert["alert_id"]
    original_flux = alert["properties"]["lsst_diaSource_psfFlux"]
    alert["properties"]["lsst_diaSource_psfFlux"] = original_flux - 1.0

    result = ingest_antares_rubin_evidence(_as_locus(changed))

    snapshots = RubinAlertEvidence.objects.filter(source_record_id=source_record_id).order_by("received_at")
    assert result.snapshots_created == 1
    assert result.changed_payload_snapshots == 1
    assert snapshots.count() == 2
    assert {row.psf_flux for row in snapshots} == {original_flux, original_flux - 1.0}


@DB_MARK
def test_quality_flags_are_preserved_without_quality_decision():
    ingest_antares_rubin_evidence(_as_locus(_payload()))

    rows = list(RubinAlertEvidence.objects.all())
    assert any(row.quality_flags.get("lsst_diaSource_isDipole") is True for row in rows)
    assert any(row.quality_flags.get("lsst_diaSource_pixelFlags_cr") is True for row in rows)
    assert Target.objects.count() == 0
    assert ReducedDatum.objects.count() == 0


@DB_MARK
def test_missing_alert_id_gets_deterministic_non_survey_record_id():
    payload = _payload()
    rubin = next(a for a in payload["locus"]["alerts"] if a["alert_id"].startswith("lsst:"))
    payload["locus"]["alerts"] = [rubin]
    payload["locus"]["alerts"][0]["alert_id"] = None

    first = ingest_antares_rubin_evidence(_as_locus(payload))
    second = ingest_antares_rubin_evidence(_as_locus(payload))

    row = RubinAlertEvidence.objects.get()
    assert row.source_record_id.startswith("UNIDENTIFIED:")
    assert first.snapshots_created == 1
    assert second.snapshots_created == 0
    assert second.duplicate_deliveries == 1
'''

HANDLER_ADDITION = r'''


def handle_antares_rubin_evidence(locus):
    """Persist Rubin broker evidence without scientific interpretation."""
    from .rubin_evidence import ingest_antares_rubin_evidence

    result = ingest_antares_rubin_evidence(locus)
    logger.info(
        "ANTARES Rubin evidence locus %s: alerts=%s rubin=%s snapshots_created=%s "
        "duplicates=%s changed_payload_snapshots=%s",
        getattr(locus, "locus_id", None),
        result.alerts_seen,
        result.rubin_alerts_seen,
        result.snapshots_created,
        result.duplicate_deliveries,
        result.changed_payload_snapshots,
    )
    return result
'''

ADMIN_CONTENT = r'''from django.contrib import admin

from .models import RubinAlertEvidence


@admin.register(RubinAlertEvidence)
class RubinAlertEvidenceAdmin(admin.ModelAdmin):
    list_display = (
        "broker",
        "source_record_id",
        "dia_object_id",
        "dia_source_id",
        "band",
        "psf_flux",
        "delivery_count",
        "received_at",
    )
    search_fields = (
        "source_record_id",
        "locus_id",
        "dia_object_id",
        "dia_source_id",
        "payload_sha256",
    )
    readonly_fields = (
        "broker",
        "locus_id",
        "source_record_id",
        "payload_sha256",
        "dia_object_id",
        "dia_source_id",
        "ss_object_id",
        "midpoint_mjd_tai",
        "band",
        "psf_flux",
        "psf_flux_err",
        "reliability",
        "quality_flags",
        "grav_wave_events",
        "raw_alert",
        "received_at",
        "last_received_at",
        "delivery_count",
    )
'''


def build_fixture() -> None:
    payload = json.loads(REAL_FIXTURE.read_text())
    locus = payload["locus"]
    rubin = [a for a in locus["alerts"] if str(a.get("alert_id", "")).startswith("lsst:")]
    non_rubin = [a for a in locus["alerts"] if not str(a.get("alert_id", "")).startswith("lsst:")]
    if len(rubin) < 2 or not non_rubin:
        raise RuntimeError("Expected real fixture with at least two Rubin alerts and cross-survey history")

    compact = {
        "fixture_provenance": {
            **payload.get("fixture_provenance", {}),
            "derived_for_upstream_test": True,
            "derivation": "one real non-Rubin alert plus both real Rubin alerts; values unchanged",
        },
        "locus": {
            "locus_id": locus["locus_id"],
            "ra": locus["ra"],
            "dec": locus["dec"],
            "properties": locus.get("properties", {}),
            "tags": locus.get("tags", []),
            "alerts": [non_rubin[0], *rubin[:2]],
        },
    }
    path = TROVE_ROOT / "tests" / "data" / "antares_rubin_evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n")


def modify_trove() -> None:
    models_path = TROVE_ROOT / "custom_code" / "models.py"
    models = models_path.read_text()
    if "class RubinAlertEvidence" not in models:
        models_path.write_text(models.rstrip() + "\n" + MODEL_ADDITION.lstrip())

    (TROVE_ROOT / "custom_code" / "migrations" / "0016_rubinalertevidence.py").write_text(MIGRATION)
    (TROVE_ROOT / "custom_code" / "rubin_evidence.py").write_text(EVIDENCE_MODULE)

    handler_path = TROVE_ROOT / "custom_code" / "alertstream_handlers.py"
    handler = handler_path.read_text()
    if "def handle_antares_rubin_evidence" not in handler:
        handler_path.write_text(handler.rstrip() + "\n" + HANDLER_ADDITION.lstrip())

    (TROVE_ROOT / "custom_code" / "admin.py").write_text(ADMIN_CONTENT)
    (TROVE_ROOT / "tests" / "test_rubin_evidence.py").write_text(TEST_MODULE)
    build_fixture()


def generate_patch() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "add",
            "-N",
            "custom_code/rubin_evidence.py",
            "custom_code/migrations/0016_rubinalertevidence.py",
            "tests/test_rubin_evidence.py",
        ],
        cwd=TROVE_ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "add", "-N", "-f", "tests/data/antares_rubin_evidence.json"],
        cwd=TROVE_ROOT,
        check=True,
    )

    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary"],
        cwd=TROVE_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    if not diff.strip():
        raise RuntimeError("Generated v2 patch is empty")
    PATCH_PATH.write_text(diff)

    changed = subprocess.run(
        ["git", "status", "--short"],
        cwd=TROVE_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    (OUT_DIR / "changed-files.txt").write_text(changed)


if __name__ == "__main__":
    modify_trove()
    generate_patch()
    print(PATCH_PATH)
