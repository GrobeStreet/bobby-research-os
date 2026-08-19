from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trove_tom.settings")

import django

django.setup()

from django.db import connection

from custom_code.models import (
    RubinAlertEvidence,
    RubinBrokerContextEvidence,
    RubinEvidenceDelivery,
)
from custom_code.rubin_evidence import ingest_antares_rubin_delivery


def as_alert(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(**payload)


def as_context(locus: dict) -> SimpleNamespace:
    # Deliberately expose only context fields. There is no locus.alerts/history path.
    return SimpleNamespace(
        locus_id=locus["locus_id"],
        tags=deepcopy(locus.get("tags", [])),
        grav_wave_events=deepcopy(locus.get("grav_wave_events", [])),
    )


def real_rubin_alert(payload: dict) -> dict:
    return next(
        alert for alert in payload["locus"]["alerts"]
        if str(alert.get("alert_id", "")).startswith("lsst:")
    )


def json_bytes(value) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def row_size(table: str, pk: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT pg_column_size(t) FROM "{table}" AS t WHERE id = %s', [pk])
        return int(cursor.fetchone()[0])


def relation_sizes(table: str) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              pg_relation_size(%s::regclass),
              pg_indexes_size(%s::regclass),
              pg_total_relation_size(%s::regclass)
            """,
            [table, table, table],
        )
        heap_bytes, index_bytes, total_bytes = cursor.fetchone()
    return {
        "heap_bytes": int(heap_bytes),
        "index_bytes": int(index_bytes),
        "total_bytes": int(total_bytes),
    }


def snapshot(label: str) -> dict:
    tables = {
        "alert": RubinAlertEvidence._meta.db_table,
        "context": RubinBrokerContextEvidence._meta.db_table,
        "delivery": RubinEvidenceDelivery._meta.db_table,
    }
    return {
        "label": label,
        "counts": {
            "alerts": RubinAlertEvidence.objects.count(),
            "contexts": RubinBrokerContextEvidence.objects.count(),
            "deliveries": RubinEvidenceDelivery.objects.count(),
        },
        "relations": {name: relation_sizes(table) for name, table in tables.items()},
    }


def main() -> None:
    if connection.vendor != "postgresql":
        raise RuntimeError("storage benchmark must run on PostgreSQL")

    fixture = Path("tests/data/antares_rubin_delivery.json")
    payload = json.loads(fixture.read_text())
    alert_dict = real_rubin_alert(payload)
    context_dict = payload["locus"]
    alert = as_alert(alert_dict)
    context = as_context(context_dict)

    result: dict = {
        "database": "PostgreSQL",
        "fixture_locus_id": context_dict["locus_id"],
        "source_alert_id": alert_dict["alert_id"],
        "input_json_bytes": {
            "alert_projection": json_bytes(alert_dict),
            "context_projection": json_bytes({
                "locus_id": context_dict["locus_id"],
                "tags": context_dict.get("tags", []),
                "grav_wave_events": context_dict.get("grav_wave_events", []),
            }),
        },
        "snapshots": [snapshot("empty")],
    }

    first = ingest_antares_rubin_delivery(
        alert,
        locus_context=context,
        delivery_metadata={"topic": "trove-rubin-benchmark", "partition": 0, "offset": 1},
    )
    alert_row = RubinAlertEvidence.objects.get(pk=first.alert_evidence_id)
    context_row = RubinBrokerContextEvidence.objects.get(pk=first.context_evidence_id)
    delivery_row = RubinEvidenceDelivery.objects.get(pk=first.delivery_id)

    result["first_rows"] = {
        "alert_pg_column_size": row_size(RubinAlertEvidence._meta.db_table, alert_row.pk),
        "context_pg_column_size": row_size(RubinBrokerContextEvidence._meta.db_table, context_row.pk),
        "delivery_pg_column_size": row_size(RubinEvidenceDelivery._meta.db_table, delivery_row.pk),
        "stored_alert_snapshot_json_bytes": json_bytes(alert_row.broker_alert_snapshot),
        "stored_context_snapshot_json_bytes": json_bytes(context_row.context_snapshot),
    }
    result["snapshots"].append(snapshot("one_alert_one_context_one_delivery"))

    # 100 observed deliveries of the exact same immutable alert/context. The alert
    # and context rows must remain one each; only compact delivery rows should grow.
    for offset in range(2, 101):
        ingest_antares_rubin_delivery(
            alert,
            locus_context=context,
            delivery_metadata={
                "topic": "trove-rubin-benchmark",
                "partition": 0,
                "offset": offset,
            },
        )
    assert RubinAlertEvidence.objects.count() == 1
    assert RubinBrokerContextEvidence.objects.count() == 1
    assert RubinEvidenceDelivery.objects.count() == 100
    result["snapshots"].append(snapshot("one_alert_one_context_100_deliveries"))

    # Evolve mutable broker context 20 times. This must add only context+delivery
    # rows; it must never duplicate the full Rubin alert snapshot.
    for version in range(1, 21):
        changed_context = as_context(context_dict)
        changed_context.tags = list(changed_context.tags) + [f"benchmark-context-v{version:02d}"]
        ingest_antares_rubin_delivery(
            alert,
            locus_context=changed_context,
            delivery_metadata={
                "topic": "trove-rubin-benchmark",
                "partition": 1,
                "offset": version,
            },
        )
    assert RubinAlertEvidence.objects.count() == 1
    assert RubinBrokerContextEvidence.objects.count() == 21
    assert RubinEvidenceDelivery.objects.count() == 120
    result["snapshots"].append(snapshot("one_alert_21_contexts_120_deliveries"))

    # A materially changed alert payload is a real second alert-evidence snapshot.
    changed_alert_dict = deepcopy(alert_dict)
    changed_alert_dict["properties"]["lsst_diaSource_psfFlux"] -= 1.0
    ingest_antares_rubin_delivery(
        as_alert(changed_alert_dict),
        locus_context=context,
        delivery_metadata={
            "topic": "trove-rubin-benchmark",
            "partition": 2,
            "offset": 1,
        },
    )
    assert RubinAlertEvidence.objects.count() == 2
    assert RubinEvidenceDelivery.objects.count() == 121
    result["snapshots"].append(snapshot("two_alert_versions_21_contexts_121_deliveries"))

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
