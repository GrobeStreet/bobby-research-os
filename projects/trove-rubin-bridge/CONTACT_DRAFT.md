# Draft outreach to Griffin Hosseinzadeh

**Subject:** Possible open-source contribution to TROVE Rubin alert ingestion (#23)

Hi Griffin — I’m Bobby Morong, an independent research engineer in San Diego working on reproducible scientific software, AI evaluation, and cosmology.

I’ve been reading through TROVE’s public code and issue tracker, and issue #23 (Rubin/LSST alert ingestion) looked like a place where I might be useful without touching the project’s science logic.

I built a small test-first prototype around this possible boundary:

**Rubin -> ANTARES -> thin TROVE-specific filter/topic -> TOM `AntaresAlertStream` -> TROVE handler -> existing target/post-save/vetting path.**

The prototype is intentionally narrow: normalization, idempotency under broker redelivery, incremental photometry, provenance, historical no-look-ahead tests, and fail-closed schema behavior. I did not modify TROVE scoring or build a competing transient classifier.

Before I take it further, I’m trying to validate two assumptions rather than guess:

1. Is ANTARES an acceptable/intended Rubin broker path for TROVE #23, or is the team planning a different ingestion route?
2. If ANTARES is reasonable, is there one representative sanitized Rubin `Locus` fixture (or intended topic/schema) I could use for an integration test?

If the direction is useful, I’d be happy to keep the first contribution tightly scoped to ingestion/idempotency/tests.

Best,
Bobby Morong
Independent research engineer
GitHub: https://github.com/GrobeStreet
Research portfolio: https://robert-morong-research.netlify.app
