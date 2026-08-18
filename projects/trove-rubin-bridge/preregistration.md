# Pre-specified acceptance and kill conditions

**Frozen before access to a real TROVE/ANTARES Rubin fixture.**

This is an engineering preregistration, not a scientific preregistration.

## Hypothesis

A thin broker adapter can reuse TROVE's existing target/post-save/vetting workflow without requiring a parallel Rubin-specific science pipeline.

## Acceptance tests

A real fixture implementation advances only if all of these are true:

1. **Repeat delivery** — second delivery creates zero new target identities and zero new photometry records.
2. **Incremental update** — ingest A,B and then A,B,C; exactly one new photometry record is created.
3. **Provenance** — ANTARES locus ID, survey alert ID, timestamps, band, GW IDs, and LSST DIA Object ID when available survive the handoff.
4. **No look-ahead** — a historical cutoff never includes a later alert.
5. **Fail closed** — missing identity/coordinates, missing alert time, or no recognizable LSST/Rubin alert raises an error.
6. **Science neutrality** — the bridge does not calculate a kilonova score or replace TROVE vetting.

## Kill conditions

Stop and redesign rather than patch around the problem if:

- TROVE maintainers say ANTARES is not their intended Rubin path;
- the real topic delivers a materially different object contract than ANTARES `Locus`;
- unique identity cannot be made stable under broker redelivery;
- source alert identity cannot be retained well enough to prevent duplicate photometry;
- the intended workflow requires duplicating TROVE's GW localization/scoring logic in the bridge;
- a maintainer identifies an already-active implementation that makes this work duplicative.

## Post-hoc boundary

Any new success metric added after receiving a real fixture is labeled post-hoc until a new version of this document is frozen.
