# Maintainer-review response — Rubin evidence ingress v2

This document maps the internal maintainer-style review of the v1 candidate patch to the v2 evidence-only design.

## Blockers removed by design

### 1. Negative Rubin difference flux was silently turned into a positive detection

**v2:** removed the interpretation path entirely.

Ingress copies signed `lsst_diaSource_psfFlux` and `lsst_diaSource_psfFluxErr` as convenience/index fields and preserves the full raw alert payload. It creates no `ReducedDatum`, magnitude, detection, upper limit, Target, or score.

A real ANTARES/Rubin fixture with negative `psfFlux` is a required regression test.

### 2. New evidence did not correctly re-vet an existing EventCandidate

**v2:** candidate vetting is outside ingress.

The evidence handler never calls `target_post_save`, `vet_basic`, `vet_bns`, `vet_kn_in_sn`, or `vet_super_kn`. A downstream interpretation/workflow service must explicitly define how new interpreted evidence refreshes existing EventCandidates.

### 3. Slow science work inside the Kafka handler created an offset/failure hazard

**v2 core:** all external science/network work is removed from ingress.

The core candidate patch still does **not** claim a solved Kafka acknowledgement policy. It is deliberately not wired to production ANTARES settings until TROVE confirms topic/filter/offset/failure semantics.

### 4. ANTARES was chosen without a public TROVE architecture decision

**v2 core:** transport configuration is separated from the evidence model/handler.

No credentials, topic, consumer group, or stream activation are added by the core patch. A later transport patch can wire the one-argument evidence handler after the broker contract is confirmed.

## High-priority findings addressed

### Target identity resolution

No Target is created at ingress. DIA Object/DIA Source IDs are preserved as evidence fields. Cross-survey identity resolution is deferred to an explicit downstream service.

### ReducedDatum provenance collision

No ReducedDatum is created at ingress. Evidence snapshots have their own database identity and raw payload hash.

### Cross-survey locus history

Only alert objects recognizably carrying Rubin/LSST alert evidence are stored as Rubin evidence. A real mixed ZTF+Rubin locus is a regression fixture.

### Changed broker evidence

Snapshot identity is `(broker, source_record_id, payload_sha256)`. Exact redelivery is idempotent; a materially changed payload for the same source record creates a second preserved snapshot rather than overwriting the first.

The hardened builder also includes minimal broker routing context (locus ID, tags, locus-level GW associations) in snapshot hashing so context changes are not silently discarded.

### Quality flags

Rubin DiaSource boolean fields are preserved as convenience fields and remain in the authoritative raw payload. Ingress does not decide whether any flag makes the measurement scientifically usable.

### Time scale

`midpointMjdTai` is stored as the original numeric TAI MJD. Ingress no longer converts it to a scientific observation datetime. Any TAI→UTC transformation belongs to the downstream interpretation layer and must be explicit/versioned.

## Still intentionally unresolved

These are not hidden limitations; they are the next contract decisions:

1. ANTARES vs another Rubin broker path.
2. Exact ANTARES topic/tag/filter definition.
3. Kafka auto-commit/manual-commit policy and replay semantics.
4. Listener exception/dead-letter/restart policy.
5. Target identity resolution across Rubin/ZTF/TNS aliases and coordinates.
6. Signed Rubin difference-flux → TROVE photometry semantics.
7. Quality/reliability criteria for scientific use.
8. How new interpreted evidence refreshes existing EventCandidates.
9. Production PostgreSQL/load validation.

The v2 core patch is intentionally useful without pretending those decisions have already been made.
