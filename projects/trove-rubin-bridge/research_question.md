# Research question

## Primary question

Can a Rubin/LSST candidate delivered through ANTARES be converted into a TROVE-compatible target + photometry handoff in a way that is:

1. **idempotent** under repeated broker delivery;
2. **incremental** when the same locus gains new alerts;
3. **provenance-preserving** for broker locus ID, survey alert ID, timestamps, coordinates, band and GW association;
4. **time-safe** for historical replay (`as_of` never sees later alerts);
5. **fail-closed** when the input is not recognizably Rubin/LSST or lacks required documented fields; and
6. **science-neutral**, meaning it does not alter TROVE's candidate-scoring or transient-vetting logic?

## Primary metric

For a representative captured ANTARES Rubin locus replayed through the reference ledger:

- duplicate target creations: **0** after the first delivery;
- duplicate observation creations: **0**;
- missing required provenance fields in the handoff: **0**;
- future-alert leakage into any historical `as_of` view: **0**;
- malformed fixture silently accepted: **0**.

## Secondary metrics after real fixture access

- normalization success across multiple real Rubin loci;
- per-locus normalization time;
- percentage of alerts requiring unsupported survey-property fallbacks;
- end-to-end topic-to-TROVE processing latency once an upstream integration exists;
- error/retry behavior under broker redelivery.

## Out of scope for v0.1

- candidate ranking;
- kilonova classification;
- BBH scoring;
- multiband light-curve fitting;
- follow-up scheduling;
- production database migrations;
- live ANTARES credentials.
