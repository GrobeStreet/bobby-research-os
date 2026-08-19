# Supported ANTARES trigger/ack seam review

Status: **prototype passed; production integration still requires maintainer/ANTARES agreement**

Validated against:
- `antares-client==1.14.0`
- `tom-alertstreams==1.2.1`
- CI run `32224251347`
- prototype branch commit `db7eadeeacc5fde4ec7a3d66d2f00ce67aeb337b`

## Smallest supported seam

Do not redesign TROVE evidence storage. Do not ship a private Kafka consumer inside TROVE.

The minimum safe path is:

1. **ANTARES filter/output contract**
   - execute on the incoming alert;
   - stamp an explicit current-alert identifier on the outgoing Locus, e.g. `trove_rubin_trigger_alert_id`;
   - route the tag to a TROVE-directed Kafka topic with ANTARES coordination;
   - do not ask TROVE to infer the trigger from historical alert order.

2. **Small ANTARES client API addition**
   - preserve the existing parsed `Locus`;
   - expose the `partition` and `offset` of the `confluent_kafka.Message` already present inside `StreamingClient._timed_poll()`;
   - a possible public API shape is `poll_delivery() -> {topic, partition, offset, locus}`.

3. **Small TOM wrapper addition**
   - configure `enable_auto_commit=False`;
   - use a stable explicit consumer group;
   - poll one delivery;
   - call the TROVE evidence/quarantine transaction;
   - call the existing public `StreamingClient.commit()` only after durability is proven;
   - do not poll another message on that consumer before the current delivery is resolved.

## Why this is small

In ANTARES Client 1.14.0, `_timed_poll()` already receives the raw Kafka message and calls:

```python
message = self._consumer.poll(...)
locus = _parse_message(message)
return message.topic(), locus
```

The required partition and offset already exist on that same message. They are discarded only by the current return shape. The client also already exposes a public `commit()` method and an `enable_auto_commit` constructor option.

Therefore the acknowledgement half does not require a new broker stack. It requires preserving metadata already present in the supported client implementation.

## Trigger rule

The filter-side trigger marker is necessary because the downstream `StreamingClient` returns a Locus representing alert-site history, not the incoming Alert as a distinct return value.

Downstream resolution must:
- read an explicit trigger id from streamed Locus properties;
- inspect only alerts embedded in that broker delivery;
- never access `locus.alerts` when `_alerts` is absent, because that property lazy-loads historical alerts over HTTP;
- fail closed if the explicit trigger is missing, absent from the embedded alerts, or ambiguous.

Whether the production ANTARES output always embeds the current Alert in the streamed Locus must be confirmed with ANTARES/TROVE before activation. If it does not, the filter/output contract must carry a sufficient lossless trigger snapshot rather than causing TROVE to fetch or infer history.

## Prototype validation

Focused prototype tests passed:
- raw Kafka topic/partition/offset are preserved;
- explicit trigger selects exactly one embedded alert;
- missing trigger fails closed;
- explicit trigger with no embedded alerts fails closed without HTTP history loading;
- absent/duplicate trigger matches fail closed;
- durable evidence occurs before commit;
- transient evidence failure does not commit;
- nondurable evidence receipt does not commit;
- permanent trigger-contract failure commits only after durable quarantine;
- nondurable quarantine does not commit.

CI run `32224251347`: **10 passed** plus fail-closed static safety assertions.

## Remaining external questions

Before production wiring:
1. Is ANTARES the broker route TROVE intends for Rubin Issue #23?
2. Can a TROVE-specific filter/tag be enabled on an ANTARES Kafka output?
3. Will that output include the current Alert in the serialized Locus when the filter stamps its alert id?
4. Would ANTARES maintainers accept a tiny public delivery-return API exposing partition/offset, or should that seam live elsewhere?
5. Does TROVE prefer the corresponding one-message-at-a-time/manual-commit behavior in `tom-alertstreams`, or another supervised consumer architecture?

No production claim is made until these are answered.
