from __future__ import annotations

import subprocess
from pathlib import Path

# Packaging-only repair of the first v3 protocol builder attempt. Read the exact
# failed source as data, change only nested multiline-string delimiters, then execute
# the repaired source. The protocol logic remains byte-for-byte otherwise unchanged.
FAILED_BUILDER_COMMIT = "0b1521be5475906d2700c0d63a49a64522841183"
RELATIVE_PATH = "projects/trove-rubin-bridge/upstream_patch_v3/run_hardened_v3_protocol_v3.py"
repo_root = Path(__file__).resolve().parents[3]
source = subprocess.run(
    ["git", "show", f"{FAILED_BUILDER_COMMIT}:{RELATIVE_PATH}"],
    cwd=repo_root,
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout

# The outer protocol injection intentionally remains raw triple-single-quoted.
# Nested generated fragments therefore use triple-double delimiters. Remove the one
# generated triple-double docstring first so it cannot terminate canonical_v3.
doc = '''    \"\"\"Encode supported broker values into a structurally unambiguous JSON tree.\n\n    Every Python value is wrapped in a type tag, so broker dictionaries can never\n    collide with encoded bytes/non-finite floats or another supported Python type.\n    Float identity uses the exact IEEE-754 binary64 bit pattern, including signed\n    zero and NaN payload bits. Mapping keys must be strings.\n    \"\"\"\n'''
replacement = '''    # Encode supported broker values into a structurally unambiguous JSON tree.\n    # Every Python value is wrapped in a type tag. Float identity uses the exact\n    # IEEE-754 binary64 bit pattern, including signed zero and NaN payload bits.\n'''
if source.count(doc) != 1:
    raise RuntimeError("Expected exactly one generated typed-normal-form docstring")
source = source.replace(doc, replacement, 1)

pairs = [
    ("canonical_v3 = r'''", 'canonical_v3 = r"""'),
    ('    return "" if value is None else str(value)\n\'\'\'\nbase.INGRESS_MODULE =', '    return "" if value is None else str(value)\n"""\nbase.INGRESS_MODULE ='),
    ("transport_v3 = r'''", 'transport_v3 = r"""'),
    ('                raise ValueError("delivery identity/provenance was previously used with different values")\n\'\'\'\nbase.INGRESS_MODULE =', '                raise ValueError("delivery identity/provenance was previously used with different values")\n"""\nbase.INGRESS_MODULE ='),
    ("strict_test_old = r'''", 'strict_test_old = r"""'),
    ('    assert CONTEXT_HASH_DOMAIN.endswith(":v2")\n\'\'\'\nstrict_test_new =', '    assert CONTEXT_HASH_DOMAIN.endswith(":v2")\n"""\nstrict_test_new ='),
    ("strict_test_new = r'''", 'strict_test_new = r"""'),
    ('    assert TYPED_NORMAL_FORM == "trove-typed-normal-form:v1"\n\'\'\'\nbase.TEST_MODULE =', '    assert TYPED_NORMAL_FORM == "trove-typed-normal-form:v1"\n"""\nbase.TEST_MODULE ='),
]
for old, new in pairs:
    if source.count(old) != 1:
        raise RuntimeError(f"Expected exactly one delimiter fragment: {old[:80]!r}")
    source = source.replace(old, new, 1)

compile(source, RELATIVE_PATH, "exec")
exec(compile(source, RELATIVE_PATH, "exec"), {"__name__": "__main__", "__file__": str(Path(__file__))})
