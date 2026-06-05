# TRANSFER RUNG 3 precommit — config/IaC (Helm chart, Kubernetes YAML)

Registered: 2026-06-05, BEFORE mutation generation or any run.

## Question

Does the oracle-density inversion repeat outside dbt? If the mined oracle
(rendered-manifest diff vs parent) again dominates the native oracle
(helm lint --strict + helm template success + kubernetes-validate offline
schema check), the cheap-oracle-frontier thesis strengthens; if native
dominates, the loop is decorative in this artifact class.

## Target

`podinfo` @ HEAD, chart at charts/podinfo (real, widely-deployed demo chart;
renders 5 manifests/206 lines; lint green; kubernetes-validate green on
parent). All offline (helm 3.18, kubernetes-validate pinned schemas 1.31).

## Protocol (density FIRST, loop second — per the rung-2 lesson)

1. Mechanical YAML mutations on templates/*.yaml + values.yaml:
   true<->false, port/replica integers +1, Always<->IfNotPresent,
   ClusterIP<->NodePort, TCP<->UDP, RollingUpdate<->Recreate,
   readinessProbe<->livenessProbe, memory<->cpu.
2. Density on ALL candidates (cap 40): native_kill (lint/template/validate)
   vs diff_catch (rendered output != parent rendering; helm output is
   deterministic so text comparison after render is the canonicalization).
3. Loop runs on the native-scoreable set (native_kill = held-out GT):
   detection = mined diff; localization = `# Source:` marker of the first
   divergent rendered doc (structural); repair = locate-then-patch on the
   localized file (mutant source + diff sample <=10 lines); verification =
   re-render matches parent exactly; GT = native stack green.
4. Safety reported separately: false successes (must be 0), false
   rejections diagnosed individually.

## Bands (loop, on native-scoreable n; low-n clause as rung 2)

GREEN >= 25% GT + 0 FP (n>=10); YELLOW >= 10% + 0 FP; RED otherwise;
n < 10 -> INSUFFICIENT_DATA for the band, density finding reported regardless.

## Registered predictions

P1: inversion REPEATS and is more extreme than dbt — schema validation
catches type/enum violations only; most value flips (ports, bools,
policies) render valid-but-different. Predicted native <= 25%, mined >= 85%.
P2: localization via Source markers >= 90% correct (rendering preserves
file provenance).

## Stopping rule

One density pass, one loop run. No operator/prompt changes after results.
Apparatus fixes logged.
