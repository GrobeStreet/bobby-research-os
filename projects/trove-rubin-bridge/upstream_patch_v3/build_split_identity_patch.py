from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

BRIDGE_ROOT = Path(os.environ["TROVE_RUBIN_BRIDGE_ROOT"])
TROVE_ROOT = Path(os.environ["TROVE_ROOT"])
FIXTURE_SOURCE = BRIDGE_ROOT / "fixtures" / "real_multi" / "antares_lsst_multi.json"
OUT_DIR = BRIDGE_ROOT / "upstream_patch_v3"
PATCH_PATH = OUT_DIR / "0001-rubin-split-evidence-boundary.patch"

MODEL_ADDITION = r'''

class AppendOnlyEvidenceQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("Scientific evidence rows are append-only")

    def delete(self):
        raise RuntimeError("Scientific evidence rows are append-only")


class AppendOnlyEvidenceModel(models.Model):
    objects = AppendOnlyEvidenceQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("Scientific evidence rows are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Scientific evidence rows are append-only")


class RubinAlertEvidence(AppendOnlyEvidenceModel):
    """Immutable broker-level snapshot of one Rubin alert.

    ``broker_alert_snapshot`` is authoritative for this model. It is a deterministic
    JSON snapshot of the broker alert object, not the original Kafka bytes or Rubin
    wire packet. Mutable locus context and delivery metadata are stored separately.
    """

    broker = models.CharField(max_length=50, default="ANTARES")
    source_record_id = models.CharField(max_length=200, db_index=True)
    alert_payload_sha256 = models.CharField(max_length=64, db_index=True)
    canonicalization_version = models.CharField(max_length=50, default="alert-v1")

    dia_object_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    dia_source_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    ss_object_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    midpoint_mjd_tai = models.FloatField(null=True, blank=True)
    band = models.CharField(max_length=20, blank=True, default="")
    psf_flux = models.FloatField(null=True, blank=True)
    psf_flux_err = models.FloatField(null=True, blank=True)
    reliability = models.FloatField(null=True, blank=True)
    quality_flags = models.JSONField(default=dict)
    alert_grav_wave_events = models.JSONField(default=list)
    broker_alert_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker", "source_record_id", "alert_payload_sha256"],
                name="unique_rubin_alert_evidence",
            )
        ]
        indexes = [
            models.Index(fields=["broker", "dia_object_id"], name="rubin_alert_obj_idx"),
            models.Index(fields=["broker", "dia_source_id"], name="rubin_alert_src_idx"),
        ]


class RubinBrokerContextEvidence(AppendOnlyEvidenceModel):
    """Immutable snapshot of mutable broker routing/context state."""

    broker = models.CharField(max_length=50, default="ANTARES")
    locus_id = models.CharField(max_length=100, db_index=True)
    context_sha256 = models.CharField(max_length=64, db_index=True)
    canonicalization_version = models.CharField(max_length=50, default="context-v1")
    context_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker", "locus_id", "context_sha256"],
                name="unique_rubin_broker_context",
            )
        ]


class RubinEvidenceDelivery(AppendOnlyEvidenceModel):
    """Append-only record that TROVE observed one broker delivery occurrence."""

    broker = models.CharField(max_length=50, default="ANTARES")
    delivery_id = models.CharField(max_length=200, unique=True)
    alert_evidence = models.ForeignKey(
        RubinAlertEvidence,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    broker_context = models.ForeignKey(
        RubinBrokerContextEvidence,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    received_at = models.DateTimeField(auto_now_add=True)
    topic = models.CharField(max_length=255, blank=True, default="")
    partition = models.IntegerField(null=True, blank=True)
    offset = models.BigIntegerField(null=True, blank=True)
    transport_metadata = models.JSONField(default=dict)

    class Meta:
        indexes = [
            models.Index(fields=["broker", "received_at"], name="rubin_delivery_time_idx"),
            models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),
        ]
'''

MIGRATION = r'''from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("custom_code", "0015_alter_credibleregioncontour_id")]

    operations = [
        migrations.CreateModel(
            name="RubinAlertEvidence",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("broker", models.CharField(default="ANTARES", max_length=50)),
                ("source_record_id", models.CharField(db_index=True, max_length=200)),
                ("alert_payload_sha256", models.CharField(db_index=True, max_length=64)),
                ("canonicalization_version", models.CharField(default="alert-v1", max_length=50)),
                ("dia_object_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("dia_source_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("ss_object_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("midpoint_mjd_tai", models.FloatField(blank=True, null=True)),
                ("band", models.CharField(blank=True, default="", max_length=20)),
                ("psf_flux", models.FloatField(blank=True, null=True)),
                ("psf_flux_err", models.FloatField(blank=True, null=True)),
                ("reliability", models.FloatField(blank=True, null=True)),
                ("quality_flags", models.JSONField(default=dict)),
                ("alert_grav_wave_events", models.JSONField(default=list)),
                ("broker_alert_snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["broker", "dia_object_id"], name="rubin_alert_obj_idx"),
                    models.Index(fields=["broker", "dia_source_id"], name="rubin_alert_src_idx"),
                ],
                "constraints": [models.UniqueConstraint(fields=("broker", "source_record_id", "alert_payload_sha256"), name="unique_rubin_alert_evidence")],
            },
        ),
        migrations.CreateModel(
            name="RubinBrokerContextEvidence",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("broker", models.CharField(default="ANTARES", max_length=50)),
                ("locus_id", models.CharField(db_index=True, max_length=100)),
                ("context_sha256", models.CharField(db_index=True, max_length=64)),
                ("canonicalization_version", models.CharField(default="context-v1", max_length=50)),
                ("context_snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("broker", "locus_id", "context_sha256"), name="unique_rubin_broker_context")],
            },
        ),
        migrations.CreateModel(
            name="RubinEvidenceDelivery",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("broker", models.CharField(default="ANTARES", max_length=50)),
                ("delivery_id", models.CharField(max_length=200, unique=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("topic", models.CharField(blank=True, default="", max_length=255)),
                ("partition", models.IntegerField(blank=True, null=True)),
                ("offset", models.BigIntegerField(blank=True, null=True)),
                ("transport_metadata", models.JSONField(default=dict)),
                ("alert_evidence", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="deliveries", to="custom_code.rubinalertevidence")),
                ("broker_context", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="deliveries", to="custom_code.rubinbrokercontextevidence")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["broker", "received_at"], name="rubin_delivery_time_idx"),
                    models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),
                ],
            },
        ),
    ]
'''

INGRESS_MODULE = r'''from __future__ import annotations

import base64
import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.db import IntegrityError, transaction

from .models import RubinAlertEvidence, RubinBrokerContextEvidence, RubinEvidenceDelivery

BROKER = "ANTARES"
ALERT_HASH_DOMAIN = "trove-rubin-alert-evidence:v1"
CONTEXT_HASH_DOMAIN = "trove-rubin-broker-context:v1"
_NONFINITE_KEY = "__trove_nonfinite_float__"
_BYTES_KEY = "__trove_bytes_base64__"


@dataclass(frozen=True)
class RubinDeliveryIngestResult:
    alert_evidence_id: int
    alert_evidence_created: bool
    broker_context_id: int
    broker_context_created: bool
    delivery_id: str
    delivery_created: bool


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        label = "NaN" if math.isnan(value) else ("+Infinity" if value > 0 else "-Infinity")
        return {_NONFINITE_KEY: label}
    if isinstance(value, bytes):
        return {_BYTES_KEY: base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted((_json_safe(v) for v in value), key=lambda item: repr(item))
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _json_safe(item_method())
        except (TypeError, ValueError):
            pass
    return {
        "__trove_python_type__": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
        "__trove_python_repr__": repr(value),
    }


def _canonical_bytes(domain: str, value: Any) -> bytes:
    payload = {"domain": domain, "value": value}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash(domain: str, value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(domain, value)).hexdigest()


def _sort_json_values(values: Any) -> list[Any]:
    safe = [_json_safe(v) for v in (values or [])]
    return sorted(safe, key=lambda v: json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _alert_snapshot(alert: Any) -> dict[str, Any]:
    return _json_safe({
        "alert_id": _get(alert, "alert_id"),
        "mjd": _get(alert, "mjd"),
        "processed_at": _get(alert, "processed_at"),
        "properties": _get(alert, "properties", {}) or {},
        "grav_wave_events": _get(alert, "grav_wave_events", []) or [],
    })


def _context_snapshot(locus_context: Any) -> dict[str, Any]:
    return {
        "locus_id": str(_get(locus_context, "locus_id", "") or ""),
        "tags": _sort_json_values(_get(locus_context, "tags", []) or []),
        "grav_wave_events": _sort_json_values(_get(locus_context, "grav_wave_events", []) or []),
    }


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quality_flags(properties: Mapping[str, Any]) -> dict[str, bool]:
    return {
        str(k): v for k, v in properties.items()
        if str(k).startswith("lsst_diaSource_") and isinstance(v, bool)
    }


def _alert_defaults(alert: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    properties = _get(alert, "properties", {}) or {}
    return {
        "canonicalization_version": "alert-v1",
        "dia_object_id": str(properties.get("lsst_diaSource_diaObjectId") or ""),
        "dia_source_id": str(properties.get("lsst_diaSource_diaSourceId") or ""),
        "ss_object_id": str(properties.get("lsst_diaSource_ssObjectId") or ""),
        "midpoint_mjd_tai": _finite_float(properties.get("lsst_diaSource_midpointMjdTai")),
        "band": str(properties.get("lsst_diaSource_band") or ""),
        "psf_flux": _finite_float(properties.get("lsst_diaSource_psfFlux")),
        "psf_flux_err": _finite_float(properties.get("lsst_diaSource_psfFluxErr")),
        "reliability": _finite_float(properties.get("lsst_diaSource_reliability")),
        "quality_flags": _quality_flags(properties),
        "alert_grav_wave_events": _json_safe(_get(alert, "grav_wave_events", []) or []),
        "broker_alert_snapshot": snapshot,
    }


def ingest_antares_rubin_delivery(alert: Any, *, locus_context: Any, delivery_metadata: Mapping[str, Any] | None = None) -> RubinDeliveryIngestResult:
    """Persist one explicit Rubin alert, one context snapshot, and one delivery occurrence.

    This function never accesses ``locus_context.alerts`` and performs no scientific
    interpretation, target creation, photometry conversion, or candidate vetting.
    """
    metadata = dict(delivery_metadata or {})
    source_record_id = str(_get(alert, "alert_id", "") or "")
    if not source_record_id:
        raise ValueError("ANTARES Rubin alert is missing alert_id")
    properties = _get(alert, "properties", {}) or {}
    if not source_record_id.lower().startswith("lsst:") and not any(str(k).lower().startswith("lsst_") for k in properties):
        raise ValueError("Alert does not contain recognizable Rubin/LSST evidence")

    alert_snapshot = _alert_snapshot(alert)
    alert_digest = _hash(ALERT_HASH_DOMAIN, alert_snapshot)
    context_snapshot = _context_snapshot(locus_context)
    locus_id = context_snapshot["locus_id"]
    if not locus_id:
        raise ValueError("Broker context is missing locus_id")
    context_digest = _hash(CONTEXT_HASH_DOMAIN, context_snapshot)

    explicit_delivery_id = str(metadata.pop("delivery_id", "") or "")
    delivery_id = explicit_delivery_id or f"local:{uuid.uuid4()}"
    topic = str(metadata.pop("topic", "") or "")
    partition = metadata.pop("partition", None)
    offset = metadata.pop("offset", None)

    with transaction.atomic():
        alert_evidence, alert_created = RubinAlertEvidence.objects.get_or_create(
            broker=BROKER,
            source_record_id=source_record_id,
            alert_payload_sha256=alert_digest,
            defaults=_alert_defaults(alert, alert_snapshot),
        )
        context_evidence, context_created = RubinBrokerContextEvidence.objects.get_or_create(
            broker=BROKER,
            locus_id=locus_id,
            context_sha256=context_digest,
            defaults={
                "canonicalization_version": "context-v1",
                "context_snapshot": context_snapshot,
            },
        )
        try:
            delivery, delivery_created = RubinEvidenceDelivery.objects.get_or_create(
                delivery_id=delivery_id,
                defaults={
                    "broker": BROKER,
                    "alert_evidence": alert_evidence,
                    "broker_context": context_evidence,
                    "topic": topic,
                    "partition": partition,
                    "offset": offset,
                    "transport_metadata": _json_safe(metadata),
                },
            )
        except IntegrityError:
            delivery = RubinEvidenceDelivery.objects.get(delivery_id=delivery_id)
            delivery_created = False
        if not delivery_created and (
            delivery.alert_evidence_id != alert_evidence.id or delivery.broker_context_id != context_evidence.id
        ):
            raise ValueError("delivery_id was previously used for different evidence/context")

    return RubinDeliveryIngestResult(
        alert_evidence_id=alert_evidence.id,
        alert_evidence_created=alert_created,
        broker_context_id=context_evidence.id,
        broker_context_created=context_created,
        delivery_id=delivery.delivery_id,
        delivery_created=delivery_created,
    )
'''

TEST_MODULE = r'''import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_code.models import RubinAlertEvidence, RubinBrokerContextEvidence, RubinEvidenceDelivery
from custom_code.rubin_evidence import ALERT_HASH_DOMAIN, _canonical_bytes, ingest_antares_rubin_delivery
from tom_dataproducts.models import ReducedDatum
from trove_targets.models import Target

FIXTURE = Path(__file__).parent / "data" / "antares_rubin_delivery.json"
DB = pytest.mark.django_db(transaction=True, databases=["default", "catalogs"])


def payload():
    return json.loads(FIXTURE.read_text())


def as_alert(data):
    return SimpleNamespace(**data)


def as_context(locus):
    class Context:
        locus_id = locus["locus_id"]
        tags = locus.get("tags", [])
        grav_wave_events = locus.get("grav_wave_events", [])
        @property
        def alerts(self):
            raise AssertionError("v3 core must never access locus.alerts")
    return Context()


def first_rubin(p):
    return next(a for a in p["locus"]["alerts"] if a["alert_id"].startswith("lsst:"))


@DB
def test_negative_flux_preserved_and_no_science_side_effects():
    p = payload(); alert = first_rubin(p)
    result = ingest_antares_rubin_delivery(as_alert(alert), locus_context=as_context(p["locus"]), delivery_metadata={"delivery_id":"test:1"})
    evidence = RubinAlertEvidence.objects.get(pk=result.alert_evidence_id)
    assert evidence.psf_flux < 0
    assert evidence.broker_alert_snapshot["properties"]["lsst_diaSource_psfFlux"] == evidence.psf_flux
    assert Target.objects.count() == 0
    assert ReducedDatum.objects.count() == 0


@DB
def test_exact_alert_redelivery_reuses_alert_but_creates_separate_delivery():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    a = ingest_antares_rubin_delivery(alert, locus_context=context, delivery_metadata={"delivery_id":"test:a"})
    b = ingest_antares_rubin_delivery(alert, locus_context=context, delivery_metadata={"delivery_id":"test:b"})
    assert a.alert_evidence_id == b.alert_evidence_id
    assert RubinAlertEvidence.objects.count() == 1
    assert RubinEvidenceDelivery.objects.count() == 2


@DB
def test_same_explicit_delivery_id_is_idempotent():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    a = ingest_antares_rubin_delivery(alert, locus_context=context, delivery_metadata={"delivery_id":"broker:42","topic":"rubin"})
    b = ingest_antares_rubin_delivery(alert, locus_context=context, delivery_metadata={"delivery_id":"broker:42","topic":"rubin"})
    assert a.delivery_id == b.delivery_id
    assert b.delivery_created is False
    assert RubinEvidenceDelivery.objects.count() == 1


@DB
def test_context_change_does_not_duplicate_alert_payload():
    p = payload(); alert = as_alert(first_rubin(p)); context1 = as_context(p["locus"])
    ingest_antares_rubin_delivery(alert, locus_context=context1, delivery_metadata={"delivery_id":"test:1"})
    p2 = deepcopy(p); p2["locus"]["tags"] = ["new-context-tag"]
    ingest_antares_rubin_delivery(alert, locus_context=as_context(p2["locus"]), delivery_metadata={"delivery_id":"test:2"})
    assert RubinAlertEvidence.objects.count() == 1
    assert RubinBrokerContextEvidence.objects.count() == 2
    assert RubinEvidenceDelivery.objects.count() == 2


@DB
def test_context_reordering_is_canonicalized():
    p = payload(); alert = as_alert(first_rubin(p))
    p["locus"]["tags"] = ["b", "a"]
    ingest_antares_rubin_delivery(alert, locus_context=as_context(p["locus"]), delivery_metadata={"delivery_id":"test:1"})
    p2 = deepcopy(p); p2["locus"]["tags"] = ["a", "b"]
    ingest_antares_rubin_delivery(alert, locus_context=as_context(p2["locus"]), delivery_metadata={"delivery_id":"test:2"})
    assert RubinBrokerContextEvidence.objects.count() == 1


@DB
def test_changed_alert_payload_creates_new_alert_snapshot_only():
    p = payload(); original = first_rubin(p); context = as_context(p["locus"])
    ingest_antares_rubin_delivery(as_alert(original), locus_context=context, delivery_metadata={"delivery_id":"test:1"})
    changed = deepcopy(original); changed["properties"]["lsst_diaSource_psfFlux"] -= 1.0
    ingest_antares_rubin_delivery(as_alert(changed), locus_context=context, delivery_metadata={"delivery_id":"test:2"})
    assert RubinAlertEvidence.objects.count() == 2
    assert RubinBrokerContextEvidence.objects.count() == 1


@DB
def test_hash_recomputes_from_stored_alert_snapshot():
    p = payload(); alert = as_alert(first_rubin(p))
    result = ingest_antares_rubin_delivery(alert, locus_context=as_context(p["locus"]), delivery_metadata={"delivery_id":"test:1"})
    row = RubinAlertEvidence.objects.get(pk=result.alert_evidence_id)
    expected = hashlib.sha256(_canonical_bytes(ALERT_HASH_DOMAIN, row.broker_alert_snapshot)).hexdigest()
    assert expected == row.alert_payload_sha256


@DB
def test_evidence_context_and_delivery_are_append_only():
    p = payload(); alert = as_alert(first_rubin(p))
    result = ingest_antares_rubin_delivery(alert, locus_context=as_context(p["locus"]), delivery_metadata={"delivery_id":"test:1"})
    evidence = RubinAlertEvidence.objects.get(pk=result.alert_evidence_id)
    evidence.band = "changed"
    with pytest.raises(RuntimeError): evidence.save()
    with pytest.raises(RuntimeError): RubinAlertEvidence.objects.filter(pk=evidence.pk).update(band="changed")
    with pytest.raises(RuntimeError): evidence.delete()
    with pytest.raises(RuntimeError): RubinEvidenceDelivery.objects.all().delete()


@DB
def test_missing_alert_id_fails_closed():
    p = payload(); alert = deepcopy(first_rubin(p)); alert["alert_id"] = None
    with pytest.raises(ValueError, match="missing alert_id"):
        ingest_antares_rubin_delivery(as_alert(alert), locus_context=as_context(p["locus"]), delivery_metadata={"delivery_id":"test:1"})


@DB
def test_delivery_id_cannot_be_reused_for_different_alert():
    p = payload(); rubin = [a for a in p["locus"]["alerts"] if a["alert_id"].startswith("lsst:")]
    context = as_context(p["locus"])
    ingest_antares_rubin_delivery(as_alert(rubin[0]), locus_context=context, delivery_metadata={"delivery_id":"broker:fixed"})
    with pytest.raises(ValueError, match="previously used"):
        ingest_antares_rubin_delivery(as_alert(rubin[1]), locus_context=context, delivery_metadata={"delivery_id":"broker:fixed"})
'''

ADMIN_ADDITION = r'''
from .models import RubinAlertEvidence, RubinBrokerContextEvidence, RubinEvidenceDelivery


class ViewOnlyEvidenceAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD", "OPTIONS")
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RubinAlertEvidence)
class RubinAlertEvidenceAdmin(ViewOnlyEvidenceAdmin):
    list_display = ("broker", "source_record_id", "dia_object_id", "band", "psf_flux", "created_at")
    search_fields = ("source_record_id", "dia_object_id", "dia_source_id", "alert_payload_sha256")


@admin.register(RubinBrokerContextEvidence)
class RubinBrokerContextEvidenceAdmin(ViewOnlyEvidenceAdmin):
    list_display = ("broker", "locus_id", "context_sha256", "created_at")
    search_fields = ("locus_id", "context_sha256")


@admin.register(RubinEvidenceDelivery)
class RubinEvidenceDeliveryAdmin(ViewOnlyEvidenceAdmin):
    list_display = ("broker", "delivery_id", "topic", "partition", "offset", "received_at")
    search_fields = ("delivery_id", "topic")
'''

HANDLER = r'''


def handle_antares_rubin_delivery(alert, *, locus_context, delivery_metadata=None):
    """Thin evidence-only entrypoint for an explicit current Rubin alert.

    This is intentionally not wired to `AntaresAlertStream` yet because the pinned
    TOM wrapper currently passes a whole Locus, not an explicit triggering alert.
    """
    from .rubin_evidence import ingest_antares_rubin_delivery
    return ingest_antares_rubin_delivery(
        alert,
        locus_context=locus_context,
        delivery_metadata=delivery_metadata,
    )
'''


def compact_fixture():
    p = json.loads(FIXTURE_SOURCE.read_text())
    locus = p["locus"]
    rubin = [a for a in locus["alerts"] if str(a.get("alert_id", "")).startswith("lsst:")]
    if len(rubin) < 2:
        raise RuntimeError("Need at least two real Rubin alerts")
    return {
        "fixture_provenance": p.get("fixture_provenance", {}),
        "locus": {
            "locus_id": locus["locus_id"],
            "tags": locus.get("tags", []),
            "grav_wave_events": locus.get("grav_wave_events", []),
            "alerts": rubin[:2],
        },
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    models = TROVE_ROOT / "custom_code/models.py"
    models.write_text(models.read_text() + MODEL_ADDITION)
    (TROVE_ROOT / "custom_code/migrations/0016_rubin_split_evidence.py").write_text(MIGRATION)
    (TROVE_ROOT / "custom_code/rubin_evidence.py").write_text(INGRESS_MODULE)
    admin = TROVE_ROOT / "custom_code/admin.py"
    admin.write_text("from django.contrib import admin\n\n" + ADMIN_ADDITION)
    handlers = TROVE_ROOT / "custom_code/alertstream_handlers.py"
    handlers.write_text(handlers.read_text() + HANDLER)
    fixture_path = TROVE_ROOT / "tests/data/antares_rubin_delivery.json"
    fixture_path.write_text(json.dumps(compact_fixture(), indent=2, sort_keys=True) + "\n")
    (TROVE_ROOT / "tests/test_rubin_split_evidence.py").write_text(TEST_MODULE)

    new_files = [
        "custom_code/migrations/0016_rubin_split_evidence.py",
        "custom_code/rubin_evidence.py",
        "tests/test_rubin_split_evidence.py",
    ]
    for path in new_files:
        subprocess.run(["git", "add", "-N", path], cwd=TROVE_ROOT, check=True)
    subprocess.run(["git", "add", "-f", "-N", "tests/data/antares_rubin_delivery.json"], cwd=TROVE_ROOT, check=True)

    diff = subprocess.run(["git", "diff", "--no-ext-diff", "--binary"], cwd=TROVE_ROOT, check=True, text=True, stdout=subprocess.PIPE).stdout
    PATCH_PATH.write_text(diff)
    status = subprocess.run(["git", "status", "--short"], cwd=TROVE_ROOT, check=True, text=True, stdout=subprocess.PIPE).stdout
    (OUT_DIR / "changed-files.txt").write_text(status)
    print(PATCH_PATH)


if __name__ == "__main__":
    main()
