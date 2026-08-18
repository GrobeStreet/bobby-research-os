from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from antares_client import search

DOCUMENTED_LSST_DIA_OBJECT_ID = "169342393603063964"
OUT_DIR = Path("projects/trove-rubin-bridge/fixtures/real")
MAX_LOCI = 5


def json_default(value: Any):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


def nested_get(mapping: dict, path: str):
    current: Any = mapping
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def serialize_locus(locus) -> dict:
    alerts = []
    for alert in locus.alerts:
        alerts.append(
            {
                "alert_id": alert.alert_id,
                "mjd": alert.mjd,
                "processed_at": alert.processed_at,
                "properties": alert.properties,
                "grav_wave_events": alert.grav_wave_events,
            }
        )

    return {
        "locus_id": locus.locus_id,
        "ra": locus.ra,
        "dec": locus.dec,
        "properties": locus.properties,
        "tags": locus.tags,
        "catalogs": locus.catalogs,
        "watch_list_ids": locus.watch_list_ids,
        "watch_object_ids": locus.watch_object_ids,
        "grav_wave_events": locus.grav_wave_events,
        "alerts": alerts,
    }


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    ).encode("utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    loci = []
    seen = set()

    documented = search.get_by_lsst_dia_object_id(DOCUMENTED_LSST_DIA_OBJECT_ID)
    if documented is not None:
        loci.append(documented)
        seen.add(documented.locus_id)

    query = {
        "query": {
            "exists": {
                "field": "properties.survey.lsst.dia_object_id"
            }
        }
    }
    for locus in itertools.islice(search.search(query), MAX_LOCI * 3):
        if locus.locus_id in seen:
            continue
        loci.append(locus)
        seen.add(locus.locus_id)
        if len(loci) >= MAX_LOCI:
            break

    if not loci:
        raise RuntimeError("ANTARES public search returned no LSST loci")

    retrieved_at = datetime.now(timezone.utc).isoformat()
    records = []

    for index, locus in enumerate(loci[:MAX_LOCI], start=1):
        serialized = serialize_locus(locus)
        dia_object_id = nested_get(
            serialized.get("properties", {}),
            "survey.lsst.dia_object_id",
        )
        payload = {
            "fixture_provenance": {
                "source": "ANTARES public live database",
                "retrieved_at_utc": retrieved_at,
                "antares_client_version": version("antares-client"),
                "lookup_method": (
                    "get_by_lsst_dia_object_id"
                    if str(dia_object_id) == DOCUMENTED_LSST_DIA_OBJECT_ID
                    else "search exists properties.survey.lsst.dia_object_id"
                ),
                "documented_example_lsst_dia_object_id": DOCUMENTED_LSST_DIA_OBJECT_ID,
            },
            "locus": serialized,
        }
        digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        safe_id = str(dia_object_id or locus.locus_id).replace("/", "_")
        filename = f"antares_lsst_{safe_id}.json"
        path = OUT_DIR / filename
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
            encoding="utf-8",
        )
        records.append(
            {
                "file": filename,
                "sha256_canonical_json": digest,
                "locus_id": locus.locus_id,
                "lsst_dia_object_id": dia_object_id,
                "alert_count": len(serialized["alerts"]),
                "locus_grav_wave_events": serialized["grav_wave_events"],
                "alert_grav_wave_association_count": sum(
                    len(a.get("grav_wave_events") or []) for a in serialized["alerts"]
                ),
            }
        )

    manifest = {
        "retrieved_at_utc": retrieved_at,
        "source": "ANTARES public live database",
        "antares_client_version": version("antares-client"),
        "documented_example_lsst_dia_object_id": DOCUMENTED_LSST_DIA_OBJECT_ID,
        "fixture_count": len(records),
        "fixtures": records,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
