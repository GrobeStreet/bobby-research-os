# Bobby Research OS v1.0

A traceability-first operating system for independent, AI-assisted frontier research.

> **Question -> Evidence -> Hypothesis -> Adversarial Tests -> Computation -> Falsification -> Replication -> Artifact**

## Purpose

Bobby Research OS is designed to answer a simple question: **how much credible scientific work can one independent human produce when frontier AI is treated as cognitive infrastructure rather than an authority?**

The objective is not maximum output. It is maximum trustworthy information produced per researcher.

## Core rule

**AI proposes. Deterministic systems verify. Evidence remains traceable.**

Every serious project should end with three layers:

1. **Executive decision output** — what did we learn and what should happen next?
2. **Technical evidence** — why should anyone believe the conclusion?
3. **Reproducible repository** — can another competent researcher regenerate and interrogate the result?

## Start a project

1. Copy this repository as a GitHub template.
2. Fill in `research_question.md`.
3. Pre-specify decisive tests in `preregistration.md` before inspecting the decisive result.
4. Register sources and claims in `evidence/`.
5. Assign every consequential analysis an experiment ID in `experiments/registry.csv`.
6. Run the adversarial test suite and record attempts to kill the result.
7. Package the final decision memo, technical report, limitations, and reproducibility statement.
8. Make the central result regenerable with `make reproduce` or `./reproduce.sh`.

## Repository map

- `RESEARCH_CONSTITUTION.md` — non-negotiable epistemic rules
- `research_question.md` — falsifiable question, metric, success and failure criteria
- `preregistration.md` — pre-specified tests and post-hoc boundary
- `assumptions.yaml` — explicit versioned assumptions
- `AI_USAGE.md` — disclosure of AI involvement and verification
- `evidence/` — source, claim, and contradiction registries
- `experiments/` — experiment registry and per-experiment records
- `reports/` — executive, technical, limitations, reproducibility outputs
- `tests/` — automated integrity/reproduction tests
- `src/` — deterministic analysis code
- `outputs/` — generated figures, tables, logs, and models
- `reproduce.sh` / `Makefile` — one-command reproduction entry point

## Validation ladder

0. Observation
1. Internal reproduction
2. Robustness
3. Null calibration
4. Independent implementation
5. External benchmark
6. Independent replication
7. Formal scientific validation

Claims should be written at the level actually earned.

## Public disclosure

Recommended label for public work:

> **Independent, AI-assisted research. Not peer reviewed unless explicitly stated otherwise.**

## First externally scored implementation

The intended first instantiation is **`fair-universe-2026`**, targeting the NeurIPS 2026 FAIR Universe Weak Lensing Uncertainty Challenge Phase 2.

## Status

**v1.0 — active development**
