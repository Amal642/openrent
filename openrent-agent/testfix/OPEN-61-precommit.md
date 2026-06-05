# OPEN-61 precommit — differential-vs-parent verification

Registered: 2026-06-05, BEFORE any run. The immediate unblocker from OPEN-60's
gate failure: strengthen the oracle enough to kill the coverage-gap FP class.

## Mechanism

A regression repair must behaviorally match the PARENT on the affected entry
points — not merely satisfy the generated suite. The parent IS the expected
value, so the differential oracle needs only INPUTS, never expected outputs:
the spec-gap that produced coverage-gap FPs cannot recur by construction.

Per entry function: an LLM-generated input corpus (cached, label-free; inputs
are Python literal expressions, datetime available in eval namespace).
At case start (parent on disk): compute parent outputs for all affected
entries' corpora. After a candidate repair passes suite verification: compute
repaired outputs, compare reprs (exceptions count as outputs). ANY divergence
-> repair rejected (D-rejection), loop tries the next candidate.

Scoring-only addition: at each D-rejection, the held-out human test is run
against the rejected state and logged (never shown to the loop) — this
measures oracle PRECISION (false-rejection rate) as well as recall.

## Arm

CTRL-GD = guards (G1-G3) + differential, beta=0, same suite cache
(open59_suites.json), same 20 seeds. Compared against CTRL-G (OPEN-60:
7/20 ground truth, 2/20 FP) and CTRL (OPEN-59: 8/20, 2/20 FP).

## Precommitted bands

- PASS:  coverage-gap FPs = 0/20 AND ground-truth successes >= CTRL-G - 1
         (the oracle must kill FPs WITHOUT rejecting legitimate repairs).
- PARTIAL: FPs = 0 but ground-truth drops by >= 2 (over-strict oracle —
         report false-rejection log; the fix is corpus quality, not concept).
- FAIL:  any coverage-gap FP survives differential verification (the class
         is not input-reachable at this corpus size — report and redesign).

Unblock rule (per program sequencing): PASS -> OPEN-60's FP gate is re-tested
and met -> transfer phase (and any future learning legs) unblocked.

## Honest scope

Differential-vs-parent is valid for REGRESSION repair (the parent is the
behavioral spec). It does NOT extend to forward fixes (intended behavior
changes) — there the diff must be confined to the intended change, which is a
harder oracle. Our seeds are pure regressions; the claim is scoped to that.

## Stopping rule

One run. Corpus size fixed at <= 20 inputs/entry before the run. No corpus
regeneration after seeing results. Apparatus fixes logged.

## OPEN-61b amendment — determinism screening (registered BEFORE the 61b run)

Screen (label-free): when computing parent outputs, run the corpus TWICE on
the parent. Keep only inputs whose two parent outputs are identical; if fewer
than 5 stable inputs remain for a function, exclude that function from the
differential entirely (its suite verdict stands alone). Thresholds fixed now.

Arm: CTRL-GDS = guards + differential + screen, same suite cache, one run.

Bands (same as OPEN-61): PASS = FP 0/20 AND ground truth >= CTRL-G - 1 (>= 6;
projection from the OPEN-61 false-rejection log is 8/20). PARTIAL = FP 0 but
GT <= 5. FAIL = any FP returns.

## Apparatus fix log (pre-eval, from the cross_012 smoke test)

1. Corpus generator produced wrong-TYPE inputs (message lists for a
   string-typed parameter) — zero discriminative power. Fix: the generator now
   sees the PARENT function source (legitimate — the parent is the trusted
   reference the whole oracle is built on) and is instructed to cover every
   branch/table entry. Regenerated corpus includes all alias-table entries.
2. Differential runner subprocess failed with ModuleNotFoundError (script in
   testfix/ put its own dir on sys.path, not the project root); silent abstain
   masked the failure. Fix: sys.path.insert(0, os.getcwd()).
   Smoke verification: cross_012's coverage-gap repair now REJECTED on the
   'friendly_couple' divergence; human-test-at-rejection = False (rejection
   correct).
