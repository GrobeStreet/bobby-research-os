from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "build_split_identity_patch.py"

spec = importlib.util.spec_from_file_location("v3_base", BASE)
base = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(base)


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"Expected v3 builder fragment not found: {old[:120]!r}")
    return text.replace(old, new, 1)


# True append-only semantics should use Django's object state, not merely whether a
# caller happened to assign a primary key before the first insert.
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '    def save(self, *args, **kwargs):\n        if self.pk is not None:\n            raise RuntimeError("Scientific evidence rows are append-only")\n',
    '    def save(self, *args, **kwargs):\n        if not self._state.adding:\n            raise RuntimeError("Scientific evidence rows are append-only")\n',
)

# A broker delivery identifier is meaningful only within a broker namespace. A
# concrete Kafka position is independently unique when topic/partition/offset are
# all known.
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '    delivery_id = models.CharField(max_length=200, unique=True)\n',
    '    delivery_id = models.CharField(max_length=200)\n',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '    class Meta:\n        indexes = [\n            models.Index(fields=["broker", "received_at"], name="rubin_delivery_time_idx"),\n            models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),\n        ]\n',
    '''    class Meta:\n        constraints = [\n            models.UniqueConstraint(\n                fields=["broker", "delivery_id"],\n                name="unique_rubin_delivery_id",\n            ),\n            models.UniqueConstraint(\n                fields=["broker", "topic", "partition", "offset"],\n                condition=(\n                    models.Q(topic__gt="")\n                    & models.Q(partition__isnull=False)\n                    & models.Q(offset__isnull=False)\n                ),\n                name="unique_rubin_transport_position",\n            ),\n        ]\n        indexes = [\n            models.Index(fields=["broker", "received_at"], name="rubin_delivery_time_idx"),\n            models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),\n        ]\n''',
)

base.MIGRATION = replace_once(
    base.MIGRATION,
    '("delivery_id", models.CharField(max_length=200, unique=True)),\n',
    '("delivery_id", models.CharField(max_length=200)),\n',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '''            options={\n                "indexes": [\n                    models.Index(fields=["broker", "received_at"], name="rubin_delivery_time_idx"),\n                    models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),\n                ],\n            },\n''',
    '''            options={\n                "indexes": [\n                    models.Index(fields=["broker", "received_at"], name="rubin_delivery_time_idx"),\n                    models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),\n                ],\n                "constraints": [\n                    models.UniqueConstraint(fields=("broker", "delivery_id"), name="unique_rubin_delivery_id"),\n                    models.UniqueConstraint(\n                        fields=("broker", "topic", "partition", "offset"),\n                        condition=models.Q(("offset__isnull", False), ("partition__isnull", False), ("topic__gt", "")),\n                        name="unique_rubin_transport_position",\n                    ),\n                ],\n            },\n''',
)

old_delivery_block = '''    explicit_delivery_id = str(metadata.pop("delivery_id", "") or "")\n    delivery_id = explicit_delivery_id or f"local:{uuid.uuid4()}"\n    topic = str(metadata.pop("topic", "") or "")\n    partition = metadata.pop("partition", None)\n    offset = metadata.pop("offset", None)\n\n    with transaction.atomic():\n        alert_evidence, alert_created = RubinAlertEvidence.objects.get_or_create(\n            broker=BROKER,\n            source_record_id=source_record_id,\n            alert_payload_sha256=alert_digest,\n            defaults=_alert_defaults(alert, alert_snapshot),\n        )\n        context_evidence, context_created = RubinBrokerContextEvidence.objects.get_or_create(\n            broker=BROKER,\n            locus_id=locus_id,\n            context_sha256=context_digest,\n            defaults={\n                "canonicalization_version": "context-v1",\n                "context_snapshot": context_snapshot,\n            },\n        )\n        try:\n            delivery, delivery_created = RubinEvidenceDelivery.objects.get_or_create(\n                delivery_id=delivery_id,\n                defaults={\n                    "broker": BROKER,\n                    "alert_evidence": alert_evidence,\n                    "broker_context": context_evidence,\n                    "topic": topic,\n                    "partition": partition,\n                    "offset": offset,\n                    "transport_metadata": _json_safe(metadata),\n                },\n            )\n        except IntegrityError:\n            delivery = RubinEvidenceDelivery.objects.get(delivery_id=delivery_id)\n            delivery_created = False\n        if not delivery_created and (\n            delivery.alert_evidence_id != alert_evidence.id or delivery.broker_context_id != context_evidence.id\n        ):\n            raise ValueError("delivery_id was previously used for different evidence/context")\n'''

new_delivery_block = '''    explicit_delivery_id = str(metadata.pop("delivery_id", "") or "")\n    topic = str(metadata.pop("topic", "") or "")\n    partition = metadata.pop("partition", None)\n    offset = metadata.pop("offset", None)\n    try:\n        partition = None if partition is None else int(partition)\n        offset = None if offset is None else int(offset)\n    except (TypeError, ValueError) as exc:\n        raise ValueError("partition and offset must be integers when supplied") from exc\n    transport_metadata = _json_safe(metadata)\n\n    has_kafka_position = bool(topic) and partition is not None and offset is not None\n    if explicit_delivery_id:\n        delivery_id = explicit_delivery_id\n    elif has_kafka_position:\n        delivery_id = f"kafka:{topic}:{partition}:{offset}"\n    else:\n        delivery_id = f"local:{uuid.uuid4()}"\n\n    with transaction.atomic():\n        alert_evidence, alert_created = RubinAlertEvidence.objects.get_or_create(\n            broker=BROKER,\n            source_record_id=source_record_id,\n            alert_payload_sha256=alert_digest,\n            defaults=_alert_defaults(alert, alert_snapshot),\n        )\n        context_evidence, context_created = RubinBrokerContextEvidence.objects.get_or_create(\n            broker=BROKER,\n            locus_id=locus_id,\n            context_sha256=context_digest,\n            defaults={\n                "canonicalization_version": "context-v1",\n                "context_snapshot": context_snapshot,\n            },\n        )\n        defaults = {\n            "alert_evidence": alert_evidence,\n            "broker_context": context_evidence,\n            "topic": topic,\n            "partition": partition,\n            "offset": offset,\n            "transport_metadata": transport_metadata,\n        }\n        try:\n            # Inner savepoint is required because a competing delivery can conflict\n            # either on broker+delivery_id or on the concrete Kafka position.\n            with transaction.atomic():\n                delivery, delivery_created = RubinEvidenceDelivery.objects.get_or_create(\n                    broker=BROKER,\n                    delivery_id=delivery_id,\n                    defaults=defaults,\n                )\n        except IntegrityError:\n            delivery = None\n            if has_kafka_position:\n                delivery = RubinEvidenceDelivery.objects.filter(\n                    broker=BROKER,\n                    topic=topic,\n                    partition=partition,\n                    offset=offset,\n                ).first()\n            if delivery is None:\n                delivery = RubinEvidenceDelivery.objects.get(\n                    broker=BROKER,\n                    delivery_id=delivery_id,\n                )\n            delivery_created = False\n\n        if not delivery_created:\n            expected = {\n                "delivery_id": delivery_id,\n                "alert_evidence_id": alert_evidence.id,\n                "broker_context_id": context_evidence.id,\n                "topic": topic,\n                "partition": partition,\n                "offset": offset,\n                "transport_metadata": transport_metadata,\n            }\n            actual = {\n                "delivery_id": delivery.delivery_id,\n                "alert_evidence_id": delivery.alert_evidence_id,\n                "broker_context_id": delivery.broker_context_id,\n                "topic": delivery.topic,\n                "partition": delivery.partition,\n                "offset": delivery.offset,\n                "transport_metadata": delivery.transport_metadata,\n            }\n            if actual != expected:\n                raise ValueError("delivery identity/provenance was previously used with different values")\n'''
base.INGRESS_MODULE = replace_once(base.INGRESS_MODULE, old_delivery_block, new_delivery_block)

# Add transport-integrity and real PostgreSQL race tests to the exact upstream diff.
extra_tests = r'''

@DB
def test_kafka_position_is_stable_delivery_identity_when_explicit_id_absent():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    meta = {"topic":"rubin-filtered", "partition":3, "offset":42}
    first = ingest_antares_rubin_delivery(alert, locus_context=context, delivery_metadata=meta)
    second = ingest_antares_rubin_delivery(alert, locus_context=context, delivery_metadata=meta)
    assert first.delivery_id == "kafka:rubin-filtered:3:42"
    assert second.delivery_created is False
    assert RubinEvidenceDelivery.objects.count() == 1


@DB
def test_same_delivery_id_with_changed_transport_provenance_is_rejected():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    ingest_antares_rubin_delivery(
        alert,
        locus_context=context,
        delivery_metadata={"delivery_id":"broker:fixed", "topic":"rubin", "partition":1, "offset":7},
    )
    with pytest.raises(ValueError, match="identity/provenance"):
        ingest_antares_rubin_delivery(
            alert,
            locus_context=context,
            delivery_metadata={"delivery_id":"broker:fixed", "topic":"rubin", "partition":1, "offset":8},
        )


@DB
def test_same_kafka_position_cannot_hide_behind_different_delivery_ids():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    shared = {"topic":"rubin", "partition":2, "offset":99}
    ingest_antares_rubin_delivery(
        alert, locus_context=context, delivery_metadata={**shared, "delivery_id":"broker:a"}
    )
    with pytest.raises(ValueError, match="identity/provenance"):
        ingest_antares_rubin_delivery(
            alert, locus_context=context, delivery_metadata={**shared, "delivery_id":"broker:b"}
        )


def _require_postgres():
    from django.db import connection
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL concurrency test")


def _thread_ingest(alert_dict, locus_dict, metadata, barrier):
    from django.db import close_old_connections
    close_old_connections()
    try:
        barrier.wait(timeout=10)
        return ingest_antares_rubin_delivery(
            as_alert(deepcopy(alert_dict)),
            locus_context=as_context(deepcopy(locus_dict)),
            delivery_metadata=deepcopy(metadata),
        )
    finally:
        close_old_connections()


@DB
def test_postgres_concurrent_exact_duplicate_converges_to_one_delivery():
    _require_postgres()
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    p = payload(); alert = first_rubin(p); locus = p["locus"]
    barrier = Barrier(2)
    meta = {"delivery_id":"race:same", "topic":"rubin", "partition":4, "offset":500}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_thread_ingest, alert, locus, meta, barrier) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert RubinAlertEvidence.objects.count() == 1
    assert RubinBrokerContextEvidence.objects.count() == 1
    assert RubinEvidenceDelivery.objects.count() == 1
    assert sorted(result.delivery_created for result in results) == [False, True]


@DB
def test_postgres_concurrent_distinct_deliveries_share_one_alert_snapshot():
    _require_postgres()
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    p = payload(); alert = first_rubin(p); locus = p["locus"]
    barrier = Barrier(2)
    metas = [
        {"delivery_id":"race:a", "topic":"rubin", "partition":5, "offset":1},
        {"delivery_id":"race:b", "topic":"rubin", "partition":5, "offset":2},
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_thread_ingest, alert, locus, meta, barrier) for meta in metas]
        [future.result(timeout=20) for future in futures]
    assert RubinAlertEvidence.objects.count() == 1
    assert RubinBrokerContextEvidence.objects.count() == 1
    assert RubinEvidenceDelivery.objects.count() == 2


@DB
def test_postgres_concurrent_changed_alert_versions_preserve_both():
    _require_postgres()
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    p = payload(); original = first_rubin(p); changed = deepcopy(original)
    changed["properties"]["lsst_diaSource_psfFlux"] -= 1.0
    locus = p["locus"]; barrier = Barrier(2)
    jobs = [
        (original, {"delivery_id":"race:v1", "topic":"rubin", "partition":6, "offset":1}),
        (changed, {"delivery_id":"race:v2", "topic":"rubin", "partition":6, "offset":2}),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_thread_ingest, alert, locus, meta, barrier) for alert, meta in jobs]
        [future.result(timeout=20) for future in futures]
    assert RubinAlertEvidence.objects.count() == 2
    assert RubinBrokerContextEvidence.objects.count() == 1
    assert RubinEvidenceDelivery.objects.count() == 2
'''
base.TEST_MODULE += extra_tests

# The base builder now generates the hardened patch with the stricter model/function/tests.
base.main()
