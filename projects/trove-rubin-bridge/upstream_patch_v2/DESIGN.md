# TROVE Rubin evidence-ingress boundary — v2

## Design law

> **Ingress may move and preserve evidence. It may not silently reinterpret the evidence.**

The v1 candidate patch was rejected in internal maintainer review because it crossed the transport/science boundary: it converted ANTARES-normalized positive `ant_mag` values into TROVE `ReducedDatum` detections even when the underlying Rubin difference-image `psfFlux` was negative. It also tied new broker evidence to target lifecycle and candidate vetting before the scientific interpretation contract had been agreed.

v2 removes that entire class of behavior.

## What v2 does

The core patch:

1. adds a dedicated `RubinAlertEvidence` Django model in TROVE's existing `custom_code` app;
2. accepts an ANTARES `Locus` object and selects only Rubin/LSST alerts;
3. preserves each distinct Rubin alert payload as an evidence snapshot;
4. extracts a small set of routing/index fields **without changing their sign or scientific meaning**:
   - ANTARES locus ID
   - alert ID
   - Rubin DIA Object ID
   - Rubin DIA Source ID
   - Rubin Solar System Object ID
   - `midpointMjdTai` (stored as the original numeric TAI MJD)
   - band
   - signed `psfFlux`
   - `psfFluxErr`
   - reliability
   - quality/flag fields
   - alert-level gravitational-wave associations;
5. hashes the canonical raw alert payload with SHA-256;
6. makes exact broker redelivery idempotent while counting redeliveries;
7. preserves a second snapshot rather than overwriting evidence if the same source alert ID arrives with a materially different payload;
8. exposes a small handler function that performs database ingress only.

## What v2 deliberately does NOT do

Ingress does **not**:

- create a TROVE `Target`;
- resolve Rubin identity against ZTF/TNS/other target aliases;
- create `ReducedDatum` photometry;
- convert signed difference flux into magnitude;
- classify a point as a detection or upper limit;
- reject a point because a science-quality flag is set;
- associate or score an `EventCandidate`;
- call `target_post_save`;
- call `vet_basic`, `vet_bns`, `vet_kn_in_sn`, or `vet_super_kn`;
- choose how an existing EventCandidate should be re-vetted;
- claim exactly-once Kafka delivery semantics.

Those are downstream scientific/workflow decisions.

## Evidence authority

`raw_alert` is the authoritative preserved broker payload after deterministic JSON-safe serialization. The extracted database columns are convenience/index fields only. If an extracted field and `raw_alert` ever disagree, `raw_alert` wins.

Non-finite floating values and other non-JSON-native primitives are encoded explicitly rather than coerced into scientific values.

## Snapshot identity

A stored evidence snapshot is uniquely identified by:

`(broker, source_record_id, payload_sha256)`

where `source_record_id` is the ANTARES alert ID when present. If an LSST-like alert is missing an alert ID, a deterministic `UNIDENTIFIED:<sha256>` record ID is used so the evidence can still be preserved without inventing a survey identity.

Consequences:

- exact redelivery -> no new evidence row;
- same alert ID + changed payload -> a new evidence snapshot is preserved;
- old evidence is never silently overwritten.

## Transport split

The core evidence patch is intentionally separate from ANTARES credential/topic wiring.

`0001-rubin-evidence-core.patch` is the candidate review unit.

A future/optional transport patch can wire a confirmed ANTARES topic to the handler once TROVE decides:

- ANTARES vs another broker path;
- exact topic/tag/filter contract;
- Kafka offset/acknowledgement behavior;
- listener failure/dead-letter policy.

This avoids baking an unconfirmed production transport choice into the scientific evidence schema.

## Downstream contract

A later explicit interpretation service may consume `RubinAlertEvidence` and produce TROVE photometry/candidate updates. That service must:

1. name and version its interpretation rules;
2. retain links back to the source evidence snapshot(s);
3. define signed-flux, quality-flag, and upper-limit semantics explicitly;
4. define target identity resolution explicitly;
5. re-vet existing EventCandidates when new interpreted evidence actually changes their scientific state.

That layer is intentionally absent from v2 ingress.
