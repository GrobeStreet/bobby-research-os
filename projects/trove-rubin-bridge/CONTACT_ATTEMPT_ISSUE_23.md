# TROVE Issue #23 first-contact attempt

Date: 2026-08-23

Target: `astro-trove/trove#23` — "Begin listening to the Rubin/LSST Alert streams"

Outcome: **not posted**.

The connected GitHub integration returned HTTP 403: `Resource not accessible by integration` when attempting to create an issue comment on the external `astro-trove/trove` repository.

No external contact was made. The failure is preserved here so the project record does not imply otherwise.

## Exact intended comment

I took a close look at this issue and built a small Rubin/ANTARES prototype against the current TROVE code plus `antares-client==1.14.0` / `tom-alertstreams==1.2.1`.

Two things stood out:

1. On the science side, the ingest layer should preserve Rubin difference-flux evidence without immediately translating broker magnitudes into TROVE detections. In a real ANTARES Rubin fixture, negative `lsst_diaSource_psfFlux` values coexisted with an `ant_mag` corresponding to `abs(psfFlux)`, so a naive magnitude mapping could manufacture a positive detection.

2. On the transport side, the current ANTARES client already has the raw Kafka message inside `_timed_poll()`, but returns only `(topic, locus)` and drops `partition`/`offset`; the TOM wrapper then passes only the Locus to the handler. The smallest safe path I found is: make the triggering alert explicit in the ANTARES output, expose the already-polled Kafka coordinates, disable auto-commit, process one delivery at a time, and commit only after durable evidence persistence (or durable quarantine of a permanent poison message).

I built and stress-tested the downstream evidence boundary and the durability-before-ack state machine, but I deliberately have not opened an upstream code PR because the remaining question is architectural:

**Is ANTARES the broker route you intend for #23, and if so, would you prefer the explicit-trigger / delivery-coordinate seam to live in `antares-client`, `tom-alertstreams`, or somewhere else?**

Happy to adapt the prototype to the maintainers’ preferred boundary rather than guessing.
