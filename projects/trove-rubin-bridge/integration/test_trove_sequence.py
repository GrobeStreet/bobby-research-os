import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

BRIDGE_ROOT = Path(os.environ["TROVE_RUBIN_BRIDGE_ROOT"])
sys.path.insert(0, str(BRIDGE_ROOT / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trove_tom.settings")

import django  # noqa: E402

django.setup()

from trove_rubin_bridge.adapter import normalize_antares_locus  # noqa: E402
from trove_rubin_bridge.trove_sequence import (  # noqa: E402
    DEFER_TARGET_POST_SAVE_ATTR,
    ingest_then_vet,
)
from tom_dataproducts.models import ReducedDatum  # noqa: E402
from trove_targets.models import Target  # noqa: E402

MULTI = BRIDGE_ROOT / "fixtures" / "real_multi" / "antares_lsst_multi.json"
DB_MARK = pytest.mark.django_db(transaction=True, databases=["default", "catalogs"])


def load_multi_target():
    payload = json.loads(MULTI.read_text())
    return normalize_antares_locus(payload["locus"])


@DB_MARK
def test_new_rubin_evidence_vets_once_after_photometry_exists(monkeypatch):
    target = load_multi_target()
    partial = replace(
        target,
        observations=target.observations[:1],
        first_seen_at=target.observations[0].observed_at,
    )

    observed_counts = []

    def fake_vet(trove_target, *, created=True):
        observed_counts.append(
            ReducedDatum.objects.filter(
                target=trove_target,
                data_type="photometry",
                source_name="Rubin/ANTARES",
            ).count()
        )
        assert created is True

    result = ingest_then_vet(partial, vet_callable=fake_vet)

    assert result.target_created is True
    assert result.observations_created == 1
    assert result.observations_duplicate == 0
    assert result.vetting_invocations == 1
    assert observed_counts == [1]

    db_target = Target.objects.get(name=partial.trove_target_name)
    assert not hasattr(db_target, DEFER_TARGET_POST_SAVE_ATTR)
    assert ReducedDatum.objects.filter(target=db_target).count() == 1


@DB_MARK
def test_duplicate_delivery_vets_zero_times():
    target = load_multi_target()
    partial = replace(
        target,
        observations=target.observations[:1],
        first_seen_at=target.observations[0].observed_at,
    )

    vet = Mock()
    first = ingest_then_vet(partial, vet_callable=vet)
    assert first.vetting_invocations == 1
    assert vet.call_count == 1

    second = ingest_then_vet(partial, vet_callable=vet)
    assert second.target_created is False
    assert second.observations_created == 0
    assert second.observations_duplicate == 1
    assert second.vetting_invocations == 0
    assert vet.call_count == 1


@DB_MARK
def test_incremental_delivery_vets_exactly_once_per_new_evidence_batch():
    target = load_multi_target()
    assert len(target.observations) == 2

    partial = replace(
        target,
        observations=target.observations[:1],
        first_seen_at=target.observations[0].observed_at,
    )

    seen_counts = []

    def fake_vet(trove_target, *, created=True):
        seen_counts.append(
            ReducedDatum.objects.filter(
                target=trove_target,
                data_type="photometry",
                source_name="Rubin/ANTARES",
            ).count()
        )

    first = ingest_then_vet(partial, vet_callable=fake_vet)
    second = ingest_then_vet(target, vet_callable=fake_vet)
    third = ingest_then_vet(target, vet_callable=fake_vet)

    assert first.vetting_invocations == 1
    assert second.vetting_invocations == 1
    assert third.vetting_invocations == 0
    assert seen_counts == [1, 2]

    assert second.observations_created == 1
    assert second.observations_duplicate == 1
    assert third.observations_created == 0
    assert third.observations_duplicate == 2


@DB_MARK
def test_real_trove_hook_guard_defers_only_marked_target(monkeypatch):
    """Prove the proposed tiny upstream guard prevents premature science only."""
    from custom_code import hooks

    calls = []

    monkeypatch.setattr(hooks, "vet_basic", lambda *args, **kwargs: calls.append("vet_basic"))
    monkeypatch.setattr(hooks, "associate_nle_with_target", lambda *args, **kwargs: [])

    target = Target(
        name="LSST-DEFER-GUARD-TEST",
        type="SIDEREAL",
        ra=10.0,
        dec=-20.0,
        permissions="PUBLIC",
    )
    setattr(target, DEFER_TARGET_POST_SAVE_ATTR, True)

    # This test assumes the proposed guard is installed by the integration harness
    # into TROVE's custom_code/hooks.py before pytest runs.
    messages, status = hooks.target_post_save(target, created=True)
    assert messages == []
    assert status is None
    assert calls == []
