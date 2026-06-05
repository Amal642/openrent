# TRANSFER RUNG 2 precommit — the loop on a NON-CODE artifact class (dbt SQL)

Registered: 2026-06-05, BEFORE mutation generation or any loop run.

## Question

Is this a software-repair loop, or an oracle-mining loop? Rung 2 keeps the
loop FORM (trusted-reference differential oracle -> detect -> localize ->
locate-then-patch -> verify -> held-out ground truth) and swaps the artifact
class: SQL transformation models instead of Python functions.

## Target

`jaffle_shop_duckdb` @ HEAD (D:/transfer-rung1/jaffle_shop_duckdb).
5 SQL models (3 staging views, 2 marts), 3 seed CSVs, 20 native dbt data
tests, `dbt build` green in ~5s, fully offline (DuckDB).

## Stage mapping (the FORM, re-instantiated for SQL — logged, not tuned)

- Trusted reference: parent commit's model OUTPUTS — after `dbt run` on
  parent, every model's full result table snapshotted as a SORTED row
  multiset (sorting = the determinism canonicalization; SQL row order is
  not guaranteed, values on fixed seeds are).
- Detection: `dbt run` on mutant (NO tests — `dbt test` results are the
  HELD-OUT ground truth and never shown to the loop); model tables diffed
  against parent snapshots.
- Localization: first divergent model in DAG topological order (the
  upstream-most divergence is the cause; downstream divergence is cascade).
  Structural — no learned weights (the OpenRent features are Python-specific;
  porting them would be tuning).
- Repair: locate-then-patch (SEARCH/REPLACE) on the localized model's SQL,
  prompt context = mutant SQL + divergence sample (<=5 differing rows,
  expected-vs-got). Patch must apply exactly once. One attempt per candidate;
  candidates = [first divergent model, its direct upstream models] capped 3.
- Verification: `dbt run` + ALL model tables match parent snapshots exactly.
- Ground truth (held out, scoring only): `dbt build` green (includes the 20
  native tests).
- False success: loop claims success, `dbt build` fails.

## Mutations (mechanical)

Line-based operator flips on models/**/*.sql (raw text, jinja-safe lines):
sum<->count, min<->max, left join<->inner join, = <-> != , /100 <-> *100,
else 0 <-> else 1, asc<->desc. Validity (loop never sees it): parent
`dbt build` green AND mutant `dbt build` has >=1 failure. <=3 per model.
Target n >= 15; accept n >= 10 with an explicit low-n caveat (the native
test surface may be insensitive to many value-level mutations — itself a
finding about oracle density in this artifact class, reported either way).

## Bands (mirroring rung 1)

- GREEN:  >= 25% ground-truth success AND 0 false successes
- YELLOW: >= 10% + 0 FP, or >= 25% + <= 1 FP
- RED:    < 10% or > 1 FP

## Stopping rule

One loop run on the validated set. No prompt/threshold changes after the run.
Apparatus fixes logged. Full funnel table to the guide whatever the color.
