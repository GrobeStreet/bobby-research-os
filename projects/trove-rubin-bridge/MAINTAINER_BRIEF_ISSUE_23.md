# TROVE Issue #23 — Rubin/LSST alert-stream maintainer brief

## Purpose

This is a narrow design note for `astro-trove/trove#23` ("Begin listening to the Rubin/LSST Alert streams"). It is not an upstream PR and does not assume ANTARES is TROVE's preferred production route.

## What I found

I prototyped the Rubin ingress path against TROVE plus `antares-client==1.14.0` / `tom-alertstreams==1.2.1` and found two separable problems:

1. **Evidence/science boundary** — broker evidence must be stored without silently converting Rubin difference-flux measurements into ordinary detections.
2. **Transport boundary** — the current ANTARES/TOM high-level stream returns `(topic, locus)` and discards Kafka partition/offset metadata before the handler; the TOM wrapper also does not provide durable-success -> commit semantics.

The first problem now has a validated internal prototype. The second has a small tested contract but still needs a supported integration decision from TROVE/ANTARES maintainers.

## Science-integrity issue discovered during testing

A real ANTARES Rubin fixture contained negative `lsst_diaSource_psfFlux` values while `ant_mag` numerically matched the magnitude of `abs(psfFlux)`. Mapping that broker magnitude directly into TROVE `ReducedDatum["magnitude"]` would manufacture a positive detection from a negative difference-flux measurement.

The current prototype therefore treats ingress as evidence preservation only. It does not create magnitude detections, Targets, EventCandidates, or scores.

## Evidence boundary prototype

The current internal prototype separates:

- immutable alert evidence;
- mutable broker-context snapshots;
- delivery identity/provenance.

The evidence canonicalization is versioned and structurally typed. Kafka delivery identity is `transport_namespace + topic + partition + offset`; consumer-group state is separate.

Validation against clean TROVE main `9f2309890b248d78fc470632c7ee5d9c8c4739b6` included migration consistency, focused SQLite, full TROVE, PostgreSQL concurrency tests, and independent application of the exact frozen patch.

## Smallest transport seam I found

The exact `antares-client==1.14.0` runtime shows that `StreamingClient._timed_poll()` already has the raw `confluent_kafka.Message` and therefore the topic/partition/offset. It currently parses the message into a `Locus` and returns only `(topic, locus)`.

The smallest safe transport contract appears to be:

1. ANTARES filtering/output makes the **current alert ID explicit** in the outgoing Locus (rather than TROVE inferring it from Locus history).
2. The ANTARES client/TOM wrapper exposes the already-polled Kafka `partition` and `offset` alongside the Locus.
3. TROVE runs the consumer with auto-commit disabled and a stable consumer group.
4. One delivery is processed at a time.
5. TROVE commits only after either:
   - durable evidence persistence; or
   - durable quarantine of a permanent poison message.
6. Transient failures do not commit and do not poll past the unresolved delivery.

I built an executable harness for these semantics. It passes crash-after-durable-before-commit replay, transient DB failure, poison-message quarantine, nondurable-store rejection, contradictory transport identity, and independent consumer-group progress cases.

## What is still unresolved

The remaining question is intentionally small and architectural:

**Is ANTARES the broker route TROVE intends for Issue #23, and if so, where would maintainers prefer the explicit-trigger + delivery-coordinate seam to live?**

Possible homes appear to be:

- a small `antares-client` API extension returning delivery metadata;
- a `tom-alertstreams` ANTARES wrapper extension built on that API;
- an ANTARES output/filter contract that provides an explicit trigger marker;
- or a different broker path if ANTARES is not the intended route.

I have deliberately not opened an upstream code PR until that preference is clear.

## Internal evidence artifacts

The work is staged in `GrobeStreet/bobby-research-os`, branch `project/trove-rubin-bridge`, including:

- frozen v3 evidence patch and validation status;
- real ANTARES Rubin fixtures;
- hostile transport-boundary review;
- executable durability-before-ack contract;
- supported-seam runtime inspection and prototype review.

The goal of first contact is to verify the intended route and patch boundary before doing more implementation.
