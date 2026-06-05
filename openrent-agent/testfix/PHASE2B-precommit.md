# PHASE2B — dbt Accumulated-Learning Loop Phase 2b Precommit

## Mechanism question
Does adding one diff-context feature let the learner use episode information that
Phase 2a's structural-only feature space could not represent?

Phase 2a result: YELLOW (MRR static=0.740, freq=0.821, learned=0.833)
Root cause of ceiling: d_c04/d_c05 share ctx_key (customers, {clv}), same hist_freq
at convergence → learner oscillates, net gain ≈ 0. d001 stuck at rank 2.

## The added feature: diff_kind_match
Single binary feature per candidate:

    diff_kind_match = 1 if
        (episode is agg mutation AND cand.is_agg)
        OR (episode is join mutation AND cand.is_join)
      else 0

Episode diff_kind (agg/join/other) is derivable from the diff hunk — whether the
changed line is inside a SUM/MIN/MAX/COUNT call or a JOIN ON clause.
In simulation: derived from the changed expression's type (is_agg, is_join),
which is fixed per case_id and does not depend on which candidate is chosen.

Classification per case_id:
  d_c01, d_c02, d_c03, d_c04, d_o01, d_o02: is_agg=True  (agg mutation)
  d_c05, d001, d002, d003:                   is_join=True (join mutation)
  d_s01:                                     is_other     (arithmetic)

## Why this breaks the d_c04/d_c05 ceiling
Phase 2a: for d_c04 and d_c05, every candidate had the same feature vector
(both mutations share ctx_key → same hist_freq; same structural features).
The learner had NO dimension to tell them apart.

Phase 2b:
- d_c04 (agg mutation): e_sum gets diff_kind_match=1; e_inner_join/e_cp_join get 0.
- d_c05 (join mutation): e_inner_join/e_cp_join get diff_kind_match=1; e_sum gets 0.

Feature vectors are now DISTINCT across the two episodes.
The learner can learn: "when diff_kind_match=1 AND is_agg=True → correct in d_c04 context"
and: "when diff_kind_match=1 AND is_join=True → correct in d_c05 context."

## What remains ambiguous after Phase 2b
d001 vs d003: both are join mutations → both have diff_kind_match=1 for ALL join
candidates (e_co_join and e_cp_join both get diff_kind_match=1). Structural features
and hist_freq are also tied. Static tie-break (e_co_join before e_cp_join) means
d001 (true=e_cp_join) stays at rank 2. This cannot be resolved without knowing
WHICH join clause changed (a level more specific than "is it a join mutation").

## Registered prediction: YELLOW

Reasoning:
- diff_kind_match resolves d_c04/d_c05 oscillation: both should converge to rank 1
  from round ~2 onward (need 1+ episode to learn the feature weight).
  Expected improvement over Phase 2a: ~+1.0 to +1.5 RR units on d_c04/d_c05.
- d001 remains at rank 2 (Phase 2a and frequency both give rank 2 here).
- Expected Phase 2b learned MRR: ~0.855–0.875
- Expected frequency MRR: ~0.821 (unchanged, does not use diff features)
- δ(2b_learned − freq): ~+0.034 to +0.054 → borderline YELLOW/GREEN

GREEN would require diff_kind_match to also help d001/d002/d003 joint disambiguation
beyond what hist_freq already provides. This is possible if diff_kind_match enables
earlier convergence on the join explosion cases (round 1 already ranks joins above
aggregates before hist_freq kicks in). If this early-round benefit materializes,
δ(2b_learned − freq) could exceed 0.05.

**Best case: borderline GREEN (+0.05–0.06 over freq).**
**Expected case: YELLOW (+0.03–0.04 over freq).**

## Verdict bands (same as Phase 2a)
| Band   | Condition                                                              |
|--------|------------------------------------------------------------------------|
| GREEN  | MRR_2b_learned > MRR_freq + 0.05 AND > MRR_static + 0.05             |
| YELLOW | MRR_2b_learned > MRR_static + 0.05 AND ≤ MRR_freq + 0.05             |
| RED    | MRR_2b_learned ≤ MRR_static + 0.05                                    |

Additional comparison: Phase 2b vs Phase 2a learned (+0.05 threshold).
If MRR_2b_learned ≤ MRR_2a_learned + 0.05: diff_kind_match adds nothing
beyond what Phase 2a's hist_freq already captured.

## Core claim being tested
Self-verified experience only becomes learnable when the episode representation
includes the right causal/diff context. Phase 2b tests whether one diff-context
feature is sufficient to break the representation ceiling measured in Phase 2a.
