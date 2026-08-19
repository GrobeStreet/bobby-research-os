# ANTARES -> TROVE Rubin trigger transport contract

## Status

**Design contract only. Not production wiring.**

The v3 evidence core intentionally accepts one explicit current Rubin alert plus separate broker context and delivery metadata. It must not be wired directly to the current TOM Toolkit `AntaresAlertStream` until the trigger-envelope and offset/failure semantics below are satisfied.

## Why a contract is required

ANTARES Client 1.14 streaming returns `(topic, locus)`. The streamed `Locus` represents the history of observations at the alert site. `Locus.alerts` may be absent from the streamed object and is documented to lazy-load from the ANTARES HTTP API on first access.

Therefore TROVE must **not** identify the triggering alert by:

- reading `locus.alerts[-1]`;
- sorting locus history by timestamp;
- selecting the highest alert ID;
- loading historical alerts over HTTP inside the stream handler.

All of those approaches turn historical state into guessed delivery identity.

ANTARES filters, by contrast, execute on each incoming alert and have access to the incoming alert as well as the locus and its history. Current DevKit filter examples use the current alert in filter execution, and filters may set Locus/Alert properties and tags. Tags can be routed to Kafka output streams with ANTARES coordination.

## Required output envelope

A TROVE-directed ANTARES output must make the **triggering alert** explicit without requiring TROVE to inspect history.

Conceptually the output contract needs:

```text
trigger_alert:
    broker_alert_id
    broker_alert_snapshot OR a lossless/documented way to retrieve it

locus_context:
    locus_id
    tags / routing context as intentionally defined
    locus-level GW context as intentionally defined

transport:
    topic
    partition
    offset
    broker delivery/message identifier if available
```

The exact mechanism by which ANTARES exposes the trigger alert downstream remains an integration decision. A filter property may be appropriate for a compact trigger marker, but the current public documentation does not establish a safe size/type contract for embedding a complete alert payload as a Locus property. Do not invent that production contract without ANTARES/TROVE agreement.

## Core boundary

Once an explicit trigger is available, TROVE calls:

```python
ingest_antares_rubin_delivery(
    alert,
    locus_context=context,
    delivery_metadata=transport,
)
```

The evidence core must not call `locus.alerts`.

## Delivery identity

Delivery identity and alert identity remain separate.

Preferred durable transport identity when Kafka coordinates are available:

```text
broker + topic + partition + offset
```

An explicit broker delivery ID may also be preserved, but reusing a delivery ID with different alert/context/transport provenance is an integrity error.

No local UUID is evidence of Kafka exactly-once delivery. It is only a TROVE-local ingestion-occurrence identifier.

## Commit / acknowledgement gate

ANTARES documents periodic automatic Kafka offset commits by default. The current TOM Toolkit ANTARES wrapper invokes the configured handler synchronously for each streamed Locus.

Before production activation, TROVE must make an explicit choice between:

1. **automatic commit with accepted replay/loss semantics**, documented and tested; or
2. **manual/controlled commit** only after the durable evidence transaction succeeds, if supported by the selected client/wrapper contract.

The v3 core does not claim this decision has been made.

## Failure / poison-message policy

A malformed or contradictory trigger must never be silently converted into valid evidence.

Minimum production requirements:

- validate trigger alert ID/schema before durable insert;
- reject contradictory delivery provenance;
- make handler exceptions observable;
- define whether failed messages are retried, quarantined, or dead-lettered;
- ensure one poison message cannot permanently kill an unsupervised listener;
- preserve enough transport coordinates to replay/audit a failed delivery.

Logging an exception and continuing is **not** sufficient if the offset may already have been committed.

## Activation gate

Do not enable live TROVE ANTARES settings until all are true:

1. TROVE confirms ANTARES is the desired Rubin broker route.
2. ANTARES/TROVE agree on the filtered output tag/topic.
3. The output contains or losslessly identifies the triggering alert without history inference.
4. Topic/partition/offset or equivalent durable delivery provenance reaches the evidence core.
5. Offset commit/ack behavior is explicit and tested.
6. Listener exception/restart/quarantine behavior is explicit and tested.
7. A live staging replay demonstrates durable evidence before acknowledgement.

Until then, the core handler remains deliberately unwired.
