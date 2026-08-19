# Hostile maintainer review: ANTARES trigger-envelope / acknowledgement boundary

Date: 2026-08-19

## Verdict

**Do not activate the current TROVE ANTARES transport path for Rubin.**

The v3 evidence protocol is no longer the blocker. The blocker is now the high-level ANTARES/TOM transport surface: it does not provide the triggering alert or Kafka partition/offset to the TROVE handler, automatic offset commit can advance independently of durable evidence insertion, disabling automatic commit alone does not create an application-level acknowledgement contract in the current wrapper, and an uncaught handler exception can terminate an unsupervised listener thread.

This is a transport/integration problem, not a reason to redesign the v3 evidence models.

## Facts established from the exact runtime surface

Pinned validation environment:
- `antares-client==1.14.0`
- `tom-alertstreams==1.2.1`

### ANTARES client

The high-level `StreamingClient.iter()` path yields `(topic, locus)`.

The path does **not** expose Kafka `partition` or `offset` in the object returned to application code. The underlying consumer message has those coordinates, but they are discarded before the high-level return.

`ENABLE_AUTO_COMMIT` maps to Kafka `enable.auto.commit`; ANTARES documents automatic commits on an interval by default. The client exposes a `commit()` method, but the high-level iter/TOM path does not couple that commit to a successful TROVE durable transaction.

### TOM Toolkit wrapper

Current `AntaresAlertStream.listen()` is structurally:

```python
for topic, locus in self.stream.iter():
    base_topic = ...
    self.alert_handler[base_topic](locus)
```

Therefore:
- handler gets only `locus`, not the triggering `Alert`;
- handler gets no Kafka partition/offset;
- wrapper does not commit after a successful handler;
- wrapper has no per-message exception boundary.

`readstreams` starts each listener in a plain Python `Thread`. It does not supervise/restart a thread after an uncaught exception.

The executable probe in this directory asserts these source/runtime facts and simulates both the successful and poison-handler paths.

## Hostile failure cases

### 1. Trigger ambiguity

A streamed Locus is historical/site-level state. The current TROVE handler surface cannot prove which Rubin alert caused this delivery without inspecting/guessing from Locus history. That violates the evidence-boundary rule.

**Fail closed.** Require an explicit current Alert in the transport envelope.

### 2. Lost-after-auto-commit window

With automatic commits enabled, a Kafka position may be committed while TROVE is still processing, before its evidence transaction succeeds.

Failure shape:

```text
poll message N
  -> auto commit advances consumer position
  -> TROVE evidence transaction fails / process dies
  -> restart begins after N
  -> N is absent from durable evidence
```

The v3 DB idempotency cannot recover a message that is never replayed.

### 3. "Disable auto commit" is not enough

Turning off `ENABLE_AUTO_COMMIT` removes the known loss window, but the current TOM wrapper has no explicit `commit-after-durable-success` call and no message coordinate object to acknowledge.

That can yield indefinite replay/stalled progress rather than a correct delivery protocol.

### 4. Poison message kills listener

A handler exception escapes `AntaresAlertStream.listen()`. `readstreams` does not restart the dead thread.

One malformed/contradictory delivery can therefore silently stop the Rubin listener until an operator notices/restarts the process.

### 5. Naive "log and continue" is also unsafe

Even with manual commit, simply catching a poison message, logging it, and continuing can be incorrect. If a later offset on the same partition is committed, Kafka regards all earlier offsets as consumed. That can skip the failed message permanently.

A permanent poison path must either:
- durably quarantine the lossless trigger + transport coordinates, **then intentionally acknowledge it** to unblock the partition; or
- stop that partition and require operator/retry recovery before any later position is committed.

### 6. Consumer-group identity must be stable

A production contract must define a stable explicit consumer group. An ephemeral group across restarts/deployments undermines replay/ack semantics even if per-message logic is correct.

## Minimum safe contract

The next adapter/wrapper boundary must expose one object equivalent to:

```text
RubinDeliveryEnvelope:
  trigger_alert:
    explicit ANTARES Alert for this delivery

  locus_context:
    locus_id
    agreed routing tags/GW context only

  transport:
    transport_namespace
    topic
    partition
    offset
    broker delivery/message id if available
    stable consumer group
```

Processing rules:

```text
validate envelope
  -> durable v3 evidence/context/delivery transaction
  -> if success: acknowledge/commit this delivery

transient failure
  -> do not acknowledge
  -> retry/stop partition

permanent malformed/contradictory delivery
  -> durably quarantine lossless trigger + coordinates + error
  -> intentionally acknowledge only after quarantine is committed
```

Listener rules:
- exceptions observable;
- listener supervised/restarted;
- no HTTP history lookup to identify trigger;
- no commit that can move past an unhandled same-partition poison message.

## What we can implement ourselves vs what requires external agreement

### We can implement/test locally

- a TROVE-facing `RubinDeliveryEnvelope` contract;
- a thin transport adapter against a fake/controlled consumer message;
- success / transient failure / poison quarantine state machine;
- deterministic tests proving `durable first, ack second`;
- tests proving no ack on DB failure;
- tests proving same-partition later messages cannot commit past an unresolved failure;
- listener supervision behavior;
- stable namespace/group configuration requirements.

### We cannot honestly close from public interfaces alone

We still need the actual ANTARES/TROVE route contract to know how the triggering Alert and Kafka coordinates are made available in the production stream. The current public high-level TOM path is insufficient.

That means the correct next implementation target is **not** another storage patch. It is a narrow transport adapter/protocol harness that can be dropped onto the eventual ANTARES output/consumer surface once those fields are available.

## Activation gate

Do not turn on live Rubin ingestion until all are demonstrated:

1. Explicit current Alert is delivered; no Locus-history inference.
2. `transport_namespace + topic + partition + offset` reaches TROVE.
3. Stable consumer group is explicit.
4. Auto commit is not allowed to race durable insertion.
5. Durable success precedes acknowledgement.
6. Transient failure leaves the position unacknowledged.
7. Permanent poison data is durably quarantined before intentional acknowledgement, or the partition is stopped.
8. Listener failure is observable and supervised.
9. A staging crash/restart test proves replay/no-loss behavior.
10. A staging poison-message test proves progress without silent loss.

## Bottom line

**The current evidence protocol has passed its hostile gate. The current transport surface has not.**

The engineering problem is now sharply isolated: expose an explicit trigger + transport coordinates and couple Kafka progress to durable evidence/quarantine state. Until that exists, the correct behavior is to remain unwired.
