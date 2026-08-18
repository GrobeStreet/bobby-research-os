# Validation report — 2026-08-18

## Scope

This report records the strongest result currently earned by the `trove-rubin-bridge` prototype. It validates the Rubin/ANTARES normalization boundary and persistence into TROVE's actual Django models/test databases. It does **not** claim production deployment, end-to-end live Kafka ingestion, or scientific-vetting validation.

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

## Target-hook sequencing finding

TOM Toolkit `BaseTarget.save()` unconditionally invokes TROVE's configured `target_post_save` hook. Therefore a naive `Target.objects.create/get_or_create` path can fire TROVE science before Rubin photometry has been persisted.

The database tests deliberately isolate that post-save science hook so they measure persistence/idempotency only. A production TROVE handler must explicitly solve sequencing so that the intended behavior is:

1. establish target identity;
2. persist only unseen Rubin photometry;
3. invoke the existing TROVE vetting path exactly once when genuinely new evidence arrived;
4. do not invoke expensive re-vetting on broker redelivery.

This is now a known integration requirement, not an assumption.

## Reproduction caveat: upstream dependency drift

A fresh install of TROVE main on 2026-08-18 is not resolvable with its checked-in `requirements.txt`: TROVE pins the TOM Toolkit fork at v2.32.3, while the unpinned `tom-nonlocalizedevents` dependency moved to TOM Toolkit 3 after the tested TROVE main state.

For this reproduction only, `tom-nonlocalizedevents` was pinned to pre-migration commit:

`d877e0281c6c826d753b19442a7452dbaafb00c5`

This reproduces the dependency era compatible with TROVE main rather than silently upgrading TROVE. The CI also applies the same upstream migration no-op patches used by TROVE's own current CI workflow.

## Machine-readable result

`integration/ci-status.json` records:

- `install_status: 0`
- `fixture_test_status: 0`
- `trove_db_test_status: 0`

The full runner transcript is preserved in `integration/ci-output.txt`.

## Claims earned

Supported:

> The prototype normalizes frozen real ANTARES Rubin loci and persists Rubin photometry idempotently through TROVE's actual Django Target and ReducedDatum models in TROVE's test-database environment. Duplicate broker replay creates no duplicate data and does not request re-vetting; a real incremental Rubin update inserts only unseen photometry and does request re-vetting.

Not yet supported:

- live ANTARES Kafka/topic ingestion into a deployed TROVE instance;
- production database behavior;
- finalized target-hook sequencing implementation upstream;
- latency/throughput performance;
- scientific candidate-ranking performance;
- maintainer acceptance of ANTARES as TROVE's intended Rubin production route.
