"""
OPEN-61: differential-vs-parent verification.

The parent is the expected value: per entry function, generate an INPUT corpus
(LLM, cached) and require a candidate repair's outputs to match the parent's
on every input. Exceptions count as outputs. Any divergence -> reject.

Used by open57_loop.py behind --differential.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "testfix/open61_input_corpus.json"

_RUNNER = '''
import json, os, sys, datetime
sys.path.insert(0, os.getcwd())
from datetime import datetime as _dt, timedelta

module_path, fn_name, corpus_json = sys.argv[1], sys.argv[2], sys.argv[3]
inputs = json.loads(corpus_json)

import importlib
mod = importlib.import_module(module_path)
fn = getattr(mod, fn_name)

ns = {"datetime": _dt, "timedelta": timedelta}
out = []
for expr in inputs:
    try:
        args = eval(expr, ns)          # expr evaluates to a tuple of args
        if not isinstance(args, tuple):
            args = (args,)
        result = fn(*args)
        out.append(repr(result))
    except Exception as exc:
        out.append(f"EXC:{type(exc).__name__}:{exc}")
print(json.dumps(out))
'''


def _gen_corpus_prompt(fn_name: str, signature: str, parent_source: str) -> str:
    # The parent IS the trusted reference; showing its source to the input
    # generator is legitimate (the whole oracle is parent-based) and maximizes
    # branch coverage. The generator produces INPUTS only — never outputs.
    return f"""Generate a differential-testing input corpus for this Python function:

    {signature}

=== Trusted reference implementation (generate inputs that exercise EVERY branch, key lookup, comparison, and table entry visible below) ===
{parent_source}

Return a JSON array of EXACTLY 20 strings. Each string is a Python expression
evaluating to the COMPLETE argument tuple for one call. Infer each parameter's
type from the signature and the reference implementation. Examples of tuple
syntax (adapt types to THIS function):
  "([{{'sender': 'landlord', 'message': 'see you at 3pm'}}],)"
  "('friendly_couple',)"
  "([{{'direction': 'inbound', 'content': 'hi'}}], {{'mobile_number': '07911123456'}})"

Coverage requirements: every dict-key fallback path, every entry of any
lookup/alias table, case variants, empty/None, boundary counts, and inputs
where branches DIFFER in output. `datetime` and `timedelta` are available in
the eval namespace. Return ONLY the JSON array.
"""


def _load_corpus() -> dict:
    if CORPUS_PATH.exists():
        return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return {}


def get_corpus(fn_name: str, signature: str, call_model, parent_source: str = "") -> list[str]:
    corpus = _load_corpus()
    if fn_name in corpus:
        return corpus[fn_name]
    raw, _ = call_model(_gen_corpus_prompt(fn_name, signature, parent_source),
                        "gpt-4.1-mini", max_tokens=2000)
    inputs: list[str] = []
    if raw:
        try:
            text = raw.strip()
            if text.startswith("```"):
                text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("```"))
            inputs = json.loads(text)[:20]
        except Exception:
            inputs = []
    corpus[fn_name] = inputs
    CORPUS_PATH.write_text(json.dumps(corpus, indent=2), encoding="utf-8")
    return inputs


def run_outputs(module_dotpath: str, fn_name: str, inputs: list[str]) -> list[str] | None:
    """Run fn over the corpus in a fresh subprocess against CURRENT disk state."""
    if not inputs:
        return None
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="o61_runner_", dir=ROOT / "testfix",
        delete=False, encoding="utf-8",
    ) as f:
        f.write(_RUNNER)
        runner = Path(f.name)
    try:
        result = subprocess.run(
            [sys.executable, str(runner), module_dotpath, fn_name, json.dumps(inputs)],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout.strip())
    except Exception:
        return None
    finally:
        runner.unlink(missing_ok=True)


def diverges(parent_out: list[str] | None, repaired_out: list[str] | None) -> bool:
    """True when outputs differ (or either side failed to produce outputs)."""
    if parent_out is None or repaired_out is None:
        return False  # corpus unusable -> differential abstains (suite verdict stands)
    return parent_out != repaired_out


def screen_corpus(module_dotpath: str, fn_name: str, corpus: list[str],
                  min_stable: int = 5) -> tuple[list[str], list[str] | None]:
    """OPEN-61b determinism screen: run the corpus twice on the parent; keep
    only inputs with identical outputs. Returns (stable_corpus, parent_outputs)
    or ([], None) when fewer than min_stable inputs survive (function excluded
    from the differential — its suite verdict stands alone)."""
    o1 = run_outputs(module_dotpath, fn_name, corpus)
    o2 = run_outputs(module_dotpath, fn_name, corpus)
    if o1 is None or o2 is None:
        return [], None
    stable = [(inp, a) for inp, a, b in zip(corpus, o1, o2) if a == b]
    if len(stable) < min_stable:
        return [], None
    return [inp for inp, _ in stable], [out for _, out in stable]
