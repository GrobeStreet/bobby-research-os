from __future__ import annotations

# The first v3 protocol source is frozen at commit
# 0b1521be5475906d2700c0d63a49a64522841183 as a preserved failed attempt.
# This entrypoint delegates to a packaging-only repair that reads that exact source,
# fixes nested multiline-string delimiters, compile-checks it, and executes it.
from pathlib import Path

fixed = Path(__file__).with_name("run_hardened_v3_protocol_v3_fixed.py")
source = fixed.read_text()
exec(compile(source, str(fixed), "exec"), {"__name__": "__main__", "__file__": str(fixed)})
