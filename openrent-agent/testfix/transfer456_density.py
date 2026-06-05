"""
Transfer rungs 4-6: oracle-density measurements (density-first, no loops).

Rung 6: OpenAPI spec (petstore.yaml)
  native = openapi-spec-validator; mined = canonical dereferenced dump diff
Rung 5: GitHub Actions (podinfo/.github/workflows)
  native = check-jsonschema vendor.github-workflows
  mined  = deterministic semantic projection (triggers, jobs, needs-DAG,
           matrix products, step sequences) diff vs parent  [projector is
           part of the mining toolkit — labeled MINEABLE per precommit]
Rung 4: Terraform (learn-terraform-state, AWS) — PARTIAL
  native = terraform validate; mined = INFEASIBLE-OFFLINE (plan needs creds)

Usage: python -m testfix.transfer456_density [openapi|actions|terraform]
"""

import json
import random
import re
import subprocess
import sys
from pathlib import Path

BASE = Path("D:/transfer-rung1")
OUTDIR = Path(__file__).resolve().parent


# ── generic line-mutation engine ──────────────────────────────────────────────

def _measure(name: str, files: dict[Path, str], operators, native_fn, mined_ref_fn,
             cap: int = 30, seed: int = 13) -> None:
    random.seed(seed)
    parent_ref = mined_ref_fn()
    assert native_fn(), f"{name}: parent must be native-green"
    assert parent_ref is not None

    candidates = []
    for f, src in files.items():
        for i, line in enumerate(src.splitlines(keepends=True)):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            for pat, rep, label in operators:
                if re.search(pat, line):
                    candidates.append((f, i, pat, rep, label))
    random.shuffle(candidates)
    print(f"[{name}] {len(candidates)} candidates")

    rows = []
    for f, i, pat, rep, label in candidates[:cap]:
        src = files[f]
        lines = src.splitlines(keepends=True)
        mutated = re.sub(pat, rep, lines[i], count=1)
        if mutated == lines[i]:
            continue
        new = lines.copy()
        new[i] = mutated
        f.write_text("".join(new), encoding="utf-8")
        try:
            native_kill = not native_fn()
            ref = mined_ref_fn()
            diff_catch = True if ref is None else (ref != parent_ref)
        finally:
            f.write_text(src, encoding="utf-8")
        rows.append({"file": f.name, "lineno": i + 1, "operator": label,
                     "native_kill": native_kill, "diff_catch": diff_catch})
        print(f"  {f.name} L{i+1} {label}: native={native_kill} diff={diff_catch}")

    n = len(rows)
    nk = sum(r["native_kill"] for r in rows)
    dc = sum(r["diff_catch"] for r in rows)
    print(f"\n[{name}] DENSITY n={n}: native {nk}/{n}  mined {dc}/{n}  "
          f"only-mined {sum(r['diff_catch'] and not r['native_kill'] for r in rows)}  "
          f"only-native {sum(r['native_kill'] and not r['diff_catch'] for r in rows)}  "
          f"neither {sum(not r['native_kill'] and not r['diff_catch'] for r in rows)}")
    (OUTDIR / f"transfer_density_{name}.json").write_text(json.dumps(rows, indent=2),
                                                          encoding="utf-8")


# ── rung 6: OpenAPI ───────────────────────────────────────────────────────────

def rung6_openapi() -> None:
    spec_path = BASE / "petstore.yaml"
    import yaml

    def native() -> bool:
        from openapi_spec_validator import validate as v
        try:
            v(yaml.safe_load(spec_path.read_text(encoding="utf-8")))
            return True
        except Exception:
            return False

    def mined_ref():
        try:
            d = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
            return json.dumps(d, sort_keys=True)
        except Exception:
            return None

    ops = [
        (r"\bstring\b", "integer", "type_str_to_int"),
        (r"\binteger\b", "string", "type_int_to_str"),
        (r"\bint32\b", "int64", "format_flip"),
        (r"'200'", "'201'", "status_200_to_201"),
        (r"\brequired\b", "deprecated", "required_to_deprecated"),
        (r"\btrue\b", "false", "bool_flip"),
        (r"\bmaximum\b", "minimum", "max_to_min"),
        (r"\bpetId\b", "petsId", "param_rename"),
        (r"\barray\b", "object", "array_to_object"),
        (r"\bget\b", "post", "method_get_to_post"),
    ]
    _measure("openapi", {spec_path: spec_path.read_text(encoding="utf-8")},
             ops, native, mined_ref)


# ── rung 5: GitHub Actions ────────────────────────────────────────────────────

def rung5_actions() -> None:
    wf_dir = BASE / "podinfo/.github/workflows"
    files = {p: p.read_text(encoding="utf-8") for p in sorted(wf_dir.glob("*.yml"))
             + sorted(wf_dir.glob("*.yaml"))}
    import yaml

    def native() -> bool:
        for p in files:
            r = subprocess.run(
                [sys.executable, "-m", "check_jsonschema", "--builtin-schema",
                 "vendor.github-workflows", str(p)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                return False
        return True

    def _project(doc) -> dict:
        jobs = doc.get("jobs", {}) or {}
        return {
            "on": doc.get(True, doc.get("on")),  # yaml parses bare `on:` as True
            "jobs": {
                j: {
                    "runs-on": spec.get("runs-on"),
                    "needs": spec.get("needs"),
                    "if": spec.get("if"),
                    "matrix": (spec.get("strategy", {}) or {}).get("matrix"),
                    "steps": [
                        {"uses": s.get("uses"), "run": s.get("run"),
                         "with": s.get("with"), "if": s.get("if")}
                        for s in (spec.get("steps") or [])
                    ],
                    "permissions": spec.get("permissions"),
                    "secrets": spec.get("secrets"),
                }
                for j, spec in jobs.items()
            },
        }

    def mined_ref():
        try:
            out = {}
            for p in files:
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
                out[p.name] = _project(doc)
            return json.dumps(out, sort_keys=True, default=str)
        except Exception:
            return None

    ops = [
        (r"\bpush\b", "pull_request", "trigger_push_to_pr"),
        (r"\bmain\b", "master", "branch_rename"),
        (r"ubuntu-latest", "ubuntu-22.04", "runner_flip"),
        (r"\bneeds:\s*\[?\s*\w", "needs: [nonexistent", "needs_break"),
        (r"\bif:\s", "if: false && ", "if_disable"),
        (r"secrets\.GITHUB_TOKEN", "secrets.GH_TOKEN", "secret_rename"),
        (r"@v(\d)", r"@v9", "action_version_bump"),
        (r"\bcontents: read\b", "contents: write", "permission_escalate"),
    ]
    _measure("actions", files, ops, native, mined_ref)


# ── rung 4: Terraform (PARTIAL — native only) ─────────────────────────────────

def rung4_terraform() -> None:
    tf_dir = BASE / "learn-terraform-state"
    files = {p: p.read_text(encoding="utf-8") for p in sorted(tf_dir.glob("*.tf"))}

    init = subprocess.run(["terraform", "init", "-backend=false"],
                          capture_output=True, text=True, cwd=tf_dir,
                          timeout=600, shell=True)
    assert init.returncode == 0, f"terraform init failed: {init.stderr[-300:]}"

    def native() -> bool:
        r = subprocess.run(["terraform", "validate"], capture_output=True,
                           text=True, cwd=tf_dir, timeout=120, shell=True)
        return r.returncode == 0

    def mined_ref():
        return "MINED-INFEASIBLE-OFFLINE"  # constant -> diff_catch always False

    ops = [
        (r"\btrue\b", "false", "bool_flip"),
        (r"\bfalse\b", "true", "bool_flip2"),
        (r"8080", "8081", "port_flip"),
        (r"\bingress\b", "egress", "direction_flip"),
        (r"\bt2\.micro\b", "t2.nano", "instance_type_flip"),
        (r"-0\.", "-1.", "ami_ish_flip"),
        (r"\bvar\.instance_name\b", "var.instance_nam", "var_typo"),
        (r"\baws_instance\.example\b", "aws_instance.exampl", "ref_typo"),
        (r'= "([a-zA-Z][\w-]{3,})"', r'= "\1-x"', "string_value_suffix"),
    ]
    _measure("terraform", files, ops, native, mined_ref)
    print("[terraform] NOTE: mined oracle infeasible offline (plan needs cloud "
          "credentials) — PARTIAL per precommit; diff column is structurally False.")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("openapi", "all"):
        rung6_openapi()
    if which in ("actions", "all"):
        rung5_actions()
    if which in ("terraform", "all"):
        rung4_terraform()
