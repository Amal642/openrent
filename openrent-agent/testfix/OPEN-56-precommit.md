# OPEN-56 precommit — automated spec extraction for spec-conditioned test generation

Registered: 2026-06-05, BEFORE any extraction or generation run.
Builds on: OPEN-55 (impl-conditioned RED 4/20), OPEN-55b (hand-authored-spec GREEN
11/20 = 55% file-level, 15/20 = 75% with commit-diff filter).

## Question

Can automatically extracted behavioral specs replace the hand-authored specs of
OPEN-55b? If yes, the last unmeasured stage of the autonomous-improvement loop
(change → testgen → localize → repair → verify) is solved enough to close the loop.
If no, the system is human-spec-bottlenecked.

## Setup

Same 20 cross-function seeds (cross_001–020), same generation pipeline, same
validator, same model (gpt-4.1-mini, temperature 0.2, 1 attempt) as OPEN-55b.
The ONLY change: the spec body in the generation prompt is produced by an
extractor instead of a human.

### Operational legitimacy rule

Extraction runs on the ORIGINAL (parent-commit) codebase — never the mutant.
This mirrors the real workflow: specs are distilled from the trusted pre-change
state, then changes are tested against them. The test GENERATOR still never sees
any implementation (the OPEN-55 conformance trap applies to the generator, not
the extractor).

### Leakage rules (hard)

The extractor must NEVER see:
1. `tests/test_arm_a_*.py` (the held-out eval suites — they encode the exact
   behaviors under test),
2. anything in `testfix/` (harness, seeds, mutation list, results),
3. the hand-authored SPECS dict in `open55b_testgen.py`,
4. any mutated snippet.

Existing tests OTHER than the arm suites (e.g. `tests/test_stages.py`,
`tests/test_personas.py`) are legitimate extraction evidence.

### Arms (one extracted spec per entry function per arm; spec ≤ 350 words/function)

| arm | extractor evidence | note |
|---|---|---|
| S0  | signature only (no spec body) | ablation floor / control |
| E1  | existing test files only (arm suites excluded) | covers some entry functions well (test_stages.py), others not at all — per-function variance is part of the result |
| E2  | call examples / runtime traces only | capture (args, return) pairs by instrumenting entry functions while running the INCLUDED tests + a small driver script; extractor sees traces, not code |
| E3  | comments + docstrings only | predicted ≈ S0: the codebase has ZERO docstrings on all 10 entry functions — informative null arm |
| E4  | static usage only (AST-extracted call sites from `app/`, surrounding ±10 lines) | no test files, no implementation of the entry function itself |
| E-code | original implementation source (entry function + its helpers) | "distill the contract from trusted code" |
| E-all | everything above combined | **headline arm** |

## Claim lattice (per CLAUDE.md — three independently falsifiable levels, cheapest first)

### L1 Mechanism — clause-coverage audit (intrinsic, no generation noise)

Each of the 20 mutations violates exactly one spec clause (e.g. cross_001 → "only
the most recent 8 messages"; cross_020 → "direction key fallback"; cross_012 →
"alias table resolves friendly_couple → warm_casual"). Before any generation run,
build the 20-clause checklist from the seed list. Score each arm's extracted specs:
clause stated precisely / stated vaguely / absent.

- **Mechanism GREEN:** E-all states ≥ 12/20 clauses precisely (60%).
- Mechanism is unconfoundable: it cannot be rescued or killed by generation
  randomness, filter choices, or model arithmetic errors.

### L2 Component — extraction beats its own ablation

- **Component GREEN:** E-all file-level kill rate ≥ S0 + 15 pp.
- Rationale (OPEN-18A discipline): if signature-only generation matches extracted
  specs, the extraction is decorative — the model's prior knowledge of naming
  conventions was doing the work, not the spec content.

### L3 System — headline bands (the user-committed precommit)

File-level kill rate of **E-all** on n=20 (identical metric to OPEN-55b's 55%):

- **GREEN:  ≥ 40%**
- **YELLOW: 25–39%**
- **RED:    < 25%**

A System RED never retracts a Mechanism/Component GREEN — report every level.

## Required breakdown (report all, no cherry-picking)

1. Kill rate per arm: S0, E1, E2, E3, E4, E-code, E-all — file-level AND
   commit-diff-filtered (test-function granularity, `open55b_filter_analysis.py`
   protocol).
2. False-positive rate per arm, before and after the filter.
3. Per-entry-function clause coverage (mechanism table).
4. E1 split: entry functions WITH existing tests vs WITHOUT — measures how much
   extraction quality depends on prior test coverage.
5. Reference rows in every table: OPEN-55b hand-authored (55% / 75%) and
   OPEN-55 impl-conditioned (20%).

## Predictions (falsifiable, registered now)

- P1: E3 (comments/docstrings) ≈ S0 — there is nothing to extract. If E3 ≫ S0,
  the extractor is hallucinating specs from names, which the clause audit will show.
- P2: E-code is the strongest single source (the contract is fully present in the
  original implementation), but its specs may inherit implementation vagueness on
  pattern vocabularies (regex lists may be summarized, not enumerated).
- P3: E1 is strong ONLY for detect_stage / extract_viewing_datetime (the functions
  test_stages.py covers); near-S0 for the uncovered functions.
- P4: The kill/false-positive boundary continues to track clause precision
  (the OPEN-55b root-cause finding); spec gaps → hallucinated schema keys.

## What this does and does not test

- Tests: whether spec ACQUISITION can be automated at the precision test
  generation needs, on a 266-function production codebase, given trusted
  pre-change code and its artifacts.
- Does NOT test: spec discovery for unspecified/contested behavior, codebase-only
  latent-bug discovery (explicitly out of scope until OPEN-56 passes), or
  transfer to other codebases.

## Stopping rule

If E-all is RED and E-code is also RED, conclude human-spec-bottlenecked and STOP
the test-generation arc here (do not iterate extractor prompts more than once —
prompt-tuning the extractor to the 20 known mutations is §S3 goalpost-moving).
One prompt revision is allowed only if the failure is a mechanical defect
(truncation, format break), documented before re-running.
