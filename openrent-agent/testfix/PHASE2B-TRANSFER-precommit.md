# PHASE2B-TRANSFER — Pre-commit: diff_kind_match Transfer Validity Audit

## Transfer claim
Phase 2b (diff_kind_match, MRR=0.905, GREEN on jaffle_shop_duckdb) was trained
and tested on one project.  The transfer claim is:

> diff_kind_match encodes reusable signal: the same feature computation (real
> SQL diff parser + is_agg/is_join candidate flags) improves localization on
> an unseen dbt project with the same ambiguity structure.

## Pre-committed transfer validity conditions

A transfer target is VALID (diagnostic for diff_kind_match) iff ALL three hold:

1. **Mechanical parser**: diff_kind is classified from the actual SQL diff
   hunk, not from case_id labels or hand-coded dicts.
   Status: DONE. diff_parser.classify_diff_kind(hunk) is the live parser,
   validated 11/11 on JAFFLE_DIFFS. (commit: diff_parser.py)

2. **Ambiguous pairs exist**: at least 2 candidate expressions in the target
   share the same context-key (same model, same set of diverged output cols
   when mutated).  If every mutation is unambiguous, diff_kind_match is
   irrelevant — localization was never the bottleneck.

3. **Mixed diff_kind**: at least one ambiguous group has candidates of
   different diff_kind (one agg + one join, or agg + arithmetic, etc.).
   If all ambiguous pairs share the same diff_kind, diff_kind_match is
   expected decorative (cannot separate them).

## Target selected: dbt-labs/mrr-playbook

Path: D:\transfer-rung2-mrr  (shallow clone of github.com/dbt-labs/mrr-playbook)

### Audit result (dbt_ambiguity_audit.py)

    Models scanned      : 4
    Total candidates    : 7
    Ambiguous groups    : 1
    Models with mixed   : 1
    Transfer validity   : VALID

Diagnostic model: models/customer_revenue_by_month.sql

Ambiguous group [MIXED — diagnostic]
  Output cols affected: {mrr, is_active, first_active_month, last_active_month,
                         is_first_month, is_last_month, date_month_start,
                         date_month_end, ...}

  Candidates:
    customers_date_month_start  kind=agg   date_trunc('month', min(start_date))
    customers_date_month_end    kind=agg   date_trunc('month', max(end_date))
    customer_months_join_0      kind=join  inner join months on months.date_month >= ...
    joined_join_0               kind=join  left join subscription_periods on ...

### Why this qualifies

In customer_revenue_by_month.sql:
- The `customers` CTE aggregates min/max dates → date_month_start / date_month_end
- The `customer_months` CTE inner-joins `months` on those date bounds
- Mutating `min(start_date)` (agg) OR mutating the join condition (join) would
  both change which (customer, month) rows exist in `customer_months`, affecting
  all downstream output columns.
- This is a MIXED-kind ambiguous pair: agg and join, same output-col set.
- diff_kind_match should separate them: in the agg episode, e_agg candidates
  get diff_kind_match=1; join candidates get 0. In the join episode, reversed.

### Structural difference from training project

In jaffle_shop_duckdb: agg and join are PARALLEL within the same CTE
(sum(amount) and left join orders both in customer_payments CTE, both
feeding customer_lifetime_value independently).

In mrr-playbook: agg FEEDS INTO the join condition (date_month_start from
the agg is the ON clause bound for the join). The cascade pattern is
different — but the ambiguity is the same: mutating either the agg or the
join affects the same final output columns.

Whether the cascade pattern changes the learner's convergence is an empirical
question for the transfer run.

### Limitation notes

1. The ambiguous group in mrr-playbook is broad (all final cols affected), vs
   jaffle_shop_duckdb where the ambiguity was column-specific (customer_lifetime_value
   only). Broader context-key means more candidates share it — potentially harder.

2. `subscription_periods` is a CSV seed, not a SQL model, so no candidates there.
   mrr.sql has only 1 candidate (arithmetic: mrr - previous_month_mrr).

3. The util_months model has no candidates. Only customer_revenue_by_month is
   the site of interest.

4. Total candidate pool is small (7 total, 4 in the diagnostic model).
   The simulation would need synthetic mutations of the mrr-playbook expressions.

## Pre-committed verdict conditions for the transfer run

Same bands as Phase 2b on jaffle_shop_duckdb (delta threshold 0.05):

| Band    | Condition                                                                    |
|---------|------------------------------------------------------------------------------|
| GREEN   | MRR_2b_learned > MRR_freq + 0.05  AND  > MRR_static + 0.05                 |
| YELLOW  | MRR_2b_learned > MRR_static + 0.05  AND  <= MRR_freq + 0.05                |
| RED     | MRR_2b_learned <= MRR_static + 0.05                                         |

If RED or YELLOW:
- If ambiguous groups on mrr-playbook all share the same diff_kind at runtime
  (despite audit saying VALID): do NOT call the mechanism false; call the
  target non-diagnostic. A non-diagnostic target RED is not a mechanism RED.
- If the ambiguous pairs ARE mixed-kind at runtime and still RED/YELLOW:
  then the mechanism may not generalise — report as narrow conditional failure.

## Files delivered (Step 1 + Step 2)

Step 1:
  diff_parser.py                  Real SQL diff parser, 11/11 validated
  dbt_phase2b.py (updated)        Uses diff_parser.classify_diff_kind, not hardcoded dict

Step 2:
  dbt_ambiguity_audit.py          General-purpose dbt ambiguity auditor
  PHASE2B-TRANSFER-precommit.md   This file
  Transfer target: D:\transfer-rung2-mrr (mrr-playbook, VALID)
