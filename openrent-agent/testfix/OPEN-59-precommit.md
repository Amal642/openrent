# OPEN-59 precommit — eligibility-style credit assignment over composed-loop episodes

Registered: 2026-06-05, BEFORE any learning run. Composes the two arcs: the
OPEN-58 loop (this branch) + the cofounder's OPEN-57 regime law (eligibility
traces load-bearing ONLY under long-horizon sparse non-structure-recoverable
reward; all replay prioritization/protection decorative on structural
substrates).

## Question

Can the composed loop get better at closing itself from sparse pass/fail
outcomes alone — no is_true_B labels, no human tests?

## Registered prediction (from the cofounder's regime law, applied prospectively)

The loop's decision horizon is SHORT (~3: detection suite -> localizer ranking
-> repair-candidate order -> verify) and its intermediate signals are DENSE and
structure-rich. The regime law therefore predicts: eligibility-weighted credit
~ uniform credit (decorative), and a simple success-frequency lookup captures
most of the available gain. **This experiment is a prospective test of the
regime law itself**: GREEN would falsify the law's boundary; RED confirms it
out-of-domain.

## Design

**Phase A — episodes (no learning).** Enrich loop logging (attempts list,
per-stage decisions; logging only, zero behavior change). Run the unchanged
loop k=3 more times over the 20 seeds (temperature variance makes episodes
distinct) -> ~60 new + 20 existing = ~80 train episodes.

**Phase B — credit fitting (three arms, function-level priors only).**
From train episodes, each arm produces prior(fn) used at inference:
- ELIG: eligibility-decayed credit, lambda^d by stage distance from verify;
  success -> +, failure -> −.
- UNIF: same +/- credit, no decay (uniform across stages).
- FREQ: success-count lookup only (no negatives, no decay).
FORBIDDEN (per regime-1): replay prioritization, memory protection, importance
weighting of episodes.

**Phase C — evaluation (counterfactual loop runs, not log replay).**
Priors injected into (i) localizer candidate ordering (score' = learned_score
+ beta * prior), (ii) repair-attempt order. One full loop run per arm on the
20 seeds. Baseline = run #2 (beta=0, no learning).
Split-reporting: cases whose episodes were in training (seen; experience
reuse) vs leave-out cases excluded from training (held-out; generalization).

## Bands (amended from draft — anti-strawman clause added)

On ground-truth success rate (human test, scoring only), vs the STRONGEST of
{uniform accumulation, success-frequency}:
- GREEN:  ELIG >= strongest baseline + 15pp
- YELLOW: +5 to +14pp
- RED:    < +5pp or harmful
A GREEN vs uniform that ties FREQ is reported as DECORATIVE (OPEN-18A).

## Power caveat (logged)

n=20 eval cases cannot statistically resolve 15pp (3 cases). Reported as
exploratory with per-case tables; claims stated at the band level only if the
gap is unambiguous, otherwise INSUFFICIENT_DATA verdict is allowed and honest.

## Held-out split (registered after Phase A, BEFORE any prior fitting or eval)

Held-out cases (excluded from prior training): cross_002, cross_008, cross_014,
cross_016, cross_017, cross_018 — stratified over Phase-A outcome profiles:
never-succeed (002, 018), always-succeed (014), flippers (008, 016, 017).
cross_002's broken function (landlord_messages) appears in no other case ->
pure generalization probe.

Phase-A observation (registered): per-run success is stable at 7/20 = 35%
(r2/r3/r4 identical rate), but only 3 cases always succeed, 7 never succeed,
10 FLIP between runs; the 3-run union of successes is 12/20 = 60%. The
addressable population for decision-ordering priors is the 10 flippers.

## Stopping rule

One evaluation run per arm. No tuning of lambda/beta after seeing eval results
(lambda=0.5, beta=1.0 fixed now; priors z-normalized before blending).
Apparatus fixes logged. If ELIG is RED and FREQ captures the gain: write the
regime-law confirmation to the guide and STOP the credit-assignment thread.

## Apparatus fix log

1. (2026-06-05, pre-eval) First CTRL eval run collapsed to 1/20 with 18
   repair_failed. RCA: `_split_test_functions` (line-regex, 5-line decorator
   lookahead) silently dropped multi-line `@pytest.mark.parametrize` decorators
   when reassembling survivor suites -> 'fixture not found' collection error ->
   verification failed for every repair touching an affected suite. Also let
   non-test helper defs land inside a preceding test's block (helpers vanished
   when that test was filtered). Fixed with an AST-based splitter (decorators
   extracted via decorator_list; header = all non-test code). Poisoned suite
   cache + invalid CTRL results deleted; CTRL re-run with the fix.
   NOTE: the same latent bug was present in ALL OPEN-58 runs and OPEN-55b/56
   filter analyses (fired by sampling luck per generated suite) — their
   published numbers are FLOORS, not unbiased estimates; flagged in the guide.
2. (Same time) A killed eval process left `app/ai/stages.py` mutated on disk
   (kill bypasses `finally`); restored from git, all 20 human tests re-verified
   green. Operational note: never hard-kill a loop run mid-case.
