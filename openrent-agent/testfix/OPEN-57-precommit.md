# OPEN-57 precommit — the composed loop, end-to-end, no oracle labels

Registered: 2026-06-05, BEFORE any run. OPEN-56 proved the components; OPEN-57
tests the system.

## Pipeline under test (per case)

    mutated codebase (+ parent codebase, git-available)
      -> derive affected public entry points (reverse call graph from the diff)
      -> extract specs from PARENT code (E-code, the OPEN-56 winner)
      -> generate tests from specs (never sees any implementation)
      -> filter test functions on parent (commit-diff filter)
      -> run survivors on mutant            [DETECTION]
      -> failing test -> learned localizer  [LOCALIZATION]
      -> repair top-ranked candidate        [REPAIR]
      -> loop verification: full survivor suite passes on repaired code
      -> SUCCESS claimed or not

## No-oracle rules (hard)

The loop receives NO: entry-function labels, true-B labels, human-written tests,
seed metadata, mutation snippets. It receives ONLY the parent codebase, the
mutated codebase, and what it can derive (the diff, call graphs, indexes).
The held-out human test (`test_arm_a_cross_function.py::<case>`) is used ONLY
for scoring, never shown to any stage.

Derivations that ARE allowed (operationally free in a commit workflow):
- the diff (parent vs mutant) -> changed function
- reverse transitive call graph -> public entry points affected (cap 4,
  nearest-first; a changed PUBLIC function is its own entry point at distance 0)
- localizer training data from PAST episodes (`localizer_training.jsonl`,
  built from prior human-test failures) minus the current case — accumulated
  experience; note this also tests transfer from human-test queries to
  GENERATED-test queries.

## Stage budgets (fixed now)

- Spec extraction: E-code only, 1 call per entry function, cached across cases
  (a repo-level regression suite is built once — operationally honest).
- Test generation: 1 call per entry function, cached. gpt-4.1-mini throughout.
- Localizer: top-2 candidates tried, in rank order.
- Repair: 1 attempt per candidate (B3e stage-2 prompt).
- Loop verification: ALL surviving generated tests for the case's entry points
  must pass on the repaired code.

## Metrics

- **Headline: ground-truth end-to-end success** = loop claims SUCCESS **and**
  the held-out human test passes on the repaired code. n = 20.
- **GREEN >= 8/20 (40%) | YELLOW 5-7 (25-39%) | RED <= 4 (<25%)**
- Required reporting: stage-attrition table (died at: no-entry-points /
  detection / localization+repair / loop-verification / ground-truth);
  false-success count (loop claims SUCCESS, human test still fails) — reported
  separately, NOT counted in the headline; per-case table.

## Registered predictions

- P1: detection ~ 14/20 (E-code filtered kill was 70%).
- P2: end-to-end ground-truth success 7–10/20 (stage rates roughly multiply).
- P3: false-success <= 2 (loop verification on the full survivor suite is a
  strong internal check).
- P4: the embedding-hostile name-hidden cases (cross_001, cross_009, cross_011)
  die at localization or earlier.

## Stopping rule

One run. No prompt tuning after seeing results. Apparatus bugs (crashes,
state-restore failures) may be fixed and the affected cases re-run; every such
fix is logged. Anything else ships as-is to the guide.

## Amendment log (registered BEFORE the full re-run)

Run #1 (2026-06-05) aborted at cross_012 after 11 cases. Two harness defects,
both fixed before run #2; run #1 partials are discarded as apparatus-invalid
and reported in the guide for transparency:

1. **Crash (apparatus):** a generated suite that fails at pytest COLLECTION
   (e.g. a module-level call raising under the mutant) produces returncode != 0
   with no per-test FAILED line; `next()` over failed tests raised
   StopIteration. Fix: fall back to (first test function, full pytest output)
   as the failing context.
2. **Composition defect (design-faithfulness):** `_build_pool` excludes the
   entry function from the candidate pool (inherited from OPEN-52, where B != A
   by construction). When the changed function is PUBLIC it is its own entry
   point, so repair could never select it — cases cross_002/003/006/007 were
   unreparable BY HARNESS CONSTRUCTION, contradicting the B3e design this loop
   composes ("entry-point or one of the candidates"). Fix: the repair stage
   tries [top-1, top-2, entry-function] (budget raised 2 -> 3 attempts,
   logged). This is composition-completion, not result-chasing: the defect was
   identified from run #1's attrition pattern, the fix registered here before
   run #2 produced any number.
