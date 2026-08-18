# TROVE Rubin Bridge

**Independent, AI-assisted research engineering. Not an official TROVE component.**

A small, test-first prototype for one bounded question:

> Can Rubin/LSST candidates delivered through the ANTARES broker be normalized and handed to TROVE-style target/photometry workflows **idempotently, with provenance preserved, without changing TROVE's scientific scoring logic?**

This repository exists because TROVE's public V1 issue tracker includes **“Begin listening to the Rubin/LSST Alert streams”** and the current public TROVE configuration already uses `tom-alertstreams` for multimessenger alerts. Rubin alerts are now flowing to community brokers, and ANTARES already receives LSST alerts, associates recent gravitational-wave events, supports probability-region filter gating, and can route tagged loci to Kafka streams.

The thesis here is deliberately modest:

**Rubin -> ANTARES filter/topic -> TOM `AntaresAlertStream` -> thin TROVE handler -> existing TROVE target/post-save/vetting pipeline**

Not:

**Rubin firehose -> new parallel transient-ranking system.**

## Current evidence level

**Synthetic interface prototype only.**

What is tested now:

- documented ANTARES Locus/Alert fields can be normalized through one narrow boundary;
- repeated delivery of the same locus does not create duplicate observations in the reference ledger;
- incremental locus updates add only new alerts;
- source alert IDs, timestamps, bands, coordinates, broker identity, LSST metadata when available, and GW associations are preserved;
- historical `as_of` views do not see future alerts;
- malformed/non-LSST inputs fail closed instead of being guessed into the pipeline;
- a deterministic TROVE-shaped handoff record can be produced without importing TROVE/Django.

What is **not** tested yet:

- a captured production ANTARES LSST locus;
- a live ANTARES output topic;
- TROVE's production database or hook behavior;
- the final `ReducedDatum` uniqueness/source semantics maintainers want;
- end-to-end latency;
- scientific candidate quality, kilonova recall, or ranking performance.

Those are intentionally blocked until the maintainers confirm the integration contract.

## Why broker-mediated ingestion

Rubin's public documentation describes community alert brokers as the normal science-user path for the alert stream. ANTARES's current docs say:

- it receives LSST and ZTF alerts in real time;
- a `Locus` collects the object's metadata and alert history;
- survey alerts are checked against recent, non-retracted GW notices;
- per-alert GW contour metadata is attached when spatially associated;
- filters may set `REQUIRED_GRAV_WAVE_PROB_REGION`;
- tags can be routed to real-time Kafka output streams;
- the client `StreamingClient` yields `(topic, locus)` objects.

TROVE already depends on `tom-alertstreams`, whose ANTARES adapter passes the streamed Locus to a configured topic handler. The public TROVE settings currently configure a Hopskotch stream but not an ANTARES stream.

That suggests a small integration seam already exists.

## Architecture

```text
Rubin Prompt Products
        |
        v
      ANTARES
  - LSST ingest
  - GW association
  - optional probability-region filter
  - TROVE-specific tag/topic
        |
        v
 tom-alertstreams AntaresAlertStream
        |
        v
 thin TROVE handler
  - normalize identity
  - create/update target
  - append new photometry only
  - preserve source/provenance
        |
        v
 existing TROVE hooks + candidate vetting
```

The code in this repository implements only the conceptual boundary between an ANTARES Locus and a TROVE-compatible handoff plan. It does not recreate TROVE's science.

## Research discipline

This repo follows the working rules in [Bobby Research OS](https://github.com/GrobeStreet/bobby-research-os):

**Question -> Evidence -> Hypothesis -> Adversarial Tests -> Computation -> Falsification -> Replication -> Artifact**

Start with:

- [`research_question.md`](research_question.md)
- [`preregistration.md`](preregistration.md)
- [`assumptions.yaml`](assumptions.yaml)
- [`AI_USAGE.md`](AI_USAGE.md)
- [`evidence/SOURCES.md`](evidence/SOURCES.md)

## Run it

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
pytest
python examples/demo.py
```

No ANTARES credentials or TROVE install are required for the current synthetic test suite.

## The next external dependency

The smallest useful request to TROVE/ANTARES is **not production access**. It is:

1. confirmation that ANTARES is the intended Rubin broker path for TROVE issue #23; and
2. one representative sanitized/captured Rubin `Locus` fixture (or the exact topic/schema they intend to consume).

With that, this prototype can become a fixture-driven upstream implementation rather than an architecture guess.

## What this does not claim

- This is not affiliated with or endorsed by TROVE, UC San Diego, Rubin Observatory, NSF NOIRLab, ANTARES, LIGO/Virgo/KAGRA, or TOM Toolkit.
- The synthetic fixture is not production ANTARES data.
- No new transient classifier or scientific ranking method is proposed here.
- Passing these tests does not establish scientific usefulness; it establishes software-boundary behavior only.
- No pull request to TROVE should be opened until maintainers confirm the broker/topic/schema direction.

— Robert “Bobby” Morong, independent research engineer
