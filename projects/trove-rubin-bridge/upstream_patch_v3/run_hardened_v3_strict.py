from __future__ import annotations

import subprocess
from pathlib import Path

REVIEWED_COMMIT = "d5cf21aec1f8b8105c9d34920b509410cca4deb6"
RELATIVE_PATH = "projects/trove-rubin-bridge/upstream_patch_v3/run_hardened_v3.py"
repo_root = Path(__file__).resolve().parents[3]
source = subprocess.run(
    ["git", "show", f"{REVIEWED_COMMIT}:{RELATIVE_PATH}"],
    cwd=repo_root,
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout

old_q = 'condition=models.Q(("offset__isnull", False), ("partition__isnull", False), ("topic__gt", "")),'
new_q = 'condition=models.Q(("topic__gt", ""), ("partition__isnull", False), ("offset__isnull", False)),'
if source.count(old_q) != 1:
    raise RuntimeError("Expected exactly one migration condition in reviewed hardening source")
source = source.replace(old_q, new_q, 1)

marker = '''# The base builder now generates the hardened patch with the stricter model/function/tests.\nbase.main()'''
if source.count(marker) != 1:
    raise RuntimeError("Could not locate reviewed hardening finalization marker")

strict_injection = r"""# Canonicalization is part of the evidence protocol. Unknown Python reprs are not
# acceptable evidence identity because repr() may contain process-specific memory
# addresses. Mapping keys must remain strings so JSON normalization cannot collapse
# distinct Python keys such as 1 and "1". This is a protocol change, so bump both
# canonicalization/hash domains rather than silently changing v1 semantics.
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    'canonicalization_version = models.CharField(max_length=50, default="alert-v1")',
    'canonicalization_version = models.CharField(max_length=50, default="alert-v2")',
)
base.MODEL_ADDITION = replace_once(
    base.MODEL_ADDITION,
    'canonicalization_version = models.CharField(max_length=50, default="context-v1")',
    'canonicalization_version = models.CharField(max_length=50, default="context-v2")',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '("canonicalization_version", models.CharField(default="alert-v1", max_length=50)),',
    '("canonicalization_version", models.CharField(default="alert-v2", max_length=50)),',
)
base.MIGRATION = replace_once(
    base.MIGRATION,
    '("canonicalization_version", models.CharField(default="context-v1", max_length=50)),',
    '("canonicalization_version", models.CharField(default="context-v2", max_length=50)),',
)
base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    'ALERT_HASH_DOMAIN = "trove-rubin-alert-evidence:v1"',
    'ALERT_HASH_DOMAIN = "trove-rubin-alert-evidence:v2"',
)
base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    'CONTEXT_HASH_DOMAIN = "trove-rubin-broker-context:v1"',
    'CONTEXT_HASH_DOMAIN = "trove-rubin-broker-context:v2"',
)
base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    '"canonicalization_version": "alert-v1",',
    '"canonicalization_version": "alert-v2",',
)
base.INGRESS_MODULE = replace_once(
    base.INGRESS_MODULE,
    '"canonicalization_version": "context-v1",',
    '"canonicalization_version": "context-v2",',
)

strict_old = """def _json_safe(value: Any) -> Any:
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
"""

strict_new = """def _json_safe(value: Any) -> Any:
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
        non_string_keys = [key for key in value if not isinstance(key, str)]
        if non_string_keys:
            raise TypeError("Broker evidence mappings must use string keys")
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        safe = [_json_safe(item) for item in value]
        return sorted(
            safe,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ),
        )
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            converted = item_method()
        except (TypeError, ValueError):
            converted = value
        if converted is not value:
            return _json_safe(converted)
    raise TypeError(
        "Unsupported broker evidence type: "
        f"{value.__class__.__module__}.{value.__class__.__qualname__}"
    )
"""
base.INGRESS_MODULE = replace_once(base.INGRESS_MODULE, strict_old, strict_new)

base.TEST_MODULE += r'''

@DB
def test_unknown_python_objects_fail_closed_instead_of_hashing_repr():
    p = payload(); alert = deepcopy(first_rubin(p))
    alert["properties"]["unsupported"] = object()
    with pytest.raises(TypeError, match="Unsupported broker evidence type"):
        ingest_antares_rubin_delivery(
            as_alert(alert),
            locus_context=as_context(p["locus"]),
            delivery_metadata={"delivery_id":"strict:unknown"},
        )
    assert RubinAlertEvidence.objects.count() == 0
    assert RubinEvidenceDelivery.objects.count() == 0


@DB
def test_non_string_mapping_keys_fail_closed_without_key_collision():
    p = payload(); alert = deepcopy(first_rubin(p))
    alert["properties"]["nested"] = {1: "integer-key", "1": "string-key"}
    with pytest.raises(TypeError, match="string keys"):
        ingest_antares_rubin_delivery(
            as_alert(alert),
            locus_context=as_context(p["locus"]),
            delivery_metadata={"delivery_id":"strict:keys"},
        )
    assert RubinAlertEvidence.objects.count() == 0


def test_set_serialization_is_canonical_and_not_repr_ordered():
    from custom_code.rubin_evidence import _json_safe
    left = _json_safe({"items": {"b", "a"}})
    right = _json_safe({"items": {"a", "b"}})
    assert left == right == {"items": ["a", "b"]}


def test_hash_protocol_version_is_explicitly_v2():
    from custom_code.rubin_evidence import ALERT_HASH_DOMAIN, CONTEXT_HASH_DOMAIN
    assert ALERT_HASH_DOMAIN.endswith(":v2")
    assert CONTEXT_HASH_DOMAIN.endswith(":v2")
'''

# The base builder now generates the hardened, strict-canonicalization patch.
base.main()"""

source = source.replace(marker, strict_injection, 1)
exec(compile(source, RELATIVE_PATH, "exec"), {"__name__": "__main__", "__file__": str(Path(__file__))})
