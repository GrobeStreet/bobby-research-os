import json
from pathlib import Path

from trove_rubin_bridge.adapter import normalize_antares_locus

REAL_DIR = Path(__file__).parents[1] / "fixtures" / "real"


def real_fixture_paths():
    manifest = json.loads((REAL_DIR / "manifest.json").read_text())
    return [REAL_DIR / item["file"] for item in manifest["fixtures"]]


def load_locus(path):
    return json.loads(path.read_text())["locus"]


def test_all_frozen_live_antares_lsst_fixtures_normalize():
    paths = real_fixture_paths()
    assert len(paths) == 5

    for path in paths:
        target = normalize_antares_locus(load_locus(path))
        assert target.broker == "ANTARES"
        assert target.lsst_dia_object_id is not None
        assert target.trove_target_name == f"LSST{target.lsst_dia_object_id}"
        assert target.observations
        assert all(obs.alert_id and obs.alert_id.startswith("lsst:") for obs in target.observations)
        assert all(
            any(str(key).startswith("lsst_") for key in obs.raw_properties)
            for obs in target.observations
        )


def test_cross_survey_locus_ingests_only_rubin_alerts():
    path = next(p for p in real_fixture_paths() if "170666303722881099" in p.name)
    locus = load_locus(path)
    raw_ids = [str(alert.get("alert_id", "")) for alert in locus["alerts"]]
    assert any(alert_id.startswith("ztf_") for alert_id in raw_ids)

    target = normalize_antares_locus(locus)
    normalized_ids = [obs.alert_id for obs in target.observations]
    assert normalized_ids
    assert all(alert_id.startswith("lsst:") for alert_id in normalized_ids)
    assert len(normalized_ids) < len(raw_ids)


def test_live_schema_nested_lsst_identity_is_unwrapped_to_scalar():
    path = next(p for p in real_fixture_paths() if "170666303786319881" in p.name)
    locus = load_locus(path)
    assert locus["properties"]["survey"]["lsst"]["dia_object_id"] == ["170666303786319881"]

    target = normalize_antares_locus(locus)
    assert target.lsst_dia_object_id == "170666303786319881"
    assert target.observations[0].raw_properties["lsst_diaSource_diaObjectId"] == 170666303786319881


def test_gw_provenance_is_preserved_for_rubin_alerts_without_cross_survey_leakage():
    saw_cross_survey_gw = False

    for path in real_fixture_paths():
        locus = load_locus(path)
        raw_rubin = [
            alert for alert in locus["alerts"]
            if str(alert.get("alert_id", "")).startswith("lsst:")
        ]
        raw_non_rubin = [
            alert for alert in locus["alerts"]
            if not str(alert.get("alert_id", "")).startswith("lsst:")
        ]
        if any(alert.get("grav_wave_events") for alert in raw_non_rubin):
            saw_cross_survey_gw = True

        target = normalize_antares_locus(locus)
        assert len(target.observations) == len(raw_rubin)

        expected_ids = []
        for alert in raw_rubin:
            for event in alert.get("grav_wave_events") or []:
                if event.get("gracedb_id") is not None:
                    expected_ids.append(str(event["gracedb_id"]))

        observed_ids = []
        for obs in target.observations:
            for event in obs.grav_wave_events:
                assert set(event) == {"gracedb_id", "contour_level", "contour_area"}
                if event["gracedb_id"] is not None:
                    observed_ids.append(str(event["gracedb_id"]))

        assert observed_ids == expected_ids
        assert set(target.grav_wave_events) == set(expected_ids)

    assert saw_cross_survey_gw, "Expected real ANTARES loci to exercise cross-survey GW leakage protection"
