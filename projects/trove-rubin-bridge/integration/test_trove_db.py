import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

BRIDGE_ROOT = Path(os.environ["TROVE_RUBIN_BRIDGE_ROOT"])
sys.path.insert(0, str(BRIDGE_ROOT / "src"))

from trove_rubin_bridge.adapter import normalize_antares_locus  # noqa: E402
from trove_rubin_bridge.trove_native import ingest_into_trove  # noqa: E402
from tom_dataproducts.models import ReducedDatum  # noqa: E402
from trove_targets.models import Target  # noqa: E402

REAL_DIR = BRIDGE_ROOT / "fixtures" / "real"
FIXTURE = REAL_DIR / "antares_lsst_['170666303786319881'].json"


def load_target():
    payload = json.loads(FIXTURE.read_text())
    return normalize_antares_locus(payload["locus"])


@pytest.mark.django_db(transaction=True)
def test_real_rubin_fixture_persists_into_trove_models_and_replay_is_idempotent():
    target = load_target()

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


@pytest.mark.django_db(transaction=True)
def test_incremental_rubin_delivery_inserts_only_unseen_photometry_and_requests_revet():
    target = load_target()
    assert len(target.observations) >= 2

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
