# TRANSFER RUNGS 4-6 precommit — finishing the frontier map (density-first)

Registered: 2026-06-05, BEFORE any measurement. The map's instrument is the
density pair (native catch rate vs mined catch rate on mechanical mutations);
repair-loop runs are NOT in scope for these rungs (safety already held at
rungs 1-3; the law under test is the user-stated candidate:
"native validation checks STRUCTURE; mined references check INTENT").

## Rung 4 — Terraform

Target: a real public config restricted to offline-able providers
(random/local/null/tls/time); fallback if none clones cleanly: report
PARTIAL with `terraform validate`-only native density and mined oracle
marked infeasible-offline (cloud-credentialed plan).
Native oracle: `terraform validate` (+ init success).
Mined oracle: `terraform plan` output diff vs parent plan (deterministic
with these providers; -refresh=false).
Mutations: operator/value flips in .tf (==<->!=, +1 on counts, string value
swaps, `true<->false`, resource attribute swaps). Cap 30.

## Rung 5 — GitHub Actions workflows

Target: podinfo's real .github/workflows (already cloned).
Native oracle: `check-jsonschema --builtin-schema vendor.github-workflows`
(the schemastore schema — the ecosystem's static gate).
Mined oracle: SEMANTIC PROJECTION diff vs parent — jobs, needs-DAG, matrix
expansion products, step (uses/run) sequences, triggers — computed by a
deterministic projector we implement. HONESTY NOTE (registered): unlike helm
template / dbt run, the ecosystem ships no renderer; the projector is part
of the mining toolkit, so rung 5 measures "native vs MINEABLE", which is
exactly the thesis but must be labeled as such.
Mutations: trigger event swaps (push<->pull_request), branch renames,
needs edge removal, matrix value edits, runs-on flips, secret name typos,
`if:` condition flips. Cap 30.

## Rung 6 — Structured documents (OpenAPI 3 spec)

Target: a real public OpenAPI spec (OAI petstore or equivalent).
Native oracle: `openapi-spec-validator` (offline pip).
Mined oracle: dereferenced/canonicalized spec diff vs parent (deterministic
resolution + sorted canonical dump).
Mutations: type flips (string<->integer), required-field add/remove,
enum value swaps, HTTP status 200<->201, format flips, path-parameter
renames. Cap 30.

## Outputs per rung (all reported, no cherry-picking)

native catch rate; mined catch rate; only-mined; only-native; silent
(neither — semantically inert on this artifact); the running gradient table.

## The law under test (user-stated, falsifiable form)

"The company lives where native validation checks structure but mined
references check intent" — operationalized: down the ladder, native density
stays low/flat (structural checks only) while mined density stays near-total
(intent visible in deterministic projections). FALSIFIER: any rung where
native >= mined breaks the monotone gradient; any rung with a large
"silent" residual shows intent NOT mineable there — the frontier's edge.

## Stopping rule

One density pass per rung. No operator changes after results. Apparatus
fixes logged. All three rungs go in the guide regardless of outcome.
