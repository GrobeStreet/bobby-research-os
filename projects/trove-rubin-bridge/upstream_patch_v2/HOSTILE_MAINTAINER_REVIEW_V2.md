# Hostile maintainer review — TROVE Rubin evidence ingress v2

Review target: `0001-rubin-evidence-core.patch`

Frozen patch SHA-256: `ca476bf50b466bc47efbca06272b4d61eec157185c54a168fa368bc472f32c68`

Review posture: assume this code will eventually sit on a live broker path, receive duplicate/reordered/malformed messages, survive process restarts and database outages, and be relied on later as scientific provenance.

## Verdict

**Reject as merge-ready trustworthy evidence infrastructure. Keep the architecture direction; revise the implementation.**

The v2 patch fixed the scientific-interpretation failure from v1, but the hostile review finds three merge blockers and several high-priority hardening gaps:

1. evidence is described as immutable but is not actually immutable;
2. snapshot identity conflates an alert with mutable locus context and causes history-driven write/storage amplification;
3. accessing `locus.alerts` can reintroduce broker HTTP I/O inside the stream handler, while the current ANTARES/TOM path has unresolved offset/exception semantics.

The current green tests establish deterministic behavior for the reviewed fixture under SQLite. They do **not** establish production PostgreSQL concurrency, load, retention, or Kafka delivery safety.

---

## P1 — merge blockers

### 1. “Immutable” evidence is mutable, and the admin currently permits hash-breaking edits

`RubinAlertEvidence` is documented as an immutable scientific-evidence snapshot, but no model/database mechanism prevents updates or deletion.

More seriously, the admin `readonly_fields` list omits `broker_context`. The snapshot hash is computed over `{alert, broker_context}`, so a privileged admin can edit `broker_context` without changing `payload_sha256`. The row can then claim a hash that no longer describes its stored evidence.

Default Django admin deletion also remains available unless explicitly disabled.

The duplicate path does not recompute and verify the stored hash before incrementing delivery metadata, so an already-corrupted row can continue to accumulate apparently legitimate deliveries.

**Required before merge**

- Make the admin view-only: no add, content edit, or delete.
- Separate immutable evidence content from mutable delivery metadata.
- Add an integrity test that recomputes the canonical hash from the stored snapshot/context and fails on mismatch.
- Add application-level mutation protection for content fields. For high-assurance production, consider database permissions or a PostgreSQL trigger if maintainers accept that operational complexity.

### 2. Snapshot identity is attached to mutable locus context, creating semantic and storage amplification

Current identity is:

`(broker, source_record_id, SHA256(alert + broker_context))`

`broker_context` contains locus ID, tags, and locus-level GW associations.

ANTARES loci are mutable objects: tags can accumulate as filters run, and GW associations can change. List ordering is also preserved by the canonical JSON encoder, so semantically identical tag/GW sets in a different order produce different hashes.

The handler then iterates **every Rubin alert in `locus.alerts`**. A streaming locus represents an object with alert history. Therefore a later locus delivery can cause every historical Rubin alert to be revisited with the current locus context.

Consequences:

- unchanged historical alerts can acquire new “alert snapshots” merely because locus tags/GW context changed;
- exact context reorderings can create false new snapshots;
- `delivery_count` becomes “number of locus deliveries that happened to contain this historical alert,” not a clean count of deliveries of the alert itself;
- over a locus with growing history, database operations can approach `1 + 2 + ... + N = N(N+1)/2` even if only one genuinely new alert arrives each time;
- if context changes repeatedly, full raw alert JSON can be duplicated for every historical alert on every context version.

**Required before merge**

Split the concepts:

- `RubinAlertEvidence`: immutable alert snapshot, hashed from alert evidence only;
- `RubinEvidenceDelivery` or `RubinLocusContextEvidence`: append-only delivery/routing context, linked to the alert snapshot and independently hashed/versioned.

Do not make mutable locus tags part of alert-content identity.

### 3. `locus.alerts` may lazy-load over HTTP inside the Kafka handler

The v2 review response says external network/science work has been removed from ingress. That is not guaranteed.

ANTARES client `Locus.alerts` is documented as lazy-loaded from the ANTARES HTTP API when it is not already present. The current handler evaluates `locus.alerts` immediately and materializes it with `list(...)`.

TOM Toolkit's `AntaresAlertStream.listen()` calls the handler synchronously and does not add a local exception boundary around the call. The ANTARES client documentation also states that Kafka offsets are automatically committed periodically by default.

So the current future production path can still be:

`Kafka message -> handler -> implicit ANTARES HTTP fetch -> DB transaction`

A slow/failing HTTP fetch or database error can occur while broker offset handling is independent of evidence persistence. That recreates the exact transport hazard v2 was intended to avoid.

**Required before production wiring**

- Ingress must consume an eagerly supplied current-alert snapshot; do not lazy-load locus history inside the handler.
- Freeze and test the offset/ack contract before activation.
- Establish an explicit listener exception/restart/quarantine policy.
- Record enough transport provenance to replay/audit a delivery.

---

## P1/P2 — high-priority hardening

### 4. `raw_alert` is not raw wire evidence

`_alert_payload()` constructs a selected Python-level projection containing:

- alert ID,
- MJD,
- processed timestamp,
- properties,
- GW events.

Then `_json_safe()` rewrites values into JSON-safe forms. PostgreSQL `JSONField` stores JSONB in production.

This is useful broker evidence, but it is **not the original Kafka bytes or the original Rubin packet**. Calling it `raw_alert` overstates the provenance guarantee.

Also, the canonicalization/hash format is not versioned. A future change to `_json_safe()`, selected fields, or context rules can give the same logical evidence a different hash with no schema marker explaining why.

**Recommended**

- Rename to `broker_alert_snapshot` or equivalent.
- Add `evidence_schema_version` / `canonicalization_version`.
- Domain-separate the hash input, e.g. `trove-rubin-evidence:v1`.
- Record the broker/client/parser version where available.
- If byte-exact broker provenance is required, capture broker message bytes at the transport layer instead of claiming this model provides them.

### 5. Missing alert IDs should fail closed, not become hash-derived identities

The ANTARES client model documents `alert_id` as the alert's ANTARES identifier. Current code accepts a missing ID and invents:

`UNIDENTIFIED:<digest>`

That is deterministic for one exact payload/context but destroys stable identity across changed payload/context versions. It also masks a broker-schema violation.

**Recommended**

- Fail closed or quarantine if broker `alert_id` is absent.
- If maintainers explicitly approve a survey-native fallback, use a separately validated stable identity field rather than the content digest itself.

### 6. Changed-snapshot observability is race-prone

`had_other_snapshot = ...exists()` runs before `get_or_create()`.

The unique database constraint protects duplicate rows for the same `(broker, source_record_id, digest)`, and the `F()` increment avoids a lost-update race for `delivery_count`. But `changed_payload_snapshots` is only a best-effort process-local counter: concurrent first-seen versions can both observe no prior version and undercount the change event.

That does not corrupt evidence, but the metric should not be treated as authoritative.

**Recommended**

Derive changed-version metrics from committed database state/events, or make the counter explicitly non-authoritative.

### 7. Current CI does not exercise production PostgreSQL semantics

TROVE production settings use PostgreSQL when configured, but the frozen v2 validation explicitly ran with `POSTGRES_DB=''`, selecting the SQLite fallback.

The 7 focused tests and 200 full-suite tests are valuable regression evidence, but they do not test:

- concurrent `get_or_create()` on PostgreSQL;
- row-lock behavior of duplicate increments;
- deadlocks from concurrent multi-alert history updates;
- JSONB/TOAST storage growth;
- real index size/write amplification;
- production query plans.

**Required before calling the boundary production-ready**

Add a PostgreSQL CI job with at least:

1. simultaneous duplicate delivery of the same alert;
2. simultaneous changed versions of one alert;
3. concurrent deliveries touching overlapping history;
4. hash-integrity verification after round-trip;
5. measured storage/index growth on real Rubin fixtures.

### 8. One poison alert rolls back the entire locus transaction

The whole locus loop runs inside one `transaction.atomic()` block. If one historical alert fails during normalization or persistence, all good evidence in that locus delivery rolls back.

Because the current TOM ANTARES listener directly calls the handler, an uncaught exception can also escape the handler and terminate the listening loop.

**Recommended**

First fix the current-alert/history problem. Then define whether a broker message is the atomic unit. Add quarantine/dead-letter behavior for malformed evidence rather than allowing one historical record to poison all future deliveries.

### 9. No transport provenance in the evidence model

The handler receives only `locus`; it does not persist topic, Kafka partition, offset, or a broker message identifier. TROVE can therefore prove that it stored a broker-derived alert snapshot, but not exactly **which stream delivery** caused it.

This matters for replay, incident response, and claims about missed/duplicated messages.

**Recommended**

Capture transport metadata in the delivery/context table once the ANTARES transport contract is chosen.

### 10. Index and payload duplication should be budgeted, not guessed

The model stores the full alert snapshot plus extracted scalar columns plus duplicated quality/GW/context JSON. It also creates several single-column indexes in addition to composite/unique indexes.

PostgreSQL can TOAST/compress wide JSONB values, so a single stored Rubin alert is not automatically a problem. The real risk is repeated full-payload duplication caused by context-version snapshots and cumulative-history processing.

**Recommended**

- Fix snapshot/history semantics first.
- Measure `pg_column_size` and total relation/index growth on realistic filtered volumes.
- Remove redundant indexes after inspecting real query patterns.
- Set an explicit retention/archival policy before long-running production ingestion.

---

## Adversarial tests missing from v2

Before the next “green” claim, add tests for:

1. admin/model mutation cannot alter evidence content;
2. stored hash recomputes exactly;
3. same alert + reordered tags does not create a new alert-content snapshot;
4. same alert + new locus context creates only a context/delivery record, not a duplicate raw alert;
5. N sequential locus deliveries do not produce O(N^2) alert writes;
6. missing alert ID fails closed/quarantines;
7. two concurrent workers ingest the same alert on PostgreSQL;
8. two concurrent workers ingest different versions of the same alert;
9. one malformed alert does not silently lose valid evidence;
10. no handler path performs implicit HTTP history loading;
11. broker topic/offset provenance survives round-trip once transport is wired;
12. payload-size and table/index-growth budgets are enforced or at least measured.

---

## Recommended v3 boundary

```text
ANTARES transport message
    -> explicit current-alert payload + delivery metadata
    -> canonical alert snapshot (versioned)
    -> immutable RubinAlertEvidence
         identity = broker + broker_alert_id + alert_payload_hash
    -> append-only RubinEvidenceDelivery / RubinLocusContextEvidence
         topic / locus / GW / tags / received_at / transport IDs
    -> downstream interpretation layer (separate)
```

Core rule remains:

> **Ingress may move and preserve evidence. It may not silently reinterpret the evidence.**

v3 needs one additional rule:

> **Alert identity, delivery identity, and mutable broker context are three different things. Store them separately.**
