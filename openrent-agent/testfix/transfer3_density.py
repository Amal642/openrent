"""
Transfer rung 3: mechanical YAML mutations + oracle density (Helm/podinfo).

native_kill = helm lint --strict fails OR helm template fails OR
              kubernetes-validate rejects any rendered doc
diff_catch  = rendered output != parent rendering (text equality; helm
              rendering is deterministic)

Usage: python -m testfix.transfer3_density
Outputs: testfix/transfer3_density.json, testfix/transfer3_mutations.json
         (the native-scoreable subset for the loop)
"""

import json
import random
import re
import subprocess
from pathlib import Path

CHART = Path("D:/transfer-rung1/podinfo/charts/podinfo")
OUT_D = Path(__file__).resolve().parent / "transfer3_density.json"
OUT_M = Path(__file__).resolve().parent / "transfer3_mutations.json"

OPERATORS = [
    (r"\btrue\b", "false", "true_to_false"),
    (r"\bfalse\b", "true", "false_to_true"),
    (r"\bAlways\b", "IfNotPresent", "pullpolicy_flip"),
    (r"\bIfNotPresent\b", "Always", "pullpolicy_flip2"),
    (r"\bClusterIP\b", "NodePort", "svctype_flip"),
    (r"\bTCP\b", "UDP", "proto_flip"),
    (r"\bRollingUpdate\b", "Recreate", "strategy_flip"),
    (r"\breadiness\b", "liveness", "probe_swap"),
    (r"\bmemory\b", "cpu", "mem_to_cpu"),
]
PORT_LINE = re.compile(r"^(\s*[\w.-]*[Pp]ort:\s*)(\d+)(\s*)$")
REPLICA_LINE = re.compile(r"^(\s*(?:replicas|minReplicas|maxReplicas):\s*)(\d+)(\s*)$")


def _render() -> str | None:
    r = subprocess.run(["helm", "template", "."], capture_output=True,
                       text=True, cwd=CHART, timeout=120, shell=True)
    return r.stdout if r.returncode == 0 else None


def _native_green() -> bool:
    lint = subprocess.run(["helm", "lint", "--strict", "."], capture_output=True,
                          text=True, cwd=CHART, timeout=120, shell=True)
    if lint.returncode != 0:
        return False
    rendered = _render()
    if rendered is None:
        return False
    import kubernetes_validate, yaml
    try:
        for d in yaml.safe_load_all(rendered):
            if d:
                kubernetes_validate.validate(d, "1.31", strict=False)
    except Exception:
        return False
    return True


def main() -> None:
    random.seed(11)
    files = sorted(CHART.glob("templates/*.yaml")) + [CHART / "values.yaml"]
    parents = {f: f.read_text(encoding="utf-8") for f in files}

    assert _native_green(), "parent must be native-green"
    parent_render = _render()
    assert parent_render

    candidates = []
    for f in files:
        for i, line in enumerate(parents[f].splitlines(keepends=True)):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            for pat, rep, label in OPERATORS:
                if re.search(pat, line):
                    candidates.append((f, i, pat, rep, label))
            m = PORT_LINE.match(line.rstrip("\n"))
            if m:
                candidates.append((f, i, None, str(int(m.group(2)) + 1), "port_plus1"))
            m = REPLICA_LINE.match(line.rstrip("\n"))
            if m:
                candidates.append((f, i, None, str(int(m.group(2)) + 1), "replica_plus1"))
    random.shuffle(candidates)
    print(f"{len(candidates)} candidates across {len(files)} files")

    rows, valid = [], []
    for f, i, pat, rep, label in candidates[:40]:
        rel = str(f.relative_to(CHART)).replace("\\", "/")
        src = parents[f]
        lines = src.splitlines(keepends=True)
        if pat is None:  # numeric +1
            m = (PORT_LINE if label == "port_plus1" else REPLICA_LINE).match(
                lines[i].rstrip("\n"))
            mutated = f"{m.group(1)}{rep}{m.group(3)}\n"
        else:
            mutated = re.sub(pat, rep, lines[i], count=1)
        if mutated == lines[i]:
            continue
        new = lines.copy()
        new[i] = mutated
        f.write_text("".join(new), encoding="utf-8")
        try:
            native_kill = not _native_green()
            r2 = _render()
            diff_catch = True if r2 is None else (r2 != parent_render)
        finally:
            f.write_text(src, encoding="utf-8")
        rows.append({"file": rel, "lineno": i + 1, "operator": label,
                     "native_kill": native_kill, "diff_catch": diff_catch})
        print(f"  {rel} L{i+1} {label}: native={native_kill} diff={diff_catch}")
        if native_kill:
            valid.append({"case_id": f"k{len(valid)+1:03d}", "file": rel,
                          "lineno": i + 1, "operator": label,
                          "original_line": lines[i], "mutated_line": mutated})

    n = len(rows)
    nk = sum(r["native_kill"] for r in rows)
    dc = sum(r["diff_catch"] for r in rows)
    only_diff = sum(r["diff_catch"] and not r["native_kill"] for r in rows)
    only_nat = sum(r["native_kill"] and not r["diff_catch"] for r in rows)
    neither = sum(not r["native_kill"] and not r["diff_catch"] for r in rows)
    print("\n" + "=" * 60)
    print(f"ORACLE DENSITY (helm/k8s)  n={n}")
    print(f"  native kills : {nk}/{n}")
    print(f"  mined catches: {dc}/{n}")
    print(f"  only-mined: {only_diff}  only-native: {only_nat}  neither: {neither}")
    OUT_D.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    OUT_M.write_text(json.dumps(valid, indent=2), encoding="utf-8")
    print(f"native-scoreable loop set: {len(valid)} -> {OUT_M}")


if __name__ == "__main__":
    main()
