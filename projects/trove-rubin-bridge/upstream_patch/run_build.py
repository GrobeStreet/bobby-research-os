from __future__ import annotations

import subprocess

import build_trove_patch as builder

# Correct a local test-variable name in the template without changing the
# production patch logic. Keep this explicit so CI records the exact transformation.
builder.TEST_MODULE = builder.TEST_MODULE.replace(
    '    rubin_alerts = [\n        alert for alert in payload["locus"]["alerts"] if alert["alert_id"].startswith("lsst:")\n    ]',
    '    rubin_alert_records = [\n        alert for alert in payload["locus"]["alerts"] if alert["alert_id"].startswith("lsst:")\n    ]',
).replace(
    '    assert len(rubin_alerts) == 2',
    '    assert len(rubin_alert_records) == 2',
).replace(
    '    partial_payload["locus"]["alerts"] = non_rubin[:1] + rubin_alerts[:1]',
    '    partial_payload["locus"]["alerts"] = non_rubin[:1] + rubin_alert_records[:1]',
).replace(
    '    monkeypatch.setattr(rubin_alerts_module := rubin_alerts, "target_post_save", fake_target_post_save)',
    '    monkeypatch.setattr(rubin_alerts, "target_post_save", fake_target_post_save)',
)

builder.modify_trove()

# `git diff` omits untracked files. Mark the three new TROVE files as
# intent-to-add so the frozen patch is complete and directly applyable.
subprocess.run(
    [
        "git",
        "add",
        "-N",
        "custom_code/rubin_alerts.py",
        "tests/test_rubin_alertstream.py",
        "tests/data/antares_rubin_locus.json",
    ],
    cwd=builder.TROVE_ROOT,
    check=True,
)

builder.generate_patch()
print(builder.PATCH_PATH)
