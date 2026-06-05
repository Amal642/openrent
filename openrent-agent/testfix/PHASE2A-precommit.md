# PHASE2A — dbt Accumulated-Learning Loop Precommit

## Mechanism question
Can self-verified repair episodes resolve structural ambiguity in dbt expression
localization?  Not: "does MRR go up?"

## Registered prediction (before running)
**YELLOW is the most likely outcome.**  The mutation space is small and structurally
fixed; success-frequency is expected to saturate by round 2 (~22 episodes).
GREEN would require the learner to exploit episode content beyond marginal counts —
specifically, the `feeds_n_cols` or `line` features to distinguish the two outer-join
candidates (d001/d003).  Those features carry equal-and-opposite signal across the
ambiguous pair, so logistic regression is expected to wash them out.
A transient GREEN at early checkpoints (≤20 episodes) is plausible if feature
generalization gives the learner a zero-shot edge over frequency on first-seen
expr_ids; it is expected to converge to YELLOW by episode 44.

## Verdict bands (evaluated at final checkpoint, episode 44)
| Band   | Condition                                                        | Interpretation                                  |
|--------|------------------------------------------------------------------|-------------------------------------------------|
| GREEN  | MRR_learned > MRR_freq + 0.05  AND  MRR_learned > MRR_static + 0.05 | Episodes encode reusable information beyond structure |
| YELLOW | MRR_learned > MRR_static + 0.05  AND  MRR_learned <= MRR_freq + 0.05 | Caching works; reuse beyond caching does not    |
| RED    | MRR_learned <= MRR_static + 0.05                                 | Structure is sufficient; episodes add nothing   |

**Critical rule:** do not claim GREEN if the learner only matches success-frequency.
Matching frequency = caching = YELLOW.

## Design
- Episodes: 4 rounds × 11 detectable mutations = 44 episodes
- Round ordering: shuffled per round (seed 42, 43, 44, 45)
- Temporal split: train on episodes 1..t-1, evaluate on t (no future leakage)
- Methods: static (line-order priority), frequency (marginal hit-rate), learned (logistic regression)
- Checkpoints: MRR reported at episodes 10, 20, 30, 44
- Feature set (Phase 2a — structural only, NO diff-context):
  exact_match, superset_match, any_overlap, is_join, is_agg,
  feeds_n_cols_norm, n_diverged_norm, row_count_changed, single_col

## What this does and does not prove
**Proves (if GREEN):** the structural feature space encodes learnable signal beyond
frequency counting; accumulated episodes provide information not derivable from
the first exposure.
**Does not prove:** Phase 2b features (diff-context) are unnecessary (they may be
needed for a stable GREEN across future repos or larger DAGs).
**Does not prove:** repair quality improves — this study measures localization only.

## Phase 2b gate
Phase 2b (add one diff-context feature, re-run) is triggered only if 2a is YELLOW
or blocked by irreducible ambiguity.  2a must complete before 2b starts.
