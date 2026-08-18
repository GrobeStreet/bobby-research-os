from __future__ import annotations

import build_evidence_patch as builder

# Preserve the minimal mutable broker context that can explain why TROVE received
# an otherwise unchanged Rubin alert. Do not pull the entire cross-survey locus
# history into the scientific evidence record.
builder.MODEL_ADDITION = builder.MODEL_ADDITION.replace(
    '    grav_wave_events = models.JSONField(default=list)\n    raw_alert = models.JSONField()\n',
    '    grav_wave_events = models.JSONField(default=list)\n'
    '    broker_context = models.JSONField(default=dict)\n'
    '    raw_alert = models.JSONField()\n',
)

builder.MIGRATION = builder.MIGRATION.replace(
    '                ("grav_wave_events", models.JSONField(default=list)),\n'
    '                ("raw_alert", models.JSONField()),\n',
    '                ("grav_wave_events", models.JSONField(default=list)),\n'
    '                ("broker_context", models.JSONField(default=dict)),\n'
    '                ("raw_alert", models.JSONField()),\n',
)

builder.EVIDENCE_MODULE = builder.EVIDENCE_MODULE.replace(
    'def _is_rubin_alert(alert: Any) -> bool:\n',
    '''def _broker_context(locus: Any) -> dict[str, Any]:\n    """Preserve routing/GW context without copying unrelated locus history."""\n\n    return _json_safe(\n        {\n            "locus_id": _get(locus, "locus_id"),\n            "tags": _get(locus, "tags", []) or [],\n            "grav_wave_events": _get(locus, "grav_wave_events", []) or [],\n        }\n    )\n\n\ndef _is_rubin_alert(alert: Any) -> bool:\n''',
)

builder.EVIDENCE_MODULE = builder.EVIDENCE_MODULE.replace(
    'def _snapshot_defaults(locus: Any, alert: Any, raw_alert: dict[str, Any]) -> dict[str, Any]:\n',
    'def _snapshot_defaults(\n    locus: Any,\n    alert: Any,\n    raw_alert: dict[str, Any],\n    broker_context: dict[str, Any],\n) -> dict[str, Any]:\n',
).replace(
    '        "grav_wave_events": _json_safe(_get(alert, "grav_wave_events", []) or []),\n'
    '        "raw_alert": raw_alert,\n',
    '        "grav_wave_events": _json_safe(_get(alert, "grav_wave_events", []) or []),\n'
    '        "broker_context": broker_context,\n'
    '        "raw_alert": raw_alert,\n',
).replace(
    '            raw_alert = _alert_payload(alert)\n'
    '            digest = hashlib.sha256(_canonical_json_bytes(raw_alert)).hexdigest()\n',
    '            raw_alert = _alert_payload(alert)\n'
    '            broker_context = _broker_context(locus)\n'
    '            digest = hashlib.sha256(\n'
    '                _canonical_json_bytes({"alert": raw_alert, "broker_context": broker_context})\n'
    '            ).hexdigest()\n',
).replace(
    '                defaults=_snapshot_defaults(locus, alert, raw_alert),\n',
    '                defaults=_snapshot_defaults(locus, alert, raw_alert, broker_context),\n',
)

# Prefer structural serialization for unexpected model-like values over reprs that
# may contain process-specific memory addresses.
builder.EVIDENCE_MODULE = builder.EVIDENCE_MODULE.replace(
    '    item_method = getattr(value, "item", None)\n',
    '''    fields = getattr(value, "__dict__", None)\n    if isinstance(fields, dict):\n        return {\n            "__trove_python_type__": f"{value.__class__.__module__}.{value.__class__.__qualname__}",\n            "__trove_object_fields__": _json_safe(fields),\n        }\n\n    item_method = getattr(value, "item", None)\n''',
)

builder.TEST_MODULE = builder.TEST_MODULE.replace(
    '        tags=locus.get("tags", []),\n        alerts=alerts,\n',
    '        tags=locus.get("tags", []),\n'
    '        grav_wave_events=locus.get("grav_wave_events", []),\n'
    '        alerts=alerts,\n',
)

builder.TEST_MODULE += r'''

@DB_MARK
def test_changed_locus_broker_context_is_preserved_as_new_snapshot():
    payload = _payload()
    rubin = next(a for a in payload["locus"]["alerts"] if a["alert_id"].startswith("lsst:"))
    payload["locus"]["alerts"] = [rubin]
    ingest_antares_rubin_evidence(_as_locus(payload))

    changed = deepcopy(payload)
    changed["locus"]["grav_wave_events"] = [
        {"gracedb_id": "SYNTHETIC-CONTEXT-CHANGE", "contour_level": 0.95}
    ]
    result = ingest_antares_rubin_evidence(_as_locus(changed))

    rows = RubinAlertEvidence.objects.filter(source_record_id=rubin["alert_id"])
    assert result.snapshots_created == 1
    assert result.changed_payload_snapshots == 1
    assert rows.count() == 2
    assert {bool(row.broker_context["grav_wave_events"]) for row in rows} == {False, True}
    # The alert payload itself was not rewritten to smuggle locus context into it.
    assert len({json.dumps(row.raw_alert, sort_keys=True) for row in rows}) == 1
'''

# Keep the compact real fixture capable of carrying locus-level context even when
# the selected public example currently has none.
_original_build_fixture = builder.build_fixture

def build_fixture_with_context() -> None:
    _original_build_fixture()
    path = builder.TROVE_ROOT / "tests" / "data" / "antares_rubin_evidence.json"
    payload = json.loads(path.read_text())
    payload["locus"].setdefault("grav_wave_events", [])
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# json is needed only by the deterministic fixture post-processing above.
import json
builder.build_fixture = build_fixture_with_context

builder.modify_trove()
builder.generate_patch()
print(builder.PATCH_PATH)
