import json
from pathlib import Path

from trove_rubin_bridge import InMemoryIngestLedger, build_trove_handoff, normalize_antares_locus

fixture = Path(__file__).parents[1] / "fixtures" / "antares_lsst_locus.synthetic.json"
locus = json.loads(fixture.read_text())
target = normalize_antares_locus(locus)
ledger = InMemoryIngestLedger()

print("first delivery:", ledger.ingest(target))
print("repeat delivery:", ledger.ingest(target))
print(json.dumps(build_trove_handoff(target), indent=2))
