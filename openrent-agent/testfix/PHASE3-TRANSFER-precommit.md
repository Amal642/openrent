# PHASE3-TRANSFER — Pre-commit: Phase 3 transfer to fivetran/dbt_stripe

## Transfer claim

The full Phase 3 feature stack (structural + hist_freq + diff_kind_match + alias_in_hunk),
trained from scratch on project 3's episodes, improves localization on an unseen dbt
project without tuning. The attribution question:

> Do the gains come from diff_kind_match, alias_in_hunk, or both?

The pre-committed attribution: diff_kind_match should lift s_inv03 (join mutation,
uniquely separated from agg candidates); alias_in_hunk should lift s_inv02 (agg
mutation, separated from the other agg candidate by output alias). If only one fires,
that is a partial transfer.

---

## Candidate targets audited

| Project | Verdict | Reason |
|---|---|---|
| dbt-labs/attribution-playbook | THIN | 1 model, SELECT * throughout, 0 ambiguous pairs |
| dbt-labs/shopify | THIN | 11 models, 0 candidates detected (direct column pass-through) |
| **fivetran/dbt_stripe** | **VALID** | 69 models, 121 candidates, 6 models with mixed diff_kind |

Auditor: `dbt_ambiguity_audit.py`, 2026-06-05.

---

## Target selected: fivetran/dbt_stripe, model stripe__invoice_details.sql

Path: `D:\transfer-rung3-stripe`
Diagnostic model: `models/stripe__invoice_details.sql`
Auditor output: 6 candidates, 1 MIXED ambiguous group (2 agg + 4 join)

---

## Structural pattern: CHILD-AGGREGATE-JOIN

```
invoice_line_item CTE:
    SELECT invoice_id, source_relation,
           count(distinct ...) AS number_of_line_items,
           sum(quantity)       AS total_quantity
    FROM stg_stripe__invoice_line_item
    GROUP BY 1, 2

Final SELECT:
    ... explicit aliases from invoice ...
    invoice_line_item.number_of_line_items,   -- from the agg CTE
    invoice_line_item.total_quantity,         -- from the agg CTE
    charge.*,
    customer.*,
    subscription.*
    FROM invoice
    LEFT JOIN invoice_line_item ON invoice.invoice_id = ...
    LEFT JOIN charge             ON invoice.charge_id  = ...
    LEFT JOIN subscription       ON invoice.subscription_id = ...
    LEFT JOIN customer           ON invoice.customer_id = ...
```

The pre-aggregation CTE (`invoice_line_item`) summarises the child table BEFORE the
final join-star assembles invoice + child-agg + dimension tables. The aggregate and
the join to the aggregated CTE are at DIFFERENT CTE levels.

### Why structurally distinct from prior targets

| Pattern | Characteristic |
|---|---|
| jaffle_shop PARALLEL | agg and join coexist WITHIN THE SAME CTE; both independently populate same column (customer_lifetime_value) |
| mrr-playbook CASCADE | agg output (date_month_start) IS USED as the join ON-clause bound; agg and join are structurally linked |
| **stripe CHILD-AGGREGATE-JOIN** | pre-aggregation CTE produces child metrics; final SELECT assembles via join ON entity key (invoice_id), not on aggregate values |

The key distinction from CASCADE: here the join uses the primary entity key
(invoice.invoice_id = invoice_line_item.invoice_id), NOT the aggregated value as a
bound. Mutating the agg expression and mutating the join ON condition are structurally
independent changes, not causally linked.

The key distinction from PARALLEL: here the agg and join live in separate query layers
(CTE level vs. final SELECT level), not within the same CTE's FROM clause.

---

## Pre-committed validity conditions

All three must hold for the target to be diagnostic:

1. **Mechanical parser**: diff_kind classified from real SQL diff hunk.
   Status: DONE. diff_parser.classify_diff_kind is the live parser. ✓

2. **Ambiguous pairs exist**: >= 1 candidate groups with same context key (same feeds_cols).
   Status: CONFIRMED. Group A = {e_count_lines, e_sum_qty, e_join_ili}, all feeding
   {number_of_line_items, total_quantity}. ✓

3. **Mixed diff_kind**: >= 1 ambiguous group has candidates of different diff_kind.
   Status: CONFIRMED. e_count_lines (agg) + e_sum_qty (agg) + e_join_ili (join). ✓

---

## Expression candidates

Model: `models/stripe__invoice_details.sql`

### Group A — invoice_line_item metrics: {number_of_line_items, total_quantity}

| expr_id | kind | is_agg | is_join | alias | joined_table | line | snippet |
|---|---|---|---|---|---|---|---|
| e_count_lines | agg | True | False | number_of_line_items | — | 18 | coalesce(count(distinct unique_invoice_line_item_id),0) as number_of_line_items |
| e_sum_qty | agg | True | False | total_quantity | — | 19 | coalesce(sum(quantity),0) as total_quantity |
| e_join_ili | join | False | True | — | invoice_line_item | 91 | left join invoice_line_item on invoice.invoice_id = invoice_line_item.invoice_id |

feeds_cols (Group A) = frozenset({"number_of_line_items", "total_quantity"})

### Group B — charge metrics

| expr_id | kind | alias | joined_table | line |
|---|---|---|---|---|
| e_join_charge | join | — | charge | 96 |

feeds_cols = frozenset({"charge_amount", "charge_status", "charge_created_at", "charge_is_refunded"})

### Group C — subscription metrics

| expr_id | kind | alias | joined_table | line |
|---|---|---|---|---|
| e_join_sub | join | — | subscription | 101 |

feeds_cols = frozenset({"subscription_billing", "subscription_start_date", "subscription_ended_at"})

### Group D — customer metrics

| expr_id | kind | alias | joined_table | line |
|---|---|---|---|---|
| e_join_cust | join | — | customer | 107 |

feeds_cols = frozenset({"customer_id", "customer_description", "customer_account_balance",
                        "customer_currency", "customer_is_delinquent", "customer_email"})

---

## Episode cases

6 cases per round × 4 rounds = 24 episodes total.

| case_id | true | div_cols group | diff | amb | sub_dk |
|---|---|---|---|---|---|
| s_inv01 | e_count_lines | Group A | agg | True | **True** |
| s_inv02 | e_sum_qty | Group A | agg | True | **True** |
| s_inv03 | e_join_ili | Group A | join | True | False |
| s_inv04 | e_join_charge | Group B | join | False | False |
| s_inv05 | e_join_sub | Group C | join | False | False |
| s_inv06 | e_join_cust | Group D | join | False | False |

Sub-dk subset = {s_inv01, s_inv02}: both agg candidates with identical 11-feature
vectors (Phase 2b cannot separate them). alias_in_hunk is the resolution signal.

### Candidate pools by div_cols

- Group A div_cols: pool = {e_count_lines, e_sum_qty, e_join_ili}, n_cands=3
- Groups B-D: pool = 1 candidate each (non-overlapping feeds_cols)

---

## Synthetic diff hunks

Constructed from stripe__invoice_details.sql (git diff -U2 style).

```
STRIPE_DIFFS = {
    # s_inv01: invoice_line_item CTE -- mutate count(distinct ...) [agg]
    "s_inv01": """\
@@ -16,6 +16,6 @@
     select
         invoice_id,
         source_relation,
-        coalesce(count(distinct unique_invoice_line_item_id),0) as number_of_line_items,
+        coalesce(count(unique_invoice_line_item_id),0) as number_of_line_items,
         coalesce(sum(quantity),0) as total_quantity
""",

    # s_inv02: invoice_line_item CTE -- mutate sum(quantity) [agg]
    "s_inv02": """\
@@ -17,6 +17,6 @@
         invoice_id,
         source_relation,
         coalesce(count(distinct unique_invoice_line_item_id),0) as number_of_line_items,
-        coalesce(sum(quantity),0) as total_quantity
+        coalesce(sum(quantity * 2),0) as total_quantity
 
""",

    # s_inv03: final SELECT -- mutate left join invoice_line_item ON condition [join]
    "s_inv03": """\
@@ -91,5 +91,5 @@
 left join invoice_line_item 
-    on invoice.invoice_id = invoice_line_item.invoice_id
+    on invoice.invoice_id != invoice_line_item.invoice_id
     and invoice.source_relation = invoice_line_item.source_relation
""",

    # s_inv04: final SELECT -- mutate left join charge ON condition [join]
    "s_inv04": """\
@@ -96,5 +96,5 @@
 left join charge 
-    on invoice.charge_id = charge.charge_id
+    on invoice.charge_id != charge.charge_id
     and invoice.invoice_id = charge.invoice_id
""",

    # s_inv05: final SELECT -- mutate left join subscription ON condition [join]
    "s_inv05": """\
@@ -101,5 +101,5 @@
 left join subscription
-    on invoice.subscription_id = subscription.subscription_id
+    on invoice.subscription_id != subscription.subscription_id
     and invoice.source_relation = subscription.source_relation
""",

    # s_inv06: final SELECT -- mutate left join customer ON condition [join]
    "s_inv06": """\
@@ -107,5 +107,5 @@
 left join customer 
-    on invoice.customer_id = customer.customer_id
+    on invoice.customer_id != customer.customer_id
     and invoice.source_relation = customer.source_relation
""",
}
```

### Expected diff_kind classifications

| case_id | expected |
|---|---|
| s_inv01 | agg |
| s_inv02 | agg |
| s_inv03 | join |
| s_inv04 | join |
| s_inv05 | join |
| s_inv06 | join |

---

## Alias_in_hunk pre-flight predictions

| case_id | e_count_lines | e_sum_qty | e_join_ili | others | verdict |
|---|---|---|---|---|---|
| s_inv01 | **1** (AS number_of_line_items in changed) | 0 | 0 (inv_line_item not in hunk) | n/a | UNIQUE |
| s_inv02 | 0 | **1** (AS total_quantity in changed) | 0 | n/a | UNIQUE |
| s_inv03 | 0 | 0 | **1** (invoice_line_item in full hunk) | n/a | UNIQUE |
| s_inv04-06 | n/a (not in pool) | n/a | n/a | 1 candidate each | trivially UNIQUE |

All three Group A cases uniquely resolved by alias_in_hunk. This is cleaner than
mrr-playbook where m_crm02 had a TIE (resolved only by the combined feature vector).

---

## Theoretical predictions

Based on structural analysis (before simulation):

| Method | MRR_full (theory) | MRR_sub_dk (theory) |
|---|---|---|
| static | 0.806 | 0.750 |
| frequency | ~0.76 (symmetric tie in Group A will suppress freq) | ~0.67 |
| learned_2b | 0.917 | 0.750 |
| learned_3 | 1.000 | 1.000 |

Rationale:
- s_inv01: static rank 1 (e_count_lines has _idx=0, ties broken by index); 2b=rank1; 3=rank1
- s_inv02: static rank 2 (e_sum_qty has _idx=1); 2b=rank2 (identical features to e_count_lines); 3=rank1 (alias fixes)
- s_inv03: static rank 3 (e_join_ili has _idx=2); 2b=rank1 (diff_kind_match separates join from both agg); 3=rank1
- s_inv04-06: always rank 1 (single candidate in pool)

Delta 2b vs static (full): +0.111 from fixing s_inv03. Predicted GREEN for Phase 2b.
Delta 3 vs 2b (sub_dk): +0.250 from fixing s_inv02. Predicted GREEN for Phase 3.

---

## Pre-committed verdict bands

### Feature-level attribution (primary question)

| Measure | Operationalisation |
|---|---|
| diff_kind_match gain | Δ_2b_vs_static: does 2b beat static? If YES: diff_kind_match transfers |
| alias_in_hunk gain | Δ_3_vs_2b (sub_dk subset): does 3 beat 2b on {s_inv01,s_inv02}? If YES: alias transfers |
| Both fire | Both deltas >= 0.05 |
| Only diff_kind fires | Δ_2b_vs_static >= 0.05, Δ_sub_dk < 0.05 |
| Only alias fires | Δ_2b_vs_static < 0.05, Δ_sub_dk >= 0.05 |
| Neither fires | Both deltas < 0.05 — RED |

### Overall Phase 3 transfer verdict bands (same thresholds as prior runs, delta=0.05)

| Band | Condition |
|---|---|
| GREEN | learned_3 > static + 0.05 AND > freq + 0.05 (full MRR) |
| YELLOW | learned_3 > static + 0.05 AND <= freq + 0.05 |
| RED | learned_3 <= static + 0.05 |

### Sub-dk alias verdict bands

| Band | Condition |
|---|---|
| GREEN | delta_3_vs_2b (sub_dk) >= +0.05 |
| YELLOW | delta_3_vs_2b (sub_dk) in (0, +0.05) |
| RED | delta_3_vs_2b (sub_dk) <= 0 |

---

## Failure interpretation rules

1. If RED on full MRR but sub_dk GREEN:
   alias_in_hunk transfers for within-kind disambiguation but the overall model adds noise
   elsewhere. Not a mechanism failure; scope it to the sub-dk claim.

2. If diff_kind_match FAILS to lift s_inv03 (static 0.333, 2b 0.333):
   Possible cause: the join ON condition mutation uses `!=` which still hits _COND_RE.
   Run diff_parser.classify_diff_kind(s_inv03_hunk) manually to confirm it returns "join".
   If it returns "unknown", the hunk is incorrectly constructed — fix the hunk, rerun.

3. If alias_in_hunk misfires on Group B-D (pools have 1 candidate each):
   Irrelevant for the verdict. Single-candidate pools are trivially correct regardless of
   alias_in_hunk. The verdict depends only on Group A cases.

4. If all Group B-D cases show alias_in_hunk=1 for the single correct candidate:
   No harm; just additional positive training signal for the feature.

---

## Files delivered

Step 1 (auditor + candidate selection):
  dbt_ambiguity_audit.py        General-purpose dbt ambiguity auditor
  D:\transfer-rung3-attribution  Attribution-playbook (THIN, non-diagnostic)
  D:\transfer-rung3-shopify      Shopify (THIN, non-diagnostic)
  D:\transfer-rung3-stripe       fivetran/dbt_stripe (VALID, CHILD-AGGREGATE-JOIN)

Step 2 (this file):
  PHASE3-TRANSFER-precommit.md  Transfer validity pre-commit

Pending (after precommit approval):
  dbt_phase3_stripe.py          Transfer simulation script
