from __future__ import annotations

import subprocess
from pathlib import Path

# Preserve the reviewed hardening implementation from its frozen commit and apply
# one deterministic packaging correction: Django serializes the conditional Q in
# model-definition order. The previous hand-written migration used the same logical
# predicate in a different tuple order, so `makemigrations --check` proposed a
# remove/recreate of an otherwise equivalent constraint.
REVIEWED_COMMIT = "d5cf21aec1f8b8105c9d34920b509410cca4deb6"
RELATIVE_PATH = "projects/trove-rubin-bridge/upstream_patch_v3/run_hardened_v3.py"
repo_root = Path(__file__).resolve().parents[3]
source = subprocess.run(
    ["git", "show", f"{REVIEWED_COMMIT}:{RELATIVE_PATH}"],
    cwd=repo_root,
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout
old = 'condition=models.Q(("offset__isnull", False), ("partition__isnull", False), ("topic__gt", "")),'
new = 'condition=models.Q(("topic__gt", ""), ("partition__isnull", False), ("offset__isnull", False)),'
if source.count(old) != 1:
    raise RuntimeError("Expected exactly one migration condition in reviewed hardening source")
source = source.replace(old, new, 1)
exec(compile(source, RELATIVE_PATH, "exec"), {"__name__": "__main__", "__file__": str(Path(__file__))})
