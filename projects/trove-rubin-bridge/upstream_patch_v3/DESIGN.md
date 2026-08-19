# TROVE Rubin evidence ingress — v3

## Design laws

> **Ingress may move and preserve evidence. It may not silently reinterpret the evidence.**

> **Alert identity, delivery identity, and mutable broker context are three different things. Store them separately.**

v3 follows from the hostile review of v2. v2 correctly removed premature photometric/scoring interpretation, but it still hashed mutable ANTARES locus context into alert identity and walked `locus.alerts`, which could duplicate historical alert payloads and potentially lazy-load locus history over HTTP inside a streaming handler.

v3 separates the three concepts explicitly.

## Data model

### `RubinAlertEvidence`

One immutable/application-append-only snapshot of one Rubin alert payload.

Identity:

`(broker, source_record_id, alert_payload_sha256)`

The hash covers only the normalized broker alert snapshot under a versioned hash domain. It does **not** include locus tags, locus GW context, delivery time, topic, partition, offset, or any downstream scientific interpretation.

Stored convenience fields preserve, without reinterpreting:

- DIA Object ID
- DIA Source ID
- Solar System Object ID
- numeric `midpointMjdTai`
- band
- signed `psfFlux`
- `psfFluxErr`
- reliability
- DiaSource boolean quality flags
- per-alert GW associations

`broker_alert_snapshot` is authoritative for this model. It is a deterministic broker-level JSON snapshot, **not claimed to be the original Kafka bytes or original Rubin Avro packet**.

### `RubinBrokerContextEvidence`

One immutable/application-append-only snapshot of mutable ANTARES locus routing context.

Identity:

`(broker, locus_id, context_sha256)`

Current context includes only:

- locus ID
- canonicalized/sorted tags
- canonicalized/sorted locus-level GW associations

Mutable context is intentionally not part of `RubinAlertEvidence` identity.

### `RubinEvidenceDelivery`

One append-only observed delivery link between an alert snapshot and a broker-context snapshot.

It carries delivery/transport provenance separately:

- broker delivery ID
- received timestamp
- topic
- partition
- offset
- transport metadata

If an explicit broker delivery ID is unavailable, TROVE creates a local delivery occurrence ID. That local ID proves an ingestion occurrence, not Kafka exactly-once identity.

## API boundary

The v3 core API accepts:

`ingest_antares_rubin_delivery(alert, *, locus_context, delivery_metadata=None)`

It accepts one explicit current alert. It never accesses `locus.alerts`.

That is deliberate. Current ANTARES streaming returns a `Locus` containing observation history, and the client documents `Locus.alerts` as potentially lazy-loaded from the ANTARES HTTP API. A future transport adapter must define how the current triggering alert is supplied without history fetches before the core is wired into TROVE's listener.

## Immutability contract

Evidence/context/delivery rows are application-enforced append-only:

- instance updates via `.save()` are rejected after creation;
- instance `.delete()` is rejected;
- queryset `.update()` and `.delete()` are rejected;
- Django admin is view-only for these models;
- content hashes are verified against stored snapshots in tests.

This is not represented as database-superuser-proof immutability. A privileged SQL operator can still mutate rows. If TROVE needs stronger guarantees, production PostgreSQL permissions or triggers should be a separate operational decision.

## Versioned hashing

Hashes are domain-separated and versioned so a future change in canonicalization does not masquerade as the same evidence protocol.

Alert domain:

`trove-rubin-alert-evidence:v1`

Context domain:

`trove-rubin-broker-context:v1`

The model stores the canonicalization version alongside each snapshot.

## What ingress still does not do

v3 still creates no:

- `Target`
- `ReducedDatum`
- magnitude
- detection/upper-limit decision
- target alias resolution
- `EventCandidate`
- candidate score
- vetting call

Those remain downstream interpretation/workflow responsibilities.

## Production gate

Before live ANTARES wiring, v3 must survive:

1. exact patch apply/check against current TROVE main;
2. SQLite focused + full-suite regression tests;
3. PostgreSQL focused tests;
4. concurrent duplicate delivery on PostgreSQL;
5. concurrent changed alert versions on PostgreSQL;
6. proof that changing/reordering locus context does not duplicate alert content;
7. proof that the core never accesses `locus.alerts`;
8. hash-integrity and append-only tests;
9. measured payload/context storage sizes from the real Rubin fixture.

Live Kafka offset/ack/restart/quarantine semantics remain a separate transport gate.
