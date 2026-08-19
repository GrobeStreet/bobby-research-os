from __future__ import annotations

import subprocess
from pathlib import Path

# Build v3 as a narrow protocol delta on top of the independently validated/frozen
# strict-v2 builder. This preserves the reviewed architecture while changing only
# canonical evidence identity, transport identity/provenance semantics, zero-valued
# ID extraction, and focused runtime-shape tests.
STRICT_V2_COMMIT = "ac912a3488235c836c8a7f3b17c74359e4480a52"
RELATIVE_PATH = "projects/trove-rubin-bridge/upstream_patch_v3/run_hardened_v3_strict_final.py"
repo_root = Path(__file__).resolve().parents[3]
source = subprocess.run(
    ["git", "show", f"{STRICT_V2_COMMIT}:{RELATIVE_PATH}"],
    cwd=repo_root,
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout

marker = "# The base builder now generates the hardened, strict-canonicalization patch.\nbase.main()'''"
if source.count(marker) != 1:
    raise RuntimeError("Could not locate strict-v2 finalization marker")

protocol_v3 = r'''
# --- narrow evidence protocol v3 ---
# v3 keeps the split evidence/context/delivery architecture intact. It changes the
# identity protocol only: all authoritative snapshots use an unambiguous tagged
# normal form, Kafka positions are namespaced, ancillary transport metadata is not
# part of delivery identity, and zero-valued Rubin IDs are preserved.
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    'canonicalization_version = models.CharField(max_length=50, default="alert-v2")',
    'canonicalization_version = models.CharField(max_length=50, default="alert-v3")',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    'canonicalization_version = models.CharField(max_length=50, default="context-v2")',
    'canonicalization_version = models.CharField(max_length=50, default="context-v3")',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '    received_at = models.DateTimeField(auto_now_add=True)\n    topic = models.CharField(max_length=255, blank=True, default="")\n',
    '    received_at = models.DateTimeField(auto_now_add=True)\n    transport_namespace = models.CharField(max_length=255, blank=True, default="")\n    topic = models.CharField(max_length=255, blank=True, default="")\n',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '    transport_metadata = models.JSONField(default=dict)\n',
    '    ancillary_metadata = models.JSONField(default=list)\n',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '                fields=["broker", "delivery_id"],\n',
    '                fields=["broker", "transport_namespace", "delivery_id"],\n',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '                fields=["broker", "topic", "partition", "offset"],\n                condition=(\n                    models.Q(topic__gt="")\n                    & models.Q(partition__isnull=False)\n                    & models.Q(offset__isnull=False)\n                ),\n',
    '                fields=["broker", "transport_namespace", "topic", "partition", "offset"],\n                condition=(\n                    models.Q(transport_namespace__gt="")\n                    & models.Q(topic__gt="")\n                    & models.Q(partition__isnull=False)\n                    & models.Q(offset__isnull=False)\n                ),\n',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '            models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),\n',
    '            models.Index(fields=["transport_namespace", "topic", "partition", "offset"], name="rubin_transport_idx"),\n',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    '    ``broker_alert_snapshot`` is authoritative for this model. It is a deterministic\n    JSON snapshot of the broker alert object, not the original Kafka bytes or Rubin\n    wire packet. Mutable locus context and delivery metadata are stored separately.\n',
    '    ``broker_alert_snapshot`` is authoritative for this model. It is a deterministic\n    tagged normal form of the broker alert object, not the original Kafka bytes or\n    Rubin wire packet. Mutable locus context and ancillary transport metadata are\n    stored separately.\n',
)

base.MIGRATION = replace_once(
    base.MIGRATION,
    '("canonicalization_version", models.CharField(default="alert-v2", max_length=50)),',
    '("canonicalization_version", models.CharField(default="alert-v3", max_length=50)),',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '("canonicalization_version", models.CharField(default="context-v2", max_length=50)),',
    '("canonicalization_version", models.CharField(default="context-v3", max_length=50)),',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '                ("received_at", models.DateTimeField(auto_now_add=True)),\n                ("topic", models.CharField(blank=True, default="", max_length=255)),\n',
    '                ("received_at", models.DateTimeField(auto_now_add=True)),\n                ("transport_namespace", models.CharField(blank=True, default="", max_length=255)),\n                ("topic", models.CharField(blank=True, default="", max_length=255)),\n',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '                ("transport_metadata", models.JSONField(default=dict)),\n',
    '                ("ancillary_metadata", models.JSONField(default=list)),\n',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '                    models.Index(fields=["topic", "partition", "offset"], name="rubin_transport_idx"),\n',
    '                    models.Index(fields=["transport_namespace", "topic", "partition", "offset"], name="rubin_transport_idx"),\n',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '                    models.UniqueConstraint(fields=("broker", "delivery_id"), name="unique_rubin_delivery_id"),\n',
    '                    models.UniqueConstraint(fields=("broker", "transport_namespace", "delivery_id"), name="unique_rubin_delivery_id"),\n',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '                        fields=("broker", "topic", "partition", "offset"),\n                        condition=models.Q(("topic__gt", ""), ("partition__isnull", False), ("offset__isnull", False)),\n',
    '                        fields=("broker", "transport_namespace", "topic", "partition", "offset"),\n                        condition=models.Q(("transport_namespace__gt", ""), ("topic__gt", ""), ("partition__isnull", False), ("offset__isnull", False)),\n',
)

base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    'import math\nimport uuid\n',
    'import math\nimport struct\nimport uuid\n',
)
base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    'ALERT_HASH_DOMAIN = "trove-rubin-alert-evidence:v2"\nCONTEXT_HASH_DOMAIN = "trove-rubin-broker-context:v2"\n_NONFINITE_KEY = "__trove_nonfinite_float__"\n_BYTES_KEY = "__trove_bytes_base64__"\n',
    'ALERT_HASH_DOMAIN = "trove-rubin-alert-evidence:v3"\nCONTEXT_HASH_DOMAIN = "trove-rubin-broker-context:v3"\nKAFKA_ID_DOMAIN = "trove-rubin-kafka-delivery:v1"\nTYPED_NORMAL_FORM = "trove-typed-normal-form:v1"\n',
)

canonical_start = base.INGRESS_MODULE.index('def _json_safe(value: Any) -> Any:')
canonical_end = base.INGRESS_MODULE.index('\ndef _finite_float', canonical_start)
canonical_v3 = r'''def _typed_normal_form(value: Any) -> Any:
    """Encode supported broker values into a structurally unambiguous JSON tree.

    Every Python value is wrapped in a type tag, so broker dictionaries can never
    collide with encoded bytes/non-finite floats or another supported Python type.
    Float identity uses the exact IEEE-754 binary64 bit pattern, including signed
    zero and NaN payload bits. Mapping keys must be strings.
    """
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, float):
        return ["float64", struct.pack(">d", value).hex()]
    if isinstance(value, bytes):
        return ["bytes", base64.b64encode(value).decode("ascii")]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat(), int(value.fold)]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, Mapping):
        non_string_keys = [key for key in value if not isinstance(key, str)]
        if non_string_keys:
            raise TypeError("Broker evidence mappings must use string keys")
        return [
            "map",
            [[key, _typed_normal_form(value[key])] for key in sorted(value)],
        ]
    if isinstance(value, list):
        return ["list", [_typed_normal_form(item) for item in value]]
    if isinstance(value, tuple):
        return ["tuple", [_typed_normal_form(item) for item in value]]
    if isinstance(value, set):
        nodes = [_typed_normal_form(item) for item in value]
        nodes.sort(key=_node_bytes)
        return ["set", nodes]
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            converted = item_method()
        except (TypeError, ValueError):
            converted = value
        if converted is not value:
            type_name = f"{value.__class__.__module__}.{value.__class__.__qualname__}"
            return ["scalar", type_name, _typed_normal_form(converted)]
    raise TypeError(
        "Unsupported broker evidence type: "
        f"{value.__class__.__module__}.{value.__class__.__qualname__}"
    )


def _node_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_bytes(domain: str, value: Any) -> bytes:
    return _node_bytes([TYPED_NORMAL_FORM, domain, value])


def _hash(domain: str, value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(domain, value)).hexdigest()


def _sort_context_values(values: Any) -> list[Any]:
    raw = list(values or [])
    return sorted(raw, key=lambda item: _node_bytes(_typed_normal_form(item)))


def _normalized_datetime_text(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _alert_snapshot(alert: Any) -> Any:
    return _typed_normal_form({
        "alert_id": _get(alert, "alert_id"),
        "mjd": _get(alert, "mjd"),
        "processed_at": _normalized_datetime_text(_get(alert, "processed_at")),
        "properties": _get(alert, "properties", {}) or {},
        "grav_wave_events": _get(alert, "grav_wave_events", []) or [],
    })


def _context_snapshot(locus_context: Any, locus_id: str) -> Any:
    return _typed_normal_form({
        "locus_id": locus_id,
        "tags": _sort_context_values(_get(locus_context, "tags", []) or []),
        "grav_wave_events": _sort_context_values(_get(locus_context, "grav_wave_events", []) or []),
    })


def _string_id(value: Any) -> str:
    return "" if value is None else str(value)
'''
base.INGRESS_MODULE = base.INGRESS_MODULE[:canonical_start] + canonical_v3 + base.INGRESS_MODULE[canonical_end:]

base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    '        "canonicalization_version": "alert-v2",\n        "dia_object_id": str(properties.get("lsst_diaSource_diaObjectId") or ""),\n        "dia_source_id": str(properties.get("lsst_diaSource_diaSourceId") or ""),\n        "ss_object_id": str(properties.get("lsst_diaSource_ssObjectId") or ""),\n',
    '        "canonicalization_version": "alert-v3",\n        "dia_object_id": _string_id(properties.get("lsst_diaSource_diaObjectId")),\n        "dia_source_id": _string_id(properties.get("lsst_diaSource_diaSourceId")),\n        "ss_object_id": _string_id(properties.get("lsst_diaSource_ssObjectId")),\n',
)
base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    '        "alert_grav_wave_events": _json_safe(_get(alert, "grav_wave_events", []) or []),\n',
    '        "alert_grav_wave_events": _typed_normal_form(_get(alert, "grav_wave_events", []) or []),\n',
)
base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    '    context_snapshot = _context_snapshot(locus_context)\n    locus_id = context_snapshot["locus_id"]\n    if not locus_id:\n        raise ValueError("Broker context is missing locus_id")\n    context_digest = _hash(CONTEXT_HASH_DOMAIN, context_snapshot)\n',
    '    locus_id = _string_id(_get(locus_context, "locus_id", ""))\n    if not locus_id:\n        raise ValueError("Broker context is missing locus_id")\n    context_snapshot = _context_snapshot(locus_context, locus_id)\n    context_digest = _hash(CONTEXT_HASH_DOMAIN, context_snapshot)\n',
)

transport_start = base.INGRESS_MODULE.index('    explicit_delivery_id = str(metadata.pop("delivery_id", "") or "")')
transport_end = base.INGRESS_MODULE.index('\n    return RubinDeliveryIngestResult(', transport_start)
transport_v3 = r'''    explicit_delivery_id = _string_id(metadata.pop("delivery_id", ""))
    transport_namespace = _string_id(metadata.pop("transport_namespace", ""))
    topic = _string_id(metadata.pop("topic", ""))
    partition = metadata.pop("partition", None)
    offset = metadata.pop("offset", None)
    try:
        partition = None if partition is None else int(partition)
        offset = None if offset is None else int(offset)
    except (TypeError, ValueError) as exc:
        raise ValueError("partition and offset must be integers when supplied") from exc

    has_any_kafka_coordinate = partition is not None or offset is not None
    if has_any_kafka_coordinate and (not topic or partition is None or offset is None):
        raise ValueError("topic, partition, and offset must be supplied together")
    has_kafka_position = has_any_kafka_coordinate
    if has_kafka_position and not transport_namespace:
        raise ValueError("transport_namespace is required with Kafka coordinates")

    ancillary_metadata = _typed_normal_form(metadata)
    if explicit_delivery_id:
        delivery_id = explicit_delivery_id
    elif has_kafka_position:
        kafka_identity = _typed_normal_form({
            "transport_namespace": transport_namespace,
            "topic": topic,
            "partition": partition,
            "offset": offset,
        })
        delivery_id = f"kafka:{_hash(KAFKA_ID_DOMAIN, kafka_identity)}"
    else:
        delivery_id = f"local:{uuid.uuid4()}"

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
                "canonicalization_version": "context-v3",
                "context_snapshot": context_snapshot,
            },
        )
        defaults = {
            "alert_evidence": alert_evidence,
            "broker_context": context_evidence,
            "topic": topic,
            "partition": partition,
            "offset": offset,
            "ancillary_metadata": ancillary_metadata,
        }
        try:
            with transaction.atomic():
                delivery, delivery_created = RubinEvidenceDelivery.objects.get_or_create(
                    broker=BROKER,
                    transport_namespace=transport_namespace,
                    delivery_id=delivery_id,
                    defaults=defaults,
                )
        except IntegrityError:
            delivery = None
            if has_kafka_position:
                delivery = RubinEvidenceDelivery.objects.filter(
                    broker=BROKER,
                    transport_namespace=transport_namespace,
                    topic=topic,
                    partition=partition,
                    offset=offset,
                ).first()
            if delivery is None:
                delivery = RubinEvidenceDelivery.objects.get(
                    broker=BROKER,
                    transport_namespace=transport_namespace,
                    delivery_id=delivery_id,
                )
            delivery_created = False

        if not delivery_created:
            expected = {
                "delivery_id": delivery_id,
                "alert_evidence_id": alert_evidence.id,
                "broker_context_id": context_evidence.id,
                "transport_namespace": transport_namespace,
                "topic": topic,
                "partition": partition,
                "offset": offset,
            }
            actual = {
                "delivery_id": delivery.delivery_id,
                "alert_evidence_id": delivery.alert_evidence_id,
                "broker_context_id": delivery.broker_context_id,
                "transport_namespace": delivery.transport_namespace,
                "topic": delivery.topic,
                "partition": delivery.partition,
                "offset": delivery.offset,
            }
            if actual != expected:
                raise ValueError("delivery identity/provenance was previously used with different values")
'''
base.INGRESS_MODULE = base.INGRESS_MODULE[:transport_start] + transport_v3 + base.INGRESS_MODULE[transport_end:]
if '_json_safe' in base.INGRESS_MODULE:
    raise RuntimeError("v3 ingress still contains legacy _json_safe canonicalization")

base.ADMIN_ADDITION = replace_once(
    base.ADMIN_ADDITION,
    '    list_display = ("broker", "delivery_id", "topic", "partition", "offset", "received_at")\n    search_fields = ("delivery_id", "topic")\n',
    '    list_display = ("broker", "transport_namespace", "delivery_id", "topic", "partition", "offset", "received_at")\n    search_fields = ("transport_namespace", "delivery_id", "topic")\n',
)

base.TEST_MODULE = replace_once(
    base.TEST_MODULE,
    'from pathlib import Path\nfrom types import SimpleNamespace\n',
    'from pathlib import Path\nfrom types import SimpleNamespace\nfrom datetime import datetime\n',
)
base.TEST_MODULE = replace_once(
    base.TEST_MODULE,
    'from custom_code.rubin_evidence import ALERT_HASH_DOMAIN, _canonical_bytes, ingest_antares_rubin_delivery\n',
    'from custom_code.rubin_evidence import ALERT_HASH_DOMAIN, _alert_snapshot, _canonical_bytes, ingest_antares_rubin_delivery\n',
)
base.TEST_MODULE = replace_once(
    base.TEST_MODULE,
    '    assert evidence.broker_alert_snapshot["properties"]["lsst_diaSource_psfFlux"] == evidence.psf_flux\n',
    '    assert evidence.broker_alert_snapshot == _alert_snapshot(as_alert(alert))\n',
)

# All concrete Kafka-position tests now carry an explicit immutable namespace.
base.TEST_MODULE = base.TEST_MODULE.replace(
    '{"topic":"rubin-filtered", "partition":3, "offset":42}',
    '{"transport_namespace":"antares:test", "topic":"rubin-filtered", "partition":3, "offset":42}',
)
base.TEST_MODULE = base.TEST_MODULE.replace(
    '"topic":"rubin", "partition":',
    '"transport_namespace":"antares:test", "topic":"rubin", "partition":',
)
base.TEST_MODULE = replace_once(
    base.TEST_MODULE,
    '    assert first.delivery_id == "kafka:rubin-filtered:3:42"\n    assert second.delivery_created is False\n',
    '    assert first.delivery_id.startswith("kafka:")\n    assert first.delivery_id == second.delivery_id\n    assert second.delivery_created is False\n',
)

strict_test_old = r'''def test_set_serialization_is_canonical_and_not_repr_ordered():
    from custom_code.rubin_evidence import _json_safe
    left = _json_safe({"items": {"b", "a"}})
    right = _json_safe({"items": {"a", "b"}})
    assert left == right == {"items": ["a", "b"]}


def test_hash_protocol_version_is_explicitly_v2():
    from custom_code.rubin_evidence import ALERT_HASH_DOMAIN, CONTEXT_HASH_DOMAIN
    assert ALERT_HASH_DOMAIN.endswith(":v2")
    assert CONTEXT_HASH_DOMAIN.endswith(":v2")
'''
strict_test_new = r'''def test_set_serialization_is_canonical_and_typed():
    from custom_code.rubin_evidence import _typed_normal_form
    left = _typed_normal_form({"items": {"b", "a"}})
    right = _typed_normal_form({"items": {"a", "b"}})
    assert left == right
    assert left[0] == "map"


def test_hash_protocol_version_is_explicitly_v3():
    from custom_code.rubin_evidence import ALERT_HASH_DOMAIN, CONTEXT_HASH_DOMAIN, TYPED_NORMAL_FORM
    assert ALERT_HASH_DOMAIN.endswith(":v3")
    assert CONTEXT_HASH_DOMAIN.endswith(":v3")
    assert TYPED_NORMAL_FORM == "trove-typed-normal-form:v1"
'''
base.TEST_MODULE = replace_once(base.TEST_MODULE, strict_test_old, strict_test_new)

base.TEST_MODULE += r"""


def test_typed_normal_form_prevents_old_sentinel_collisions():
    from custom_code.rubin_evidence import _typed_normal_form
    encoded_bytes = _typed_normal_form(b"x")
    literal_bytes_mapping = _typed_normal_form({"__trove_bytes_base64__": "eA=="})
    encoded_nan = _typed_normal_form(float("nan"))
    literal_nan_mapping = _typed_normal_form({"__trove_nonfinite_float__": "NaN"})
    assert encoded_bytes != literal_bytes_mapping
    assert encoded_nan != literal_nan_mapping
    assert _typed_normal_form(True) != _typed_normal_form(1)
    assert _typed_normal_form(-0.0) != _typed_normal_form(0.0)


@DB
def test_zero_valued_rubin_id_is_preserved():
    p = payload(); alert = as_alert(first_rubin(p))
    result = ingest_antares_rubin_delivery(
        alert,
        locus_context=as_context(p["locus"]),
        delivery_metadata={"delivery_id":"v3:zero-id"},
    )
    row = RubinAlertEvidence.objects.get(pk=result.alert_evidence_id)
    assert row.ss_object_id == "0"


@DB
def test_kafka_coordinates_require_transport_namespace():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    with pytest.raises(ValueError, match="transport_namespace"):
        ingest_antares_rubin_delivery(
            alert,
            locus_context=context,
            delivery_metadata={"topic":"rubin", "partition":1, "offset":2},
        )
    assert RubinEvidenceDelivery.objects.count() == 0


@DB
def test_same_kafka_position_is_distinct_across_transport_namespaces():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    shared = {"topic":"rubin", "partition":7, "offset":88}
    a = ingest_antares_rubin_delivery(
        alert,
        locus_context=context,
        delivery_metadata={**shared, "transport_namespace":"antares:prod"},
    )
    b = ingest_antares_rubin_delivery(
        alert,
        locus_context=context,
        delivery_metadata={**shared, "transport_namespace":"antares:staging"},
    )
    assert a.delivery_id != b.delivery_id
    assert RubinEvidenceDelivery.objects.count() == 2


@DB
def test_ancillary_metadata_is_preserved_but_not_delivery_identity():
    p = payload(); alert = as_alert(first_rubin(p)); context = as_context(p["locus"])
    identity = {
        "delivery_id":"broker:ancillary",
        "transport_namespace":"antares:prod",
        "topic":"rubin",
        "partition":9,
        "offset":123,
    }
    first = ingest_antares_rubin_delivery(
        alert,
        locus_context=context,
        delivery_metadata={**identity, "consumer_received_at":"first", "retry_count":0},
    )
    second = ingest_antares_rubin_delivery(
        alert,
        locus_context=context,
        delivery_metadata={**identity, "consumer_received_at":"second", "retry_count":1},
    )
    assert first.delivery_id == second.delivery_id
    assert second.delivery_created is False
    row = RubinEvidenceDelivery.objects.get()
    assert row.transport_namespace == "antares:prod"
    assert RubinEvidenceDelivery.objects.count() == 1


@DB
def test_actual_antares_runtime_models_match_fixture_identity():
    from antares_client.models import Alert, Locus

    p = payload(); raw = deepcopy(first_rubin(p)); props = raw["properties"]
    simple = ingest_antares_rubin_delivery(
        as_alert(raw),
        locus_context=as_context(p["locus"]),
        delivery_metadata={"delivery_id":"runtime:simple"},
    )
    processed_at = datetime.fromisoformat(raw["processed_at"]) if raw.get("processed_at") else None
    runtime_alert = Alert(
        alert_id=raw["alert_id"],
        mjd=raw["mjd"],
        properties=deepcopy(props),
        processed_at=processed_at,
        grav_wave_events=deepcopy(raw.get("grav_wave_events", [])),
    )
    runtime_locus = Locus(
        locus_id=p["locus"]["locus_id"],
        ra=float(props["lsst_diaSource_ra"]),
        dec=float(props["lsst_diaSource_dec"]),
        properties={},
        tags=deepcopy(p["locus"].get("tags", [])),
        alerts=[],
        grav_wave_events=deepcopy(p["locus"].get("grav_wave_events", [])),
    )
    runtime = ingest_antares_rubin_delivery(
        runtime_alert,
        locus_context=runtime_locus,
        delivery_metadata={"delivery_id":"runtime:client-model"},
    )
    assert runtime.alert_evidence_id == simple.alert_evidence_id
    assert runtime.broker_context_id == simple.broker_context_id
    row = RubinAlertEvidence.objects.get(pk=runtime.alert_evidence_id)
    assert row.ss_object_id == "0"
"""

# The strict builder now generates the narrow v3 evidence protocol patch.
'''

source = source.replace(
    marker,
    protocol_v3 + "\n# The base builder now generates the hardened v3 evidence protocol patch.\nbase.main()'''",
    1,
)
exec(compile(source, RELATIVE_PATH, "exec"), {"__name__": "__main__", "__file__": str(Path(__file__))})
