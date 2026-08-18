import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

BRIDGE_ROOT = Path(os.environ["TROVE_RUBIN_BRIDGE_ROOT"])
sys.path.insert(0, str(BRIDGE_ROOT / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trove_tom.settings")

import django  # noqa: E402

django.setup()

from trove_rubin_bridge.adapter import normalize_antares_locus  # noqa: E402
from trove_rubin_bridge.trove_native import ingest_into_trove  # noqa: E402
from tom_dataproducts.models import ReducedDatum  # noqa: E402
from trove_targets.models import Target  # noqa: E402

REAL_DIR = BRIDGE_ROOT / "fixtures" / "real"
DB_MARK = pytest.mark.django_db(transaction=True, databases=["default", "catalogs"])


def all_real_targets():
    manifest = json.loads((REAL_DIR / "manifest.json").read_text())
    targets = []
    for item in manifest["fixtures"]:
        payload = json.loads((REAL_DIR / item["file"]).read_text())
        targets.append(normalize_antares_locus(payload["locus"]))
    return targets


def replay_target():
    # Choose the smallest normalized real fixture for the full replay assertion.
    return min(all_real_targets(), key=lambda target: len(target.observations))


def incremental_target():
    candidates = [target for target in all_real_targets() if len(target.observations) >= 2]
    assert candidates, "Frozen real fixture set must contain a Rubin locus with >=2 Rubin alerts"
    return min(candidates, key=lambda target: len(target.observations))


@DB_MARK
def test_real_rubin_fixture_persists_into_trove_models_and_replay_is_idempotent():
    target = replay_target()

    first = ingest_into_trove(target)
    assert first.target_created is True
    assert first.observations_created == len(target.observations)
    assert first.observations_duplicate == 0
    assert first.should_revet is True

    assert Target.objects.filter(name=target.trove_target_name).count() == 1
    db_target = Target.objects.get(name=target.trove_target_name)
    rows = ReducedDatum.objects.filter(target=db_target, data_type="photometry")
    assert rows.count() == len(target.observations)
    assert set(rows.values_list("source_name", flat=True)) == {"Rubin/ANTARES"}
    assert all(
        str(source_location).startswith("lsst:")
        for source_location in rows.values_list("source_location", flat=True)
    )

    second = ingest_into_trove(target)
    assert second.target_created is False
    assert second.observations_created == 0
    assert second.observations_duplicate == len(target.observations)
    assert second.should_revet is False

    assert Target.objects.filter(name=target.trove_target_name).count() == 1
    assert ReducedDatum.objects.filter(target=db_target, data_type="photometry").count() == len(target.observations)


@DB_MARK
def test_incremental_rubin_delivery_inserts_only_unseen_photometry_and_requests_revet():
    target = incremental_target()

    partial = replace(
        target,
        observations=target.observations[:1],
        first_seen_at=target.observations[0].observed_at,
    )

    first = ingest_into_trove(partial)
    assert first.observations_created == 1
    assert first.should_revet is True

    second = ingest_into_trove(target)
    assert second.target_created is False
    assert second.observations_created == len(target.observations) - 1
    assert second.observations_duplicate == 1
    assert second.should_revet is True

    third = ingest_into_trove(target)
    assert third.observations_created == 0
    assert third.observations_duplicate == len(target.observations)
    assert third.should_revet is False

    db_target = Target.objects.get(name=target.trove_target_name)
    assert ReducedDatum.objects.filter(target=db_target, data_type="photometry").count() == len(target.observations)
