import json
from datetime import timedelta
from pathlib import Path

import pytest

from trove_rubin_bridge.adapter import SchemaError, normalize_antares_locus
from trove_rubin_bridge.gating import eligible_for_event
from trove_rubin_bridge.ledger import InMemoryIngestLedger
from trove_rubin_bridge.mapping import build_trove_handoff

FIXTURE = Path(__file__).parents[1] / "fixtures" / "antares_lsst_locus.synthetic.json"


def load_fixture():
    return json.loads(FIXTURE.read_text())


def test_normalization_preserves_identity_coordinates_gw_and_photometry():
    target = normalize_antares_locus(load_fixture())
    assert target.locus_id == "ANT2026synthetic"
    assert target.idempotency_key == "ANTARES:ANT2026synthetic"
    assert target.lsst_dia_object_id == "169342393603063964"
    assert target.grav_wave_events == ["SYNTHETIC_GW_EVENT"]
    assert [(o.band, o.magnitude) for o in target.observations] == [
        ("r", 20.10),
        ("g", 20.42),
    ]


def test_duplicate_delivery_is_idempotent():
    target = normalize_antares_locus(load_fixture())
    ledger = InMemoryIngestLedger()
    first = ledger.ingest(target)
    second = ledger.ingest(target)
    assert first.target_created is True
    assert first.observations_created == 2
    assert second.target_created is False
    assert second.observations_created == 0
    assert second.observations_duplicate == 2
    assert ledger.observation_count(target.idempotency_key) == 2


def test_incremental_locus_delivery_adds_only_new_alert():
    payload = load_fixture()
    first_delivery = dict(payload)
    first_delivery["alerts"] = payload["alerts"][:1]

    ledger = InMemoryIngestLedger()
    a = normalize_antares_locus(first_delivery)
    b = normalize_antares_locus(payload)
    assert ledger.ingest(a).observations_created == 1
    result = ledger.ingest(b)
    assert result.observations_created == 1
    assert result.observations_duplicate == 1
    assert ledger.observation_count(a.idempotency_key) == 2


def test_historical_view_does_not_look_ahead():
    target = normalize_antares_locus(load_fixture())
    cutoff = target.observations[0].observed_at + timedelta(seconds=1)
    historical = target.observations_as_of(cutoff)
    assert [o.alert_id for o in historical] == ["lsst:synthetic-alert-1"]


def test_event_gate_requires_broker_association_and_time_window():
    target = normalize_antares_locus(load_fixture())
    event_time = target.first_seen_at - timedelta(hours=2)
    assert eligible_for_event(target, "SYNTHETIC_GW_EVENT", event_time)
    assert not eligible_for_event(target, "OTHER_EVENT", event_time)
    assert not eligible_for_event(
        target,
        "SYNTHETIC_GW_EVENT",
        target.first_seen_at - timedelta(days=20),
    )


def test_trove_handoff_preserves_provenance_and_photometry_shape():
    target = normalize_antares_locus(load_fixture())
    plan = build_trove_handoff(target)
    assert plan["external_identity"]["antares_locus_id"] == target.locus_id
    assert plan["reduced_data"][0]["source_name"] == "Rubin/ANTARES"
    assert plan["reduced_data"][0]["source_location"] == "lsst:synthetic-alert-1"
    assert plan["reduced_data"][0]["value"] == {
        "filter": "r",
        "magnitude": 20.10,
        "error": 0.08,
    }


def test_malformed_locus_fails_closed():
    payload = load_fixture()
    payload.pop("ra")
    with pytest.raises(SchemaError):
        normalize_antares_locus(payload)


def test_non_lsst_locus_fails_closed_instead_of_guessing():
    payload = load_fixture()
    payload["alerts"] = [
        {
            "id": "ztf_candidate:demo",
            "mjd": 61000.25,
            "properties": {"ant_survey_name": "ZTF", "ant_mag": 19.0},
        }
    ]
    with pytest.raises(SchemaError):
        normalize_antares_locus(payload)
