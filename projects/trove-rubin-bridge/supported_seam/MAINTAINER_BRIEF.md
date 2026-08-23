# TROVE Rubin/LSST Issue #23 — maintainer brief

## One-sentence summary

I investigated Issue #23 as an external contributor and found that a safe ANTARES path appears to require two separable pieces: an explicit current-alert trigger envelope and manual Kafka acknowledgement only after durable TROVE evidence/quarantine.

## Why I looked at this

TROVE Issue #23 asks to begin listening to Rubin/LSST alert streams. I treated the current TROVE main branch and the current ANTARES/TOM transport stack as the source of truth and built a minimal prototype rather than wiring alerts directly into scoring.

## The science-integrity problem I found first

A real ANTARES Rubin fixture contained negative Rubin difference-image `psfFlux` values while ANTARES `ant_mag` was numerically the magnitude of the absolute flux. Mapping `ant_mag` directly into TROVE `ReducedDatum["magnitude"]` would therefore manufacture a positive detection from negative difference flux.

The current prototype deliberately does **not** create TROVE photometry, targets, EventCandidates, scores, or vetting results. It preserves evidence first.

## Evidence boundary

The validated v3 evidence protocol stores three different things separately:

1. immutable broker alert evidence;
2. mutable broker/locus context snapshots;
3. delivery identity/provenance.

It uses a structurally tagged canonical normal form, namespaced Kafka identity, explicit zero-valued Rubin IDs, application-level append-only semantics, and deterministic replay behavior.

The exact frozen v3 evidence patch was validated against TROVE main `9f2309890b248d78fc470632c7ee5d9c8c4739b6` with:

- migration consistency;
- focused SQLite;
- full TROVE tests;
- PostgreSQL focused tests including concurrency races;
- independent fresh-checkout verification of the exact frozen patch file.

Frozen patch SHA-256:
`7a12f85c2ffa1001a97042f6a30ef203ea1179a9fe5247abd216a49310ca5eb0`

## Current transport limitation

Against exact `antares-client==1.14.0` / `tom-alertstreams==1.2.1`:

- `StreamingClient` returns `(topic, locus)`;
- the raw Kafka message inside `_timed_poll()` already has topic/partition/offset, but partition/offset are discarded by the public return shape;
- `StreamingClient` already exposes `enable_auto_commit=False` and a public `commit()` method;
- the current TOM ANTARES wrapper passes only `locus` to the handler and has no commit-after-durable-success path;
- `Locus.alerts` may lazy-load history over HTTP when `_alerts` is absent;
- handler exceptions escape the listener and the current `readstreams` command does not supervise/restart the listener thread.

## Smallest prototype seam

The narrow prototype that survived hostile review is:

### ANTARES filter/output side

The filter executing on the incoming alert stamps an explicit current-alert identifier on the outgoing Locus, e.g.:

`trove_rubin_trigger_alert_id = <current alert.alert_id>`

That routed output must be a TROVE-directed ANTARES topic/tag. TROVE never infers the trigger from locus-history ordering.

### ANTARES client side

Add one small public delivery-return API that preserves information the client already has:

`topic + partition + offset + parsed locus`

The prototype equivalent is a `poll_delivery()` shape. No new broker stack is required.

### TROVE/TOM side

- stable explicit consumer group;
- `enable_auto_commit=False`;
- one unresolved delivery at a time;
- resolve the explicit trigger only from alerts already embedded in that broker delivery;
- never lazy-load `locus.alerts` to guess the trigger;
- durable evidence -> commit;
- permanent invalid delivery -> durable quarantine -> commit;
- transient failure -> no commit, stop/retry.

## Prototype results

The acknowledgement contract passed 14 hostile tests, including:

- crash after durable evidence before commit -> safe replay;
- transient evidence failure -> no commit and no poll-past;
- permanent poison -> quarantine before commit;
- crash after quarantine before commit -> safe replay;
- nondurable receipts can never commit;
- Kafka message identity is namespace/topic/partition/offset;
- consumer group is progress identity only.

The supported-seam prototype then passed 10 focused tests against the exact ANTARES/TOM versions, including:

- preserving raw topic/partition/offset;
- explicit trigger selection;
- fail-closed missing/duplicate/absent trigger;
- no lazy HTTP history access;
- evidence-before-commit;
- quarantine-before-commit;
- no commit on transient/nondurable failure.

## Questions for TROVE maintainers

1. Is ANTARES the Rubin broker route you intend for Issue #23?
2. If yes, would you prefer the explicit trigger marker to be produced by an ANTARES filter/tag on a TROVE-specific output topic?
3. Does that output guarantee the current alert is embedded in the serialized Locus, or should the output carry a lossless current-alert snapshot?
4. Would you prefer the tiny partition/offset return seam to live in `antares-client`, `tom-alertstreams`, or somewhere else?
5. Is one-message-at-a-time/manual commit acceptable for the first safe integration, or do you already have a preferred supervised-consumer architecture?

I have intentionally not opened a TROVE code PR because the answers above should determine the patch boundary first.

## References

- TROVE Issue #23: https://github.com/astro-trove/trove/issues/23
- Project artifacts: https://github.com/GrobeStreet/bobby-research-os/tree/project/trove-rubin-bridge/projects/trove-rubin-bridge
- Supported seam review: https://github.com/GrobeStreet/bobby-research-os/blob/project/trove-rubin-bridge/projects/trove-rubin-bridge/supported_seam/SUPPORTED_SEAM_REVIEW.md
