# TROVE Rubin / LSST Issue #23 — maintainer brief

I investigated TROVE issue #23 ("Begin listening to the Rubin/LSST Alert streams") as an independent research-engineering exercise. I did **not** open an upstream PR because the safe integration boundary depends on maintainer choices about the intended ANTARES route.

## What I found

The current high-level `tom-alertstreams` ANTARES path is not sufficient for a loss-aware Rubin integration:

- TROVE's handler receives a `Locus`, not an explicit triggering `Alert`.
- ANTARES Client 1.14.0's high-level return discards Kafka partition/offset even though the underlying `confluent_kafka.Message` has them.
- automatic Kafka commits are enabled by default;
- the TOM wrapper does not commit after durable handler success;
- handler exceptions escape the listener thread and `readstreams` does not supervise/restart it.

I also found a science-integrity trap in an earlier adapter attempt: real Rubin negative difference flux can coexist with broker `ant_mag` derived from `abs(psfFlux)`. Mapping that broker magnitude directly into TROVE would manufacture a positive "detection" from a negative difference-flux measurement. The current evidence core therefore preserves signed Rubin evidence and does not perform that interpretation at ingress.

## What is already built and stress-tested

### 1. Split evidence boundary

The current internal v3 protocol stores separately:
- immutable/application-append-only broker alert evidence;
- mutable broker-context snapshots;
- transport delivery occurrences.

It preserves signed Rubin `psfFlux`, source IDs, flags and provenance without creating Target/ReducedDatum/detection/scoring side effects.

Validation against TROVE main included migration consistency, focused SQLite, the full TROVE suite, PostgreSQL and concurrency races, then independent re-application of the exact frozen patch.

Frozen patch SHA-256:
`7a12f85c2ffa1001a97042f6a30ef203ea1179a9fe5247abd216a49310ca5eb0`

### 2. Executable acknowledgement contract

A deterministic transport harness proves the invariant:

> durable evidence **or** durable quarantine must exist before acknowledgement.

It exercises success, transient failure, permanent poison, crash-after-durability/before-ack, restart/replay, nondurable receipts and consumer-group progress semantics.

### 3. Minimal supported-seam prototype

Against exact `antares-client==1.14.0` and `tom-alertstreams==1.2.1`, a focused prototype shows the acknowledgement side can stay very small:

- ANTARES Client `_timed_poll()` already has the raw Kafka message;
- expose `topic + partition + offset + locus` rather than discarding partition/offset;
- configure auto-commit off;
- process exactly one delivery at a time;
- call the existing public `StreamingClient.commit()` only after durable evidence/quarantine.

For trigger identity, the safe rule is an explicit filter-stamped current-alert ID. TROVE must not infer the triggering alert from `locus.alerts` ordering or lazy-load history over HTTP.

The supported-seam prototype passed 10 focused tests in CI run `32224251347`.

## The narrow question for maintainers

Before I take this any further, I want to make sure I am solving the route you actually intend.

1. Is ANTARES the broker path TROVE wants for Rubin Issue #23?
2. If yes, would you prefer the trigger/offset seam to live as:
   - a tiny ANTARES client API extension exposing partition/offset plus the current parsed Locus,
   - a `tom-alertstreams` wrapper extension,
   - or an ANTARES-side output envelope/filter contract?
3. Does the TROVE-directed ANTARES output include the current Alert in the serialized Locus, or should the filter carry a compact/lossless trigger snapshot explicitly?

If this matches the direction you want, I can turn the existing internal work into a deliberately small upstream patch aligned to your preferred architecture rather than sending a speculative large PR.

## Artifacts

Project staging branch:
`GrobeStreet/bobby-research-os` → `project/trove-rubin-bridge`

Key paths:
- `projects/trove-rubin-bridge/upstream_patch_v3/`
- `projects/trove-rubin-bridge/transport_boundary_review/`
- `projects/trove-rubin-bridge/supported_seam/SUPPORTED_SEAM_REVIEW.md`

This work is internal/staging only so far; no claim of production readiness or completed Rubin ingestion is being made.
