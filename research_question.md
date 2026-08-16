# Research Question

## Primary question

Can a reproducible public-data model of PFAS adsorption on granular activated carbon (GAC) rank candidate bench-scale water-matrix experiments by expected information gain well enough that a small selected experiment set recovers materially more of the known matrix-effect structure than an equally sized naive or random set?

## Primary outcome

The primary outcome for the selection experiment will be **held-out predictive uncertainty / error after each acquired experiment**, summarized as the area under the learning curve (AULC) across a fixed experiment budget.

EXP-001 is a prerequisite reproduction test: regenerate the directional water-matrix effects in EPA dataset DOI `10.23719/1531811` before fitting any experiment-selection policy.

## Success criterion

1. **EXP-001:** the deterministic parser reproduces the published directional effects for the baseline, pH, ionic-strength, calcium/sulfate, and NOM conditions from the EPA workbook.
2. **Selection phase:** a pre-specified information-gain policy has lower mean AULC than random selection over repeated seeded trials, and its advantage survives leave-one-PFAS / leave-one-matrix robustness checks.

A positive result would support the narrow claim that computational experiment selection can reduce uncertainty faster **within the studied public-data domain**. It would not establish full-scale treatment performance.

## Failure criterion

The project fails or is materially weakened if any of the following occurs:

- EXP-001 cannot reproduce the source dataset's directional effects.
- The selection policy does not outperform random / naive baselines after repeated seeded trials.
- The apparent advantage disappears under leave-one-PFAS, leave-one-condition, or alternative-model robustness tests.
- Results depend on information leakage from held-out conditions.
- Performance is driven by one compound or one matrix condition rather than general experiment-selection value.

## Competing explanations

- **H1 — useful selection signal:** matrix chemistry and PFAS identity contain learnable structure that supports better-than-random next-experiment selection.
- **H2 — interpolation artifact:** apparent gains arise because candidate experiments are near-duplicates, so any structured sampler looks good.
- **H3 — model artifact:** gains are specific to one surrogate model or uncertainty estimate and disappear under alternative baselines.
- **H4 — insufficient public data:** the available experiments are too sparse / heterogeneous for a robust selection advantage.

## Highest-value next experiment

**EXP-001:** independently reproduce the directional matrix effects in the EPA GAC source-water-characteristics workbook (DOI `10.23719/1531811`) from the raw spreadsheet with a checksum-pinned deterministic script.

Only if EXP-001 passes do we proceed to EXP-002 (construct the candidate experiment table and establish random / naive learning-curve baselines).
