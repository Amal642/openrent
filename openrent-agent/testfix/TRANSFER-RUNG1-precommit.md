# TRANSFER RUNG 1 precommit — hardened loop on a foreign OSS repo

Registered: 2026-06-05, BEFORE mutation generation or any loop run.

## Question

Is this a portable self-verifying repair loop, or an OpenRent-specific demo?

## Target

`python-tabulate` (github.com/astanin/python-tabulate, shallow clone @ HEAD,
D:/transfer-rung1/python-tabulate). Chosen for: pytest suite (356 passed,
deterministic, ~7s), single package, EXTREME cross-function structure — 58
private helpers funneling into essentially one public entry (`tabulate`).
This is a HARDER cross-function regime than OpenRent (5-10 helpers/entry).

## No-tuning declaration (hard)

The pipeline is ported, not tuned: same stages (spec extraction E-code ->
test generation -> commit-diff filter -> detection -> learned localization ->
repair top-2+entry -> G1-G3 guards -> differential-vs-parent -> determinism
screen -> suite verification), same prompts modulo two NECESSARY
de-OpenRent-izations (logged): the status-constants prompt section is dropped
(no analog), and the corpus prompt's rental-domain examples are removed (the
generator is parent-source-conditioned, which carries the domain). Same
thresholds everywhere (top-10 embedding pool, top-2+entry repair, <=20
corpus inputs, >=5 stable inputs, 3-6 tests/entry). Localizer weights are
trained on the 20 OpenRent episodes (localizer_training.jsonl) and applied
UNCHANGED — weight transfer is part of what is being tested; per OPEN-53's
"transfer lives in FORM," the features are generic and the weights are
expected to carry or fail visibly.

## Mutations (mechanical, no hand-authoring)

AST-based operator mutations on top-level functions of tabulate/__init__.py:
comparison swaps (== <-> !=, < <-> <=, > <-> >=), and/or swap,
slice direction ([:n] <-> [-n:]), startswith<->endswith, lstrip<->rstrip,
lower<->upper, min<->max, `is None` <-> `is not None`, integer off-by-one in
subscripts. Validity filter (loop never sees it): repo suite PASSES on parent
and FAILS on mutant. Sampling: <=2 mutations per function, target n>=20.
Ground truth per case (scoring only, never shown to the loop): loop claims
SUCCESS and the repo's own full suite passes on the repaired code.

## Measurements (all required)

detection rate; localization rate (true mutated fn in top-3 / in attempts);
repair success; ground-truth success; false successes; false rejections
(diff-rejected attempts where repo suite would have passed); determinism-
screen exclusions; comparison row vs OpenRent CTRL-GDS (7/20 = 35%, 0 FP).

## Precommitted bands (n >= 20 mechanical mutations)

- GREEN:  >= 25% ground-truth success AND 0 false successes
- YELLOW: >= 10% success with 0 false successes, OR >= 25% with <= 1 false success
- RED:    < 10% success OR > 1 false success

## Stopping rule

One loop run on the validated mutation set. No prompt/threshold changes after
the first run. Apparatus fixes (crashes, state-restore) logged and re-run
allowed. Whatever the color, it goes in the guide with the full funnel table.

## RUNG 1b amendment (registered after the rung-1 RED, BEFORE any 1b run)

Rung 1 verdict was RED-capability / GREEN-safety with three named capacity
gaps. 1b fixes EXACTLY those three; everything else frozen (same mutations,
same bands, same corpus cache, same localizer weights, same thresholds):

1. GRAPH: call-graph edges also include first-class function REFERENCES
   (ast.Name in any expression context matching a module function), not just
   ast.Call — fixes the 5 no_entry_points (TableFormat-style dispatch).
2. DETECTION SCALING: suite budget scales with the entry's direct-helper
   surface — when an entry has >8 helpers, the surface is sharded into groups
   of <=6 helpers; spec extraction + test generation run per shard (entry
   source + that shard's helpers as evidence); survivor suites merged.
   Shards capped at 12 per entry. Same 3-6 tests per generation call.
3. LOCATE-THEN-PATCH: repair returns a SEARCH/REPLACE block instead of a
   whole function. The SEARCH text must occur exactly once inside the
   candidate function's current source; the patch is spliced into the
   function and the result passes the same G1-G3 guards (def-name preserved
   by construction; AST diff confinement unchanged) + differential + screen.

Suite cache is invalidated (sharding changes suites); corpus cache kept.
Bands unchanged: GREEN >= 25% GT + 0 FP; YELLOW >= 10% + 0 FP or >= 25% +
<= 1 FP; RED otherwise.

Scope caveat (registered): these fixes were DERIVED from tabulate's funnel.
A 1b GREEN therefore proves "architecture + per-regime capacity engineering"
transfers; the unfitted-transfer claim requires rung 1c — a third repo, fixes
frozen, one run — before "the architecture transfers" is stated plainly.
OpenRent-baseline comparability caveat: locate-then-patch changes the repair
stage; the OpenRent 35% reference used whole-function rewrite.
