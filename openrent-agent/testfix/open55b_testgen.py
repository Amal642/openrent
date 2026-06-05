"""
OPEN-55b: specification-conditioned test generation.

Design fix over OPEN-55 (which was RED at 4/20 with 4/20 'inverted' —
model read the mutated source and wrote tests conforming to the bug):
the model receives NO implementation at all. Input per case:

  - entry function name + signature
  - authored behavior specification (docstring-level contract)
  - import path
  - status constants (specification data, not implementation)

The model cannot conform to a mutation it has never seen, so the
'inverted' failure mode disappears by construction.

Spec-authoring note (confound, logged): the OpenRent codebase has ZERO
docstrings on all 10 entry functions, so specs were authored for this
experiment from the ORIGINAL implementations. One spec per entry
function, shared across all seeds attacking that function (limits
per-mutation tailoring). The spec author had seen the mutation list;
mitigation is the one-spec-per-function rule + documentation-level
granularity.

Precommit (same as OPEN-55):
  GREEN  >= 50%  kill rate on n=20
  YELLOW 25-49%
  RED    < 25%

Usage (from openrent-agent/):
    python -m testfix.open55b_testgen [--model MODEL] [--attempts N]
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── entry-function registry (apparatus fix from OPEN-55: phone_shared_state
#    lives in conversation_memory.py, NOT personas.py) ─────────────────────────

_ENTRY_MAP: dict[str, dict] = {
    "cross_001": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_002": {"entry_func": "detect_landlord_attitude",        "entry_file": "app/ai/conversation_memory.py"},
    "cross_003": {"entry_func": "latest_landlord_asked_for_phone", "entry_file": "app/ai/conversation_memory.py"},
    "cross_004": {"entry_func": "viewing_requested",               "entry_file": "app/ai/conversation_memory.py"},
    "cross_005": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_006": {"entry_func": "outbound_count",                  "entry_file": "app/ai/conversation_memory.py"},
    "cross_007": {"entry_func": "phone_shared_state",              "entry_file": "app/ai/conversation_memory.py"},
    "cross_008": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_009": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_010": {"entry_func": "extract_viewing_datetime",        "entry_file": "app/ai/stages.py"},
    "cross_011": {"entry_func": "extract_viewing_datetime",        "entry_file": "app/ai/stages.py"},
    "cross_012": {"entry_func": "get_conversation_style",          "entry_file": "app/ai/personas.py"},
    "cross_013": {"entry_func": "should_share_phone_now",          "entry_file": "app/ai/personas.py"},
    "cross_014": {"entry_func": "detect_landlord_attitude",        "entry_file": "app/ai/conversation_memory.py"},
    "cross_015": {"entry_func": "detect_landlord_attitude",        "entry_file": "app/ai/conversation_memory.py"},
    "cross_016": {"entry_func": "phone_shared_state",              "entry_file": "app/ai/conversation_memory.py"},
    "cross_017": {"entry_func": "outbound_count",                  "entry_file": "app/ai/conversation_memory.py"},
    "cross_018": {"entry_func": "extract_viewing_datetime",        "entry_file": "app/ai/stages.py"},
    "cross_019": {"entry_func": "detect_stage",                    "entry_file": "app/ai/stages.py"},
    "cross_020": {"entry_func": "landlord_messages",               "entry_file": "app/ai/conversation_memory.py"},
}

# ── authored behavior specifications (one per entry function) ──────────────────
# Documentation-level contracts derived from the ORIGINAL implementations.
# No docstrings exist in the codebase; these stand in for the missing specs.

SPECS: dict[str, str] = {
    "detect_stage": """detect_stage(messages) -> str | None

Determines the current conversation stage from a list of message dicts.
Each message dict carries its text under the "message" key (with "content"
as a fallback) and its sender under "sender" (fallback "direction").

Contract:
- Only the MOST RECENT 8 messages are considered. Anything earlier must
  have no effect on the result, no matter what it contains.
- Returns VIEWING_DISCUSSION (from app.db.status) if the latest message
  negates or reschedules: keywords such as "reschedule", "rearrange",
  "another time", "instead", "need to change" count even when they appear
  MID-SENTENCE, not only at the start of the message.
- Returns VIEWING_BOOKED when a booking confirmation (e.g. "confirmed",
  "see you <day>") appears together with a concrete time of day (e.g.
  "2pm", "14:30"). The confirmation and the time may be in DIFFERENT
  messages — e.g. landlord says "Confirmed, I'll see you then" and the
  tenant's neighbouring message contains "Saturday at 2pm"; the stage is
  still VIEWING_BOOKED. A single message containing both (e.g.
  "Confirmed, see you Thursday at 2pm") must also yield VIEWING_BOOKED.
- Returns VIEWING_DISCUSSION when scheduling is being discussed (e.g.
  availability questions, proposing days) without a confirmed booking.
- Returns None for empty/None input or when nothing matches.
""",
    "extract_viewing_datetime": """extract_viewing_datetime(messages, now=None) -> datetime | None

Extracts the agreed viewing datetime from recent messages (most recent 8).
Message text is read from the "message" key (fallback "content"). `now`
defaults to utcnow; pass a fixed datetime for deterministic tests.

Contract:
- Detects times of day like "3pm", "4 pm", "14:30". A message containing
  ONLY a time and no numeric calendar date (e.g. "let's meet at 3pm",
  "Confirmed, meet at 4pm") MUST yield a valid datetime — plain times must
  not be discarded just because no date is present.
- Digits that are part of a numeric calendar date (e.g. "12/06") must not
  be misread as a time of day.
- "tomorrow" in the message resolves the date to now + 1 day.
- With no date words at all, the date defaults to today, rolled forward
  one day only if the resulting datetime would be in the past.
- "Xpm" adds 12 to hours below 12 (3pm -> 15:00). Bare hours 1-7 with no
  am/pm suffix are assumed pm.
- Returns None when no time of day is mentioned anywhere.
""",
    "detect_landlord_attitude": """detect_landlord_attitude(messages, previous=None) -> str

Classifies the landlord's attitude from their messages.

Contract:
- Landlord messages are those whose sender is "landlord" OR "inbound"
  ("inbound" is OpenRent's label for landlord-side messages). The sender
  is read from the "sender" key with "direction" as a fallback, and the
  comparison is CASE-INSENSITIVE (e.g. "Landlord" or "LANDLORD" must
  still be recognised).
- Message text is read from the "message" key (fallback "content").
- Returns "aggressive" when recent landlord messages contain hostile
  language, e.g. "stop wasting my time", "serious enquiries only".
- Returns "suspicious" for scam-probing language, "helpful" /
  "friendly" / "cold" for the corresponding tones, "slow_reply" when the
  latest landlord reply came more than 24h after the previous one.
- Defaults to "responsive" when none of the above fire.
- With NO landlord messages at all, returns `previous` if it is a valid
  attitude, else "responsive".
""",
    "landlord_messages": """landlord_messages(messages) -> list

Returns the sub-list of messages sent by the landlord side.

Contract:
- A message belongs to the landlord when its sender value is "landlord"
  or "inbound" (OpenRent labels landlord-side messages "inbound").
- The sender value is read from the "sender" key; when there is no
  "sender" key, the "direction" key is used as a fallback. A message
  like {"direction": "inbound", "message": "..."} (no "sender" key at
  all) MUST be included.
- Matching is case-insensitive.
- Returns [] for None or empty input.
- Order is preserved; the returned dicts are the original message dicts.
""",
    "latest_landlord_asked_for_phone": """latest_landlord_asked_for_phone(messages) -> bool

True when the MOST RECENT landlord message asks for contact details.

Contract:
- Landlord messages: sender "landlord" or "inbound" (from "sender" key,
  fallback "direction"; case-insensitive). Only the LAST landlord message
  is inspected.
- Detection requires both a contact noun ("phone", "mobile", "number",
  "contact", "whatsapp", "call", "text") and a request verb/possessive
  ("send", "share", "give", "provide", "what's", "your", ...).
  Examples that must return True: "Can you send me your phone?",
  "What's your number?", "Share your WhatsApp please".
- Returns False when there are no landlord messages, or the latest
  landlord message is not a contact request.
""",
    "outbound_count": """outbound_count(messages) -> int

Counts the messages sent by OUR side (the tenant/agent).

Contract:
- A message counts when its sender value is one of "user", "tenant",
  "outbound", or "ai".
- The sender value is read from the "sender" key, falling back to the
  "direction" key, and the comparison is CASE-INSENSITIVE ("TENANT" or
  "Outbound" must still be counted).
- Landlord-side messages ("landlord", "inbound") are never counted.
- Returns 0 for None or empty input.
""",
    "viewing_requested": """viewing_requested(messages) -> bool

True when the conversation mentions arranging a viewing.

Contract:
- Scans ALL messages. Text is read from the "message" key, with
  "content" as a fallback — a message like {"sender": "landlord",
  "message": "When would you like to come for a viewing?"} MUST be
  detected even when no "content" key is present.
- Trigger words (whole-word, case-insensitive): viewing, view,
  come round, come over, appointment, see it, available.
- Returns False for None/empty input or when no trigger word appears.
""",
    "phone_shared_state": """phone_shared_state(messages, persona, conversation=None) -> bool

True when the tenant's phone number has already been shared in the
conversation.

Contract:
- If `conversation` has a truthy `phone_number_shared_at` attribute,
  returns True immediately.
- Otherwise scans tenant-side messages (sender one of "user", "tenant",
  "outbound", "ai"; sender from "sender" key, fallback "direction";
  case-insensitive) for the persona's mobile number
  (persona["mobile_number"]).
- Number matching ignores all non-digit characters in the message text:
  "My number is 07911 123 456" matches mobile_number "07911123456".
  Both the international form (447911123456) and local form
  (07911123456) of the same number must be recognised.
- Returns False when persona has no mobile_number, or the number does
  not appear in any tenant-side message.
""",
    "get_conversation_style": """get_conversation_style(style) -> dict

Resolves a conversation-style name to its configuration dict.

Contract:
- Canonical style names resolve directly to their config.
- LEGACY ALIASES must also resolve, via this table:
    "viewing_first"        -> "friendly_viewing"
    "friendly_couple"      -> "warm_casual"
    "direct_professional"  -> "direct_number_request"
    "relocation_approach"  -> "video_call_request"
    "whatsapp_first"       -> "whatsapp_coordination"
- Unknown/empty names fall back to "friendly_viewing".
- The returned config dict always contains a "phone_fetching_type" key.
  Reference values: friendly_viewing -> "viewing_first",
  warm_casual -> "delayed", direct_number_request -> "immediate",
  video_call_request -> "immediate",
  whatsapp_coordination -> "whatsapp_first".
- get_conversation_style("friendly_couple")["phone_fetching_type"]
  must therefore equal "delayed", and the call must NOT raise.
""",
    "should_share_phone_now": """should_share_phone_now(persona, *, landlord_asked=False, phone_shared=False, outbound_count=0, stage=None, drive_distance_high=False) -> bool

Decides whether the agent should share the tenant's phone number now.

Contract (checked in order):
- False when phone_shared is True, or persona has no "mobile_number".
- True when landlord_asked is True.
- Otherwise the decision combines persona["phone_fetching_type"]
  (default "delayed") and persona["conversation_style"]. The
  conversation_style is FIRST normalised through the legacy alias table
  ("direct_professional" -> "direct_number_request",
  "friendly_couple" -> "warm_casual", "viewing_first" ->
  "friendly_viewing", "relocation_approach" -> "video_call_request",
  "whatsapp_first" -> "whatsapp_coordination"; unknown ->
  "friendly_viewing").
- If phone_fetching_type is "immediate"/"whatsapp_first" OR the
  RESOLVED style is one of {"direct_number_request",
  "video_call_request", "whatsapp_coordination"}: share when
  outbound_count <= 1. Example: persona with phone_fetching_type
  "delayed" but conversation_style "direct_professional" (which
  resolves to "direct_number_request") and outbound_count=1 must
  return True.
- "delayed": share only when outbound_count >= 2 AND stage ==
  "VIEWING_BOOKED".
- "viewing_first": share only when stage == "VIEWING_BOOKED".
- "adaptive": share when stage == "VIEWING_BOOKED" or
  (drive_distance_high and outbound_count >= 1).
- Anything else: False.
""",
}

# ── signatures (shown to the model; extracted from original source) ───────────

SIGNATURES: dict[str, str] = {
    "detect_stage": "detect_stage(messages)",
    "extract_viewing_datetime": "extract_viewing_datetime(messages, now=None)",
    "detect_landlord_attitude": "detect_landlord_attitude(messages, previous=None)",
    "landlord_messages": "landlord_messages(messages)",
    "latest_landlord_asked_for_phone": "latest_landlord_asked_for_phone(messages)",
    "outbound_count": "outbound_count(messages)",
    "viewing_requested": "viewing_requested(messages)",
    "phone_shared_state": "phone_shared_state(messages, persona, conversation=None)",
    "get_conversation_style": "get_conversation_style(style)",
    "should_share_phone_now": (
        "should_share_phone_now(persona, *, landlord_asked=False, phone_shared=False, "
        "outbound_count=0, stage=None, drive_distance_high=False)"
    ),
}

_STATUS_CONSTANTS = (ROOT / "app/db/status.py").read_text(encoding="utf-8")


# ── seed loading + mutation (same as OPEN-55) ─────────────────────────────────

def _load_seeds() -> list[dict]:
    from testfix.seeds_cross import SEEDS_CROSS
    return SEEDS_CROSS


def _clear_pyc(py_path: Path) -> None:
    stem = py_path.stem
    cache_dir = py_path.parent / "__pycache__"
    for pyc in cache_dir.glob(f"{stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def _apply_seed_mutation(seed: dict) -> str | None:
    target_path = ROOT / seed["target_file"]
    file_src = target_path.read_text(encoding="utf-8")

    from testfix.extractor import _extract_function_source
    func_src = _extract_function_source(target_path, seed["target_function"])
    if func_src is None or seed["original_snippet"] not in func_src:
        return None

    mutated_func = func_src.replace(seed["original_snippet"], seed["mutated_snippet"], 1)
    return file_src.replace(func_src, mutated_func, 1)


# ── prompt ─────────────────────────────────────────────────────────────────────

def _build_prompt(entry_func: str, entry_file: str) -> str:
    module_dotpath = entry_file.replace("/", ".").replace("\\", ".").removesuffix(".py")
    spec = SPECS[entry_func]
    sig = SIGNATURES[entry_func]

    return f"""You are a test engineer. Write pytest tests for the function below from its SPECIFICATION ONLY — you do not have access to the implementation.

=== Function ===
{sig}

Import as: from {module_dotpath} import {entry_func}

=== Specification ===
{spec}

=== Status constants (app/db/status.py) — import what you need ===
{_STATUS_CONSTANTS}

=== Your task ===
Write 3–6 pytest test functions that:
1. Verify the SPECIFIED behaviour precisely — every clause of the contract that can be tested cheaply should have a test.
2. Use realistic inputs and assert SPECIFIC expected return values.
3. Pay particular attention to edge cases the specification calls out explicitly (fallback keys, case-insensitivity, mid-sentence keywords, boundary counts, alias resolution, etc.).
4. Do NOT directly call private helpers (names starting with `_`). Test only through `{entry_func}`.
5. Every test must assert a concrete expected value (== comparisons or `is True`/`is False`).

Return ONLY valid Python code (imports + test functions). No explanation, no markdown fences.
"""


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call_model(prompt: str, model: str, max_tokens: int = 2000) -> tuple[str | None, float]:
    from openai import OpenAI
    from app.config import settings

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0)
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()
        return content, latency_ms
    except Exception:
        return None, (time.perf_counter() - t0) * 1000


# ── validation ─────────────────────────────────────────────────────────────────

def _run_generated_test(test_code: str, label: str) -> tuple[str, str]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix=f"open55b_{label}_",
        dir=ROOT / "testfix", delete=False, encoding="utf-8",
    ) as f:
        f.write(test_code)
        tmp_path = Path(f.name)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(tmp_path), "--tb=short", "-q", "--no-header"],
            capture_output=True, text=True, cwd=ROOT,
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            return "passed", output
        if "SyntaxError" in output or "ImportError" in output or "ModuleNotFoundError" in output:
            return "error", output
        return "failed", output
    finally:
        tmp_path.unlink(missing_ok=True)


def _classify(on_mutant: str, on_original: str) -> str:
    if on_mutant == "error" or on_original == "error":
        return "syntax_error"
    if on_mutant == "failed" and on_original == "passed":
        return "killed"
    if on_mutant == "passed" and on_original == "failed":
        return "inverted"          # should be impossible by construction in 55b
    if on_mutant == "failed" and on_original == "failed":
        return "false_positive"
    return "both_pass"


def _calls_private_helper(test_code: str) -> bool:
    return bool(re.search(r'\b_[a-z]\w*\(', test_code))


def _has_real_assertion(test_code: str) -> bool:
    for m in re.finditer(r'assert\s+(.+)', test_code):
        clause = m.group(1).strip()
        if ' == ' in clause or ' is True' in clause or ' is False' in clause:
            return True
    return False


def _count_test_functions(test_code: str) -> int:
    return len(re.findall(r'^def test_', test_code, re.MULTILINE))


# ── main loop ─────────────────────────────────────────────────────────────────

def run(model: str, attempts: int) -> list[dict]:
    seeds = _load_seeds()
    results = []
    # Cache one generation per entry function per attempt-round: the prompt is
    # identical for all seeds sharing an entry function, BUT each seed mutates a
    # different helper, so validation runs per seed. Fresh generation per seed
    # keeps seeds independent (temperature noise), so we do NOT cache.

    for seed in seeds:
        case_id = seed["case_id"]
        entry_info = _ENTRY_MAP[case_id]
        entry_func = entry_info["entry_func"]
        entry_file = entry_info["entry_file"]
        target_path = ROOT / seed["target_file"]

        mutated_src = _apply_seed_mutation(seed)
        if mutated_src is None:
            print(f"[{case_id}] SKIP — mutation snippet not found")
            continue

        prompt = _build_prompt(entry_func, entry_file)

        best_outcome = None
        best_code = None
        latency_total = 0.0

        for attempt in range(1, attempts + 1):
            generated, latency_ms = _call_model(prompt, model)
            latency_total += latency_ms

            if not generated:
                print(f"  [{case_id}] attempt {attempt} — LLM returned nothing")
                continue

            # IMPORTANT: validate on ORIGINAL first. A spec-derived test that
            # fails on the original is a bad test regardless of the mutant.
            on_original, _ = _run_generated_test(generated, f"{case_id}_orig")

            original_src = target_path.read_text(encoding="utf-8")
            target_path.write_text(mutated_src, encoding="utf-8")
            _clear_pyc(target_path)
            try:
                on_mutant, _ = _run_generated_test(generated, f"{case_id}_mut")
            finally:
                target_path.write_text(original_src, encoding="utf-8")
                _clear_pyc(target_path)

            outcome = _classify(on_mutant, on_original)
            print(
                f"  [{case_id}] attempt {attempt}  on_original={on_original}  "
                f"on_mutant={on_mutant}  outcome={outcome}  ({latency_ms:.0f}ms)"
            )

            if outcome == "killed":
                best_outcome = "killed"
                best_code = generated
                break
            rank = {"both_pass": 1, "false_positive": 2, "inverted": 3, "syntax_error": 4}
            if best_outcome is None or rank.get(outcome, 9) < rank.get(best_outcome, 9):
                best_outcome = outcome
                best_code = generated

        results.append({
            "case_id": case_id,
            "entry_func": entry_func,
            "target_function": seed["target_function"],
            "outcome": best_outcome or "no_generation",
            "calls_private_helper": _calls_private_helper(best_code or ""),
            "has_real_assertion": _has_real_assertion(best_code or ""),
            "n_test_functions": _count_test_functions(best_code or ""),
            "latency_ms": round(latency_total),
            "generated_code": best_code,
        })

    return results


def _print_summary(results: list[dict]) -> None:
    from collections import Counter
    n = len(results)
    outcomes = Counter(r["outcome"] for r in results)
    killed = outcomes["killed"]
    kill_rate = killed / n if n else 0.0

    print()
    print("=" * 68)
    print(f"OPEN-55b SPEC-CONDITIONED TEST GENERATION  n={n}")
    print("=" * 68)
    print(f"  killed (mutation kill)   : {killed}/{n} = {kill_rate:.1%}")
    print(f"  both_pass (too weak)     : {outcomes['both_pass']}/{n}")
    print(f"  inverted (conformed)     : {outcomes['inverted']}/{n}  (should be 0 by construction)")
    print(f"  false_positive           : {outcomes['false_positive']}/{n}")
    print(f"  syntax_error             : {outcomes['syntax_error']}/{n}")
    print()
    calls_private = sum(1 for r in results if r["calls_private_helper"])
    no_real_assert = sum(1 for r in results if not r["has_real_assertion"])
    print("Secondary metrics:")
    print(f"  tests calling private helpers : {calls_private}/{n}")
    print(f"  tests with no concrete assert : {no_real_assert}/{n}")
    if n:
        print(f"  avg test functions generated  : {sum(r['n_test_functions'] for r in results)/n:.1f}")
    print()

    if kill_rate >= 0.50:
        verdict = "GREEN"
    elif kill_rate >= 0.25:
        verdict = "YELLOW"
    else:
        verdict = "RED"
    print("S4 precommit:")
    print(f"  {verdict}  kill_rate={kill_rate:.1%}  (GREEN>=50%, YELLOW>=25%, RED<25%)")
    print()

    print("Per-case:")
    print(f"  {'case_id':<12} {'entry_func':<32} {'B':<30} {'outcome'}")
    print("  " + "-" * 84)
    for r in results:
        print(f"  {r['case_id']:<12} {r['entry_func']:<32} {r['target_function']:<30} {r['outcome']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OPEN-55b spec-conditioned test generation")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--out", default="testfix/open55b_results.json")
    args = parser.parse_args()

    print(f"OPEN-55b spec-conditioned testgen  model={args.model}  attempts={args.attempts}  n=20 seeds")
    print()

    results = run(model=args.model, attempts=args.attempts)
    _print_summary(results)

    out_path = ROOT / args.out
    out_path.write_text(
        json.dumps({"model": args.model, "attempts": args.attempts, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(f"\nResults: {out_path}")
