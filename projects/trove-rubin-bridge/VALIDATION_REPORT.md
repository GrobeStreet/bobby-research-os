# Validation report — 2026-08-18

## Scope

This report records the strongest result currently earned by the `trove-rubin-bridge` prototype. It validates the Rubin/ANTARES normalization boundary, persistence into TROVE's actual Django models/test databases, and the target/photometry/vetting sequencing contract. It does **not** claim production deployment, end-to-end live Kafka ingestion, distributed crash-proof exactly-once execution, or scientific-ranking validation.

## Frozen external data

The bridge was tested against five loci retrieved from the live public ANTARES database with `antares-client==1.14.0`, plus a separately selected real locus with at least two Rubin alerts for incremental replay.

The incremental fixture was selected by scanning LSST-associated ANTARES loci until a locus with >=2 `lsst:` alerts was found:

- ANTARES locus: `ANT2021silgg`
- Rubin DIA Object ID: `170604730330906635`
- loci scanned: 13
- total alerts on locus: 366
- actual Rubin alerts on locus: 2
- frozen fixture SHA-256: `659ebcd273e6f2bc854b724e0281c1d0b18fce7d7b88b42e924ecb38b0c8983d`

## Adapter validation

Four deterministic real-fixture tests pass:

1. all five original frozen live LSST-associated loci normalize successfully;
2. cross-survey loci ingest only Rubin `lsst:` alerts, not attached ZTF history;
3. nested list-valued `properties.survey.lsst.dia_object_id` is normalized to one scalar identity;
4. Rubin alert-level GW provenance is preserved exactly without leaking GW associations attached only to non-Rubin alerts.

## TROVE database validation

Validation ran against:

- TROVE main commit: `9f2309890b248d78fc470632c7ee5d9c8c4739b6`
- Python: 3.11
- TROVE's SQLite test-database path
- actual `trove_targets.models.Target`
- actual `tom_dataproducts.models.ReducedDatum`

Two database integration tests pass.

### Duplicate replay

For a real Rubin/ANTARES locus:

- first ingest creates exactly one TROVE Target;
- each normalized Rubin observation creates one ReducedDatum;
- every ReducedDatum has `source_name = Rubin/ANTARES` and an `lsst:` source location;
- replaying the identical locus creates zero additional Targets;
- replaying the identical locus creates zero additional ReducedDatum rows;
- duplicate replay returns `should_revet = False`.

### Incremental replay

For the real two-Rubin-alert locus `ANT2021silgg`:

- delivery A creates one observation and returns `should_revet = True`;
- delivery A+B creates exactly one additional observation, recognizes A as duplicate, and returns `should_revet = True`;
- replay A+B creates zero new observations and returns `should_revet = False`;
- final ReducedDatum count equals the number of real Rubin alerts in the frozen locus.

## Exactly-once vet sequencing validation

TOM Toolkit `BaseTarget.save()` unconditionally invokes TROVE's configured `target_post_save` hook. Therefore a naive `Target.objects.create/get_or_create` path can fire TROVE science before Rubin photometry has been persisted.

The proposed sequence uses one instance-local defer marker on a newly created Rubin target:

`_trove_defer_target_post_save = True`

and a minimal guard at the top of TROVE's `custom_code.hooks.target_post_save`:

```python
if getattr(target, "_trove_defer_target_post_save", False):
    return [], None
```

This preserves TROVE's normal `Target.save()` behavior, including its derived target fields, while deferring science only for that target instance. After target identity exists, the bridge persists only unseen Rubin photometry and explicitly invokes TROVE's existing `target_post_save(target, created=True)` exactly once when new evidence was inserted.

Five sequencing tests pass against current TROVE main and the actual Django test-database environment:

1. a first real Rubin observation is persisted before the vet callback runs, and vetting is invoked exactly once;
2. identical broker redelivery creates zero observations and invokes vetting zero times;
3. real incremental delivery A -> A+B inserts only B and invokes vetting exactly once for that new batch, while replay A+B invokes zero vetting;
4. the proposed instance-local guard causes TROVE's real `target_post_save` to return before `vet_basic` for the marked target;
5. TROVE's actual `target_post_save` entrypoint is used as the vet callback with external/scientific dependencies isolated. Its `vet_basic` entrypoint observes Rubin photometry counts `[1, 2]` across the initial and incremental deliveries, proving the science entrypoint is reached only after the corresponding new evidence exists. Duplicate partial and full deliveries invoke zero vetting.

The CI transcript records:

```text
=== install proposed instance-local defer guard ===
guard installed
=== run sequence tests ===
.....                                                                    [100%]
```

Machine-readable sequencing result in `integration/sequence-ci-status.json`:

- `install_status: 0`
- `vet_sequence_test_status: 0`
- TROVE commit: `9f2309890b248d78fc470632c7ee5d9c8c4739b6`
- reproduction `tom-nonlocalizedevents` pin: `d877e0281c6c826d753b19442a7452dbaafb00c5`

The full sequencing runner transcript is preserved in `integration/sequence-ci-output.txt`.

### Exactness boundary

The earned claim is exactly-once **vet invocation per successfully processed broker delivery containing genuinely new Rubin evidence**, with duplicate delivery suppressed by persisted alert identity.

This is not a claim of distributed exactly-once execution across process crashes or non-transactional external side effects inside downstream scientific vetting. A production system that requires that stronger guarantee would need an outbox/task-state design or another durable post-commit execution protocol.

## Reproduction caveat: upstream dependency drift

A fresh install of TROVE main on 2026-08-18 is not resolvable with its checked-in `requirements.txt`: TROVE pins the TOM Toolkit fork at v2.32.3, while the unpinned `tom-nonlocalizedevents` dependency moved to TOM Toolkit 3 after the tested TROVE main state.

For this reproduction only, `tom-nonlocalizedevents` was pinned to pre-migration commit:

`d877e0281c6c826d753b19442a7452dbaafb00c5`

This reproduces the dependency era compatible with TROVE main rather than silently upgrading TROVE. The CI also applies the same upstream migration no-op patches used by TROVE's own current CI workflow.

## Claims earned

Supported:

> Against current TROVE main's actual Django model/test-database environment and frozen real ANTARES Rubin data, the proposed handler sequence persists new Rubin evidence before invoking TROVE vetting, invokes vetting exactly once for each successfully processed delivery containing genuinely new Rubin photometry, and invokes it zero times for duplicate broker redelivery. TROVE's actual `target_post_save` entrypoint was exercised with downstream external/scientific work isolated; its `vet_basic` entrypoint saw database counts of 1 then 2 after the initial and incremental real Rubin deliveries.

Not yet supported:

- live ANTARES Kafka/topic ingestion into a deployed TROVE instance;
- production database behavior;
- distributed crash-proof exactly-once side-effect execution;
- an upstream TROVE merge or maintainer acceptance;
- latency/throughput performance;
- scientific candidate-ranking performance;
- maintainer acceptance of ANTARES as TROVE's intended Rubin production route.
