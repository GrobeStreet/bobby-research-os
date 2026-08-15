# Adversarial Test Suite

Every major result should be attacked before release.

## Data attacks
- leave-one-dataset-out
- leave-one-subset-out
- bootstrap / jackknife
- outlier removal
- data perturbation
- alternate preprocessing / quality cuts
- synthetic null data
- shuffled labels where appropriate

## Statistical attacks
- alternative priors
- alternative estimators / likelihoods
- convergence diagnostics
- posterior predictive checks
- nuisance-parameter sensitivity
- multiple-comparison / selection correction
- null calibration and coverage tests

## Computational attacks
- independent implementation
- seed variation
- dependency/version changes
- numerical precision changes
- alternate optimizer / solver
- cold reproduction in a clean environment

## Interpretation attacks
Ask:
1. What is the strongest boring explanation?
2. What hidden variable could produce this?
3. What would a skeptical domain expert expect?
4. Which analysis choice has maximum leverage?
5. Did the search over alternatives create a look-elsewhere problem?
6. Are we confusing model preference with evidence for physical truth?

## Attempts to kill the result
For each attack record:

| Test | Why it matters | Expected failure signature | Observed result | Effect on conclusion |
|---|---|---|---|---|
