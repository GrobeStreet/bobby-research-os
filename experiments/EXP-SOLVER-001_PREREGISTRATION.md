# EXP-SOLVER-001 — Frontier Solver OS held-out A/B test

Status: **PREREGISTERED / BLOCKED UNTIL FIRST FAIR EXTERNAL RECEIPT**

Preregistered: 2026-08-23

## Purpose

Test whether the Frontier Solver OS materially improves problem-solving performance relative to a minimal/general instruction condition when the **same base model, same tools, same held-out tasks, and same task budget** are used.

This experiment must not begin until FAIR EXP-001 has produced and frozen its first valid external Codabench receipt. FAIR EXP-001 itself is excluded from the evaluation set and may not be used as a test task.

## Primary question

Does the Solver OS increase held-out verified solve coverage or reduce median solve cost without materially degrading calibration, verification quality, judge accuracy, or benign utility?

## Conditions

### Condition A — Control

- Same base model as Condition B.
- Same model version / effort setting.
- Same tool access.
- Same context window and task inputs.
- Minimal generic instruction sufficient to perform the task safely and correctly.
- No Frontier Solver OS modules, terminology, memory, or strategy library.

### Condition B — Solver OS

- Same base model as Condition A.
- Same model version / effort setting.
- Same tool access.
- Same context window and task inputs.
- Frontier Solver OS operating discipline enabled, including:
  - objective compilation;
  - claim/uncertainty tracking;
  - hypothesis portfolio;
  - discriminating next-test selection;
  - generator / critic / verifier role separation where feasible;
  - failure localization;
  - evidence preservation;
  - explicit stop rules;
  - memory admission / retirement rules where applicable.

## Held-out task policy

Tasks must be selected **before either condition is run** and must not be copied from, paraphrased from, or substantially overlap with tasks used to create the Solver OS documents.

Target domains:

1. scientific reproduction / debugging;
2. AI benchmark or evaluation auditing;
3. code / infrastructure diagnosis;
4. optional authorized red-team diagnosis, only where rules and authorization are explicit.

FAIR EXP-001, the MMLU option-order audit, and any red-team examples used to design the OS are excluded from the held-out set.

## Randomization / pairing

- Each task is attempted under both conditions.
- Order of A/B execution is randomized per task with a fixed recorded seed.
- A condition must not see the other condition's transcript, intermediate artifacts, or answer before its run is complete.
- If tasks require external mutable state, both conditions must receive equivalent snapshots or the task is excluded.

## Budget parity

For each task, A and B receive the same maximum:

- wall-clock allowance;
- tool-call / query allowance;
- compute allowance;
- external API allowance;
- human intervention allowance.

If either condition exceeds the preset budget, record a budget failure rather than extending it post hoc.

## Primary outcomes

1. **Verified solve coverage** — fraction of held-out tasks meeting the predeclared task success predicate.
2. **Median solve cost** — median normalized resource cost among tasks attempted, including tool/query count and wall-clock time where measurable.

## Secondary outcomes

- queries / tool calls to first decisive evidence;
- calibration of stated confidence against correctness;
- number of material false claims caught before final answer;
- reproducibility / replay success of final artifacts;
- external-judge or deterministic-verifier accuracy where available;
- benign-task utility / regression;
- failure localization quality;
- transfer of useful strategy across tasks without leakage.

## Promotion gate

The Solver OS is promoted as empirically supported only if **at least one** of the following primary criteria is met:

- absolute improvement of **>= 10 percentage points** in held-out verified solve coverage; or
- **>= 25% reduction** in median solve cost;

and there is **no material degradation** in calibration, verification quality, external/deterministic judge accuracy, or benign utility.

A nominal win that depends on one outlier task, post-hoc task exclusion, unequal budgets, or task leakage does not count.

## Minimum sample / interpretation

A pilot may be run to test harness mechanics, but pilot results do not promote the OS. The confirmatory set should contain enough paired held-out tasks across at least three domains to make a single-task swing non-decisive. Exact final sample size must be frozen before confirmatory execution and recorded in the experiment registry.

## Verification

For every task, preserve:

- task specification and success predicate;
- condition assignment and order;
- exact model/version/effort setting;
- tool configuration;
- budget;
- raw transcript / logs where policy permits;
- artifacts produced;
- deterministic or external verification result;
- resource-use measurements;
- failure layer if unsolved.

Scoring code and aggregation rules must be frozen before confirmatory results are inspected.

## Forbidden post-hoc changes

After confirmatory execution begins, do not:

- change the promotion threshold;
- add or remove tasks because of observed outcomes;
- change success predicates;
- extend one condition's budget;
- expose one condition's work to the other;
- change the base model for only one condition;
- reinterpret failures as partial successes without a predeclared rule.

Any unavoidable deviation must be logged as post hoc and analyzed separately.

## Stop rule

Do not formally test or promote the Solver OS before the first FAIR EXP-001 external receipt is frozen.

After the confirmatory A/B completes:

- promote if the preregistered gate is met;
- revise or reject modules if it is not;
- preserve mixed/null results and identify which modules, domains, or cost components drove the outcome.

## Current blocker

FAIR EXP-001 external Codabench receipt has not yet been frozen. Until that occurs, this document is preparation only and no confirmatory Solver OS A/B runs should be started.
