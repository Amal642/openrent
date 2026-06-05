# DBTAUDIT — DBT Localization Feature-Density Audit Precommit

## Question
Does the dbt domain have enough localisation signal for accumulated episode
experience to improve the composed loop over time?

OPEN-54 demonstrated improvement on OpenRent at the **model level** (cross-function
localization). In dbt the model-level problem is structurally at ceiling: DAG
topological order trivially identifies the mutated model for single-model mutations.
The audit tests whether **column/expression-level** signal is learnable — which
output columns diverged from parent → which SQL expression to repair.

## Candidate resolutions audited

- **L1 model level** (pool = 5 models): expected to be at ceiling; DAG-order is
  a deterministic oracle for single-model mutations. Measured to confirm.
- **L2 expression level** (pool = SQL expressions within the localized model):
  the question. Can column-divergence signal identify the mutated expression?

## Mutation set
12 mutations: 4 from transfer2 (d001-d004) + 8 new (d_c01-d_c05, d_o01-d_o02, d_s01).
d004 is a known build-error (Jinja syntax mutation). n_detectable ≤ 11.

## Pre-committed decision criterion

| Band   | Condition                                                             | Decision           |
|--------|-----------------------------------------------------------------------|--------------------|
| GREEN  | ≥60% of detectable mutations uniquely identifiable by column divergence | Proceed to Phase 2 |
| YELLOW | 40–59%                                                                | Add one feature (column_lineage_rank) then rerun |
| RED    | <40%                                                                  | Column-divergence insufficient; do not build loop |

"Uniquely identifiable" = exactly one candidate expression has feeds_cols = observed
diverged_cols (exact set match). The true expression must be that candidate.

## Additional measurements (non-verdict)
- For non-unique cases: how many candidates remain after column-narrowing?
  (Measures partial signal even below exact-match threshold.)
- Feature-weight regression: do any model-level features have non-trivial weight?
  (Expected: none — DAG-order is sufficient and perfectly discriminating at L1.)
- Accuracy of DAG-order model localization (expected: 100% on detectable mutations).

## What this does and does not prove
**Proves (if GREEN):** column-divergence features carry learnable signal at the
expression level in jaffle_shop_duckdb; a learned localiser has headroom to improve
beyond the structural DAG-order baseline as episodes accumulate.

**Does not prove:** (1) that signal generalises to other dbt repos or larger DAGs;
(2) that Phase 2 (the accumulation loop) will reach GREEN on repair — Phase 2 has
its own precommit; (3) anything about the hippocampal substrate (irrelevant here —
the learner is logistic regression on hand-defined features, not the substrate).

## Phase 2 gate
Phase 2 (30–50 episode accumulation run) is BLOCKED on a GREEN here.
If YELLOW: add one feature and rerun the audit before proceeding.
If RED: the learning signal does not exist at this resolution; do not build the loop.
