"""
Transfer rung 3: the loop on Helm/K8s YAML (podinfo), native-scoreable set.

Stages per TRANSFER-RUNG3-precommit.md: detection = rendered diff vs parent;
localization = `# Source:` marker of first divergent rendered doc; repair =
locate-then-patch on the localized file (mutant source + <=10 diff lines);
verification = re-render matches parent exactly; GT (held out) = native stack.

Usage: python -m testfix.transfer3_loop
"""

import difflib
import json
import re
from pathlib import Path

CHART = Path("D:/transfer-rung1/podinfo/charts/podinfo")
MUTS = Path(__file__).resolve().parent / "transfer3_mutations.json"
OUT = Path(__file__).resolve().parent / "transfer3_results.json"
MODEL = "gpt-4.1-mini"

from testfix.open55b_testgen import _call_model
from testfix.transfer3_density import _native_green, _render


def _split_docs(rendered: str) -> list[tuple[str, str]]:
    """[(source_file, doc_text)] using helm's '# Source:' markers."""
    docs = []
    for chunk in rendered.split("\n---"):
        m = re.search(r"# Source: \S*?/(templates/\S+)", chunk)
        docs.append((m.group(1) if m else "?", chunk))
    return docs


def _localize(parent_render: str, mutant_render: str) -> tuple[str | None, str]:
    p_docs, m_docs = _split_docs(parent_render), _split_docs(mutant_render)
    for (src_p, dp), (_, dm) in zip(p_docs, m_docs):
        if dp != dm:
            diff = list(difflib.unified_diff(dp.splitlines(), dm.splitlines(),
                                             "expected(trusted)", "got", lineterm=""))
            return src_p, "\n".join(diff[:14])
    return None, ""


def _patch_prompt(rel: str, src: str, divergence: str) -> str:
    return (
        "You are fixing a regression in a Helm chart file. The chart's rendered "
        "manifests diverge from the last known-good (trusted) rendering, so this "
        "file contains a regression.\n\n"
        f"FILE ({rel}):\n{src}\n\n"
        f"RENDERED DIVERGENCE (expected = trusted rendering):\n{divergence}\n\n"
        "Produce a MINIMAL patch. Reply in EXACTLY this format:\n"
        "<<<<SEARCH\n(exact consecutive lines copied verbatim from the file)\n"
        "====\n(replacement lines)\n>>>>\n"
        "The SEARCH text must appear exactly once in the file. No explanation."
    )


def main() -> None:
    mutations = json.loads(MUTS.read_text(encoding="utf-8"))
    files = sorted(CHART.glob("templates/*.yaml")) + [CHART / "values.yaml"]
    parents = {str(f.relative_to(CHART)).replace("\\", "/"): f.read_text(encoding="utf-8")
               for f in files}
    parent_render = _render()
    assert parent_render and _native_green()

    results = []
    for mut in mutations:
        case_id, rel = mut["case_id"], mut["file"]
        path = CHART / rel
        src = parents[rel]
        lines = src.splitlines(keepends=True)
        assert lines[mut["lineno"] - 1] == mut["original_line"]
        lines[mut["lineno"] - 1] = mut["mutated_line"]

        record = {"case_id": case_id, "true_file": rel, "operator": mut["operator"],
                  "stage": None, "loop_success": False, "ground_truth": False,
                  "localized": None, "attempts": [], "repaired_file": None}
        path.write_text("".join(lines), encoding="utf-8")
        try:
            m_render = _render()
            if m_render == parent_render:
                record["stage"] = "missed_detection"
                results.append(record); print(f"[{case_id}] missed_detection"); continue
            loc, divergence = (None, "")
            if m_render is not None:
                loc, divergence = _localize(parent_render, m_render)
            # render failure or values.yaml change (markers point at templates):
            # fall back to trying values.yaml then the marker file
            cand_files = [c for c in ([loc] if loc else []) + ["values.yaml"]
                          if c in parents]
            record["localized"] = loc
            success = False
            for cand in dict.fromkeys(cand_files):
                cand_path = CHART / cand
                cand_src = cand_path.read_text(encoding="utf-8")
                fixed_raw, _ = _call_model(
                    _patch_prompt(cand, cand_src, divergence or "(chart fails to render)"),
                    MODEL, max_tokens=700)
                ok = False
                if fixed_raw:
                    m = re.search(r"<<<<SEARCH\n(.*?)\n====\n(.*?)\n?>>>>", fixed_raw, re.DOTALL)
                    if m and cand_src.count(m.group(1)) == 1:
                        new_src = cand_src.replace(m.group(1), m.group(2), 1)
                        cand_path.write_text(new_src, encoding="utf-8")
                        ok = _render() == parent_render
                        if not ok:
                            cand_path.write_text(cand_src, encoding="utf-8")
                record["attempts"].append([cand, ok])
                if ok:
                    success = True
                    record["repaired_file"] = cand
                    break
            if not success:
                record["stage"] = "repair_failed"
                results.append(record); print(f"[{case_id}] repair_failed (true: {rel})"); continue
            record["loop_success"] = True
            record["ground_truth"] = _native_green()
            record["stage"] = "success" if record["ground_truth"] else "false_success"
            results.append(record)
            print(f"[{case_id}] loop=SUCCESS gt={record['ground_truth']} "
                  f"repaired={record['repaired_file']} (true: {rel})")
        finally:
            for r2, s2 in parents.items():
                (CHART / r2).write_text(s2, encoding="utf-8")

    n = len(results)
    gt = sum(r["ground_truth"] for r in results)
    fs = sum(1 for r in results if r["loop_success"] and not r["ground_truth"])
    print(f"\nRUNG 3 loop (native-scoreable set)  n={n}: gt={gt}  fp={fs}")
    OUT.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
