# Rubin trigger-envelope / acknowledgement contract v1

## Status

**Validated executable contract harness; not production ANTARES wiring.**

CI branch: `ci/trove-rubin-transport-contract-v1`

Validated source commit: `d68f609193be5980d4fcadb76cfde01b977bdfdd`

GitHub Actions run: `32223609447`

Result: **14 passed** plus static invariant scan green.

This artifact follows the runtime hostile review at `transport-boundary-status.json`, which established that the current `antares-client==1.14.0` + `tom-alertstreams==1.2.1` high-level surface does not expose the explicit triggering Alert or Kafka partition/offset to the TOM handler and does not provide commit-after-durable-success semantics.

## Proven executable invariants

The harness models the minimum transport semantics required before TROVE should enable Rubin ingestion.

1. **Kafka message identity is independent of consumer progress.**
   - message identity: `transport_namespace + topic + partition + offset`
   - progress identity: `transport_namespace + consumer_group + topic + partition`
   - two consumer groups seeing the same Kafka record share one evidence identity but commit independently.

2. **Transport coordinates are trusted only from the transport delivery object.**
   Payload fields cannot override namespace/topic/partition/offset or consumer group.

3. **The current alert must be explicit.**
   Missing or malformed `trigger_alert` is a permanent delivery error. The adapter must never infer the trigger from locus history.

4. **Durability precedes acknowledgement.**
   `acknowledge()` is reachable only after either:
   - durable evidence persistence; or
   - durable poison-message quarantine.

5. **A nondurable receipt cannot be acknowledged.**
   The state machine raises an invariant violation rather than allowing transport progress.

6. **Transient evidence failure does not acknowledge.**
   The consumer stops at the unresolved offset and cannot poll past it. Restart replays the same offset.

7. **Permanent poison must be durably quarantined before acknowledgement.**
   Quarantine preserves the raw delivery bytes, message coordinates, payload SHA-256, broker delivery ID when present, and error classification.

8. **Transient quarantine failure does not acknowledge.**
   A poison message cannot be skipped merely because the quarantine store is unavailable.

9. **Crash after evidence durability but before acknowledgement is safe.**
   On restart the Kafka record is replayed, durable evidence is recognized idempotently, then the offset is acknowledged.

10. **Crash after quarantine durability but before acknowledgement is safe.**
    On restart the poison delivery is replayed, the durable quarantine record is recognized idempotently, then the offset is acknowledged.

11. **Identity reuse with different trigger evidence fails closed.**
    A Kafka message position cannot silently point at contradictory trigger content.

## What this does NOT prove

- It is not a production wire format. `SyntheticEnvelopeCodec` is explicitly test-only.
- It does not prove the supported ANTARES API can currently supply the required trigger + Kafka coordinates.
- It does not alter or replace the validated v3 evidence protocol.
- It does not implement a production quarantine table.
- It does not implement a production listener supervisor.
- It does not prove live Kafka rebalance, partition revocation, network partition, or broker-failover behavior.
- It does not establish the intended ANTARES tag/topic/filter contract for TROVE.

## Required production seam

A supported adapter must provide, for each delivery:

```text
trigger:
  explicit current ANTARES Alert

context:
  intentional locus context only

message identity:
  stable transport namespace
  topic
  partition
  offset
  broker delivery id if available

consumer progress:
  stable consumer group

acknowledgement:
  only after durable evidence success
  OR after durable quarantine of a permanent poison message
```

Transient failure must leave the offset unresolved. The consumer must not process later records on that partition until the failed position is resolved or deliberately quarantined.

## Current decision

The evidence boundary should **not** be redesigned again. The next uncertainty is the supported integration surface: how ANTARES/TOM can expose an explicit trigger and Kafka coordinates while giving TROVE controlled acknowledgement semantics.

That should be resolved with the maintainers before production wiring is invented privately.
