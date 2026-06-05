# OPEN-60 precommit — verification robustness before learning

Registered: 2026-06-05, BEFORE any run. Sequencing rule under test (from
OPEN-59's mechanism finding): a loop must fix its verification before it earns
the right to learn from its own outcomes.

## Standing program rule (proposed; adopted if Leg 2 passes)

No learning from loop outcomes is permitted while the loop's observed
false-success rate exceeds 1/20 with deployable (label-free) guards on.
This is the program's "fix your reward model before RL."

## Leg 1 — amplification, quantified (reanalysis + 1 eval run)

OPEN-59 left two explanations entangled: (a) the credit stream was POISONED by
shadowing artifacts; (b) outcome-only credit is INHERENTLY too coarse at this
horizon. Isolate them:

- Refit ELIG priors on artifact-CLEANED episodes. Label-free cleaning rule
  (REACHABILITY): a success episode is flagged as artifact iff its
  repaired_fn is neither the detected entry function nor a transitive callee
  of it (static call graph) — repairing a function the failing entry cannot
  reach is structurally impossible as a legitimate fix (it can only "work"
  via shadowing or coincidence). Flagged successes are re-labeled failures
  for credit purposes. Uses episode logs + call graph only; no human labels,
  no true-B.
- Re-run ONE eval arm (cleaned-ELIG, beta=1.0, same suite cache
  open59_suites.json, same held-out exclusions).

Precommitted readings:
- dirty-ELIG (7/20, from OPEN-59) < cleaned-ELIG  => AMPLIFICATION CONFIRMED
  (verification noise poisons learning) -> proceed to Leg 2.
- cleaned-ELIG <= dirty-ELIG  => coarseness confirmed in strong form; learning
  harmful even with clean stream at this horizon -> Leg 2 still runs (guards
  are needed for transfer regardless) but the amplification claim is NOT made.
- cleaned-ELIG > CTRL (8/20) by >= +10pp would additionally REOPEN the
  credit-assignment thread (overriding OPEN-59's stop) — not expected.

## Leg 2 — deployable guards (mechanical hardening)

Guards (all label-free, all cheap):
  G1 def-name guard: repair output's top-level def name MUST match the
     candidate's function name; mismatch -> reject attempt, try next.
  G2 diff confinement: after applying a repair, the changed file's AST may
     differ from pre-repair ONLY inside the candidate function; else reject.
  G3 duplicate-def lint: no module may contain two defs of the same name
     after repair; else reject.

Run the full loop once with guards on (CTRL-G arm, beta=0, same suite cache).

Precommitted gate (two-sided, honesty clause):
  (a) lab-measured false successes (vs held-out human tests) <= 1/20, AND
  (b) every lab-measured FP that occurred in CTRL (OPEN-59 table: 2/20) is of
      a type G1-G3 would catch — i.e., the guards' rejections account for the
      known artifact class. The deployable claim is "guards reduce FP," never
      "we measured FP in production."
  PASS -> standing rule adopted; proceed to Leg 3.
  FAIL (an FP class survives G1-G3) -> name the surviving class, STOP, redesign.

## Leg 3 — retry-before-learning (the sequencing claim)

Arms (both on hardened loop, same suite cache):
  R: retry budget — repair attempts per candidate 1 -> 2, and on full-case
     failure one whole-case re-roll (fresh localization + repair). No priors.
  P: cleaned priors (best variant from Leg 1), beta=1.0, no retries.

Phase-A pricing (registered): per-run success 35%, 3-run union 60% — retries
harvest stochasticity directly.

Precommitted readings (vs hardened CTRL-G baseline):
- R >= CTRL-G + 10pp AND P <= CTRL-G + 5pp  => sequencing law CONFIRMED
  (search before learning at short horizon).
- P > R                                      => sequencing law FALSIFIED —
  report prominently; reopens credit thread.
- both flat                                  => stochasticity not harvestable
  by either; report as ceiling finding.

## Budget / scope

gpt-4.1-mini throughout; same 20 seeds; same suite cache (open59_suites.json)
for every arm so detection is held constant. Leg 1: 1 refit + 1 run. Leg 2:
1 run. Leg 3: 2 runs. Total ~4 loop runs. n=20 resolution caveat carries over
from OPEN-59 (bands are coarse; INSUFFICIENT_DATA is an allowed verdict).

## Stopping rule

No tuning after results. Apparatus fixes logged. Gate to OPEN-61/transfer:
Legs 1-3 complete and written to the guide, whatever their colors.
