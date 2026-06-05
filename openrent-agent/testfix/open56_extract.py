"""
OPEN-56 step 2: extract behavioral specs from evidence bundles.

One LLM call per (entry function, arm). Arms E1..E4, E-code use their single
evidence source; E-all concatenates all five. S0 needs no extraction.

The extractor is instructed NOT to invent behavior beyond the evidence —
a null evidence bundle (E3) should produce a minimal spec, which is exactly
what prediction P1 tests.

Output: testfix/open56_specs.json   {arm: {entry_func: spec_text}}
"""

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ARMS = ["E1", "E2", "E3", "E4", "E-code", "E-all"]

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

_EVIDENCE_LABEL = {
    "E1": "existing pytest test functions that exercise this function",
    "E2": "runtime call traces — (arguments, return value) pairs captured during real executions",
    "E3": "code comments and docstrings associated with this function",
    "E4": "static call sites — code in the application that calls this function",
    "E-code": "the function's current trusted implementation source (including its helpers)",
}


def _build_extractor_prompt(entry_func: str, arm: str, evidence: dict[str, str]) -> str:
    sig = SIGNATURES[entry_func]
    if arm == "E-all":
        ev_sections = []
        for a in ["E1", "E2", "E3", "E4", "E-code"]:
            ev_sections.append(f"=== Evidence: {_EVIDENCE_LABEL[a]} ===\n{evidence[a]}")
        ev_block = "\n\n".join(ev_sections)
    else:
        ev_block = f"=== Evidence: {_EVIDENCE_LABEL[arm]} ===\n{evidence[arm]}"

    return f"""You are writing a behavioral SPECIFICATION for a Python function, to be used by a separate test engineer who will write pytest tests from your spec alone (they will never see the implementation).

Function signature: {sig}

{ev_block}

=== Your task ===
Write a compact behavioral specification (max 350 words) for `{entry_func}`. State as precisely as the evidence allows:
- the input schema: exact dict keys read, fallback keys, accepted types
- return values and types for each behavioral case
- matching rules: case sensitivity, whole-word vs substring, where keywords may appear
- exact keyword/pattern vocabularies, alias tables, and threshold values, enumerated in full when the evidence shows them
- boundary behavior: empty/None input, limits, ordering

RULES:
- Do NOT invent behavior the evidence does not support. If the evidence is insufficient to pin down a behavior, explicitly write "UNSPECIFIED: ..." for that aspect rather than guessing.
- Prefer concrete examples (input -> expected output) lifted from the evidence.
- Plain text only, no markdown headers.
"""


def _call_model(prompt: str, model: str, max_tokens: int = 900) -> str | None:
    from openai import OpenAI
    from app.config import settings

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception:
        return None


def main(model: str = "gpt-4.1-mini") -> None:
    evidence = json.loads((ROOT / "testfix/open56_evidence.json").read_text(encoding="utf-8"))

    specs: dict[str, dict[str, str]] = {arm: {} for arm in ARMS}
    total = len(ARMS) * len(evidence)
    done = 0
    for arm in ARMS:
        for fn, ev in evidence.items():
            prompt = _build_extractor_prompt(fn, arm, ev)
            spec = _call_model(prompt, model)
            if spec is None:
                time.sleep(2)
                spec = _call_model(prompt, model)
            specs[arm][fn] = spec or "(extraction failed)"
            done += 1
            print(f"[{done}/{total}] {arm} / {fn}  ({len(spec or '')} chars)")

    out = ROOT / "testfix/open56_specs.json"
    out.write_text(json.dumps(specs, indent=2), encoding="utf-8")
    print(f"\nSpecs written: {out}")


if __name__ == "__main__":
    main()
