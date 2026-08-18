import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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
REAL_MULTI_DIR = BRIDGE_ROOT / "fixtures" / "real_multi"
DB_MARK = pytest.mark.django_db(transaction=True, databases=["default", "catalogs"])


def load_target(path: Path):
    payload = json.loads(path.read_text())
    return normalize_antares_locus(payload["locus"])


def all_real_targets():
    manifest = json.loads((REAL_DIR / "manifest.json").read_text())
    return [load_target(REAL_DIR / item["file"]) for item in manifest["fixtures"]]


def replay_target():
    return min(all_real_targets(), key=lambda target: len(target.observations))


def incremental_target():
    manifest = json.loads((REAL_MULTI_DIR / "manifest.json").read_text())
    target = load_target(REAL_MULTI_DIR / manifest["file"])
    assert manifest["rubin_alert_count"] >= 2
    assert len(target.observations) == manifest["rubin_alert_count"]
    return target


@pytest.fixture
def isolate_persistence_from_trove_science_hook():
    """Exercise TROVE's real ORM/test DB without firing science before photometry exists.

    TOM Toolkit BaseTarget.save() unconditionally calls target_post_save. A Rubin
    handler that wants exactly-once vetting must therefore control that sequencing:
    persist target, persist new photometry, then vet once if new evidence arrived.
    These tests validate the persistence phase only.
    """
    with patch("tom_targets.base_models.run_hook") as hook:
        yield hook


@DB_MARK
def test_real_rubin_fixture_persists_into_trove_models_and_replay_is_idempotent(
    isolate_persistence_from_trove_science_hook,
):
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
    assert isolate_persistence_from_trove_science_hook.call_count == 1


@DB_MARK
def test_incremental_rubin_delivery_inserts_only_unseen_photometry_and_requests_revet(
    isolate_persistence_from_trove_science_hook,
):
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
    assert isolate_persistence_from_trove_science_hook.call_count == 1
