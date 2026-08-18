from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from antares_client import search

OUT_DIR = Path("projects/trove-rubin-bridge/fixtures/real_multi")
MAX_SCAN = 250


def json_default(value: Any):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


def serialize_locus(locus) -> dict:
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
        "alerts": [
            {
                "alert_id": alert.alert_id,
                "mjd": alert.mjd,
                "processed_at": alert.processed_at,
                "properties": alert.properties,
                "grav_wave_events": alert.grav_wave_events,
            }
            for alert in locus.alerts
        ],
    }


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=json_default).encode()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    query = {"query": {"exists": {"field": "properties.survey.lsst.dia_object_id"}}}
    scanned = 0
    best = None
    best_count = 0

    for locus in itertools.islice(search.search(query), MAX_SCAN):
        scanned += 1
        serialized = serialize_locus(locus)
        rubin_alerts = [a for a in serialized["alerts"] if str(a.get("alert_id", "")).startswith("lsst:")]
        count = len(rubin_alerts)
        if count > best_count:
            best = serialized
            best_count = count
            print(f"new_best locus={locus.locus_id} rubin_alerts={count} total_alerts={len(serialized['alerts'])}")
        if count >= 2:
            break

    if best is None:
        raise RuntimeError("No LSST-associated ANTARES loci returned")
    if best_count < 2:
        raise RuntimeError(f"Scanned {scanned} LSST-associated loci; best Rubin alert count was {best_count}")

    retrieved_at = datetime.now(timezone.utc).isoformat()
    lsst_ids = (((best.get("properties") or {}).get("survey") or {}).get("lsst") or {}).get("dia_object_id") or []
    payload = {
        "fixture_provenance": {
            "source": "ANTARES public live database",
            "retrieved_at_utc": retrieved_at,
            "antares_client_version": version("antares-client"),
            "selection": f"first locus within {MAX_SCAN} LSST-associated search results with >=2 lsst: alerts",
            "scanned_loci": scanned,
        },
        "locus": best,
    }
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    filename = "antares_lsst_multi.json"
    (OUT_DIR / filename).write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n")
    manifest = {
        "source": "ANTARES public live database",
        "retrieved_at_utc": retrieved_at,
        "antares_client_version": version("antares-client"),
        "scanned_loci": scanned,
        "locus_id": best["locus_id"],
        "lsst_dia_object_id": lsst_ids,
        "rubin_alert_count": best_count,
        "total_alert_count": len(best["alerts"]),
        "sha256_canonical_json": digest,
        "file": filename,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
