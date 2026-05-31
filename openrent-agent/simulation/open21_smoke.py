#!/usr/bin/env python3
"""
OPEN-21 SMOKE — proves (a) the Ollama/Qwen LLM swap works and (b) the design varies + is
recorded. Runs all 5 conversation designs through compare_conversation_designs (which drives
the agent's LLM). NOT the real experiment (1 turn, scripted landlord) — just a pipeline check.

Run from openrent-agent/ with Ollama env vars, e.g.:
  OPENAI_BASE_URL=http://127.0.0.1:11434/v1 OPENAI_REPLY_MODEL=qwen2.5-coder:3b \
  OPENAI_API_KEY=ollama  python -m simulation.open21_smoke
"""
import os, json, traceback
from simulation.compare import compare_conversation_designs
from simulation.conversation_designs import CONVERSATION_DESIGNS

print("OPEN-21 smoke — model:", os.getenv("OPENAI_REPLY_MODEL"),
      "| base_url:", os.getenv("OPENAI_BASE_URL"))
designs = list(CONVERSATION_DESIGNS.keys())
print("designs:", designs)

rows = []
# compare_conversation_designs caps at 4 designs/call -> chunk into <=4
for chunk in (designs[:3], designs[3:]):
    try:
        out = compare_conversation_designs(
            conversation_design_ids=chunk, max_turns=1, deterministic_seed=42,
        )
    except Exception as e:
        print(f"\nERROR running chunk {chunk}: {type(e).__name__}: {e}")
        traceback.print_exc()
        continue
    for r in out.get("results", []):
        rows.append(r)

print(f"\n=== {len(rows)} design results ===")
for r in rows:
    keys = {k: r.get(k) for k in ("design_id", "viewing_progressed", "viewing_confirmed",
                                   "passed", "score", "success_signals")}
    # show first ~80 chars of the agent reply if present, to confirm the LLM produced text
    reply = ""
    for cand in ("agent_reply", "final_reply", "last_agent_message", "transcript"):
        v = r.get(cand)
        if isinstance(v, str) and v:
            reply = v[:80]; break
        if isinstance(v, list) and v:
            reply = str(v[-1])[:80]; break
    print(f"  design={r.get('design_id'):24s} keys={ {k:v for k,v in keys.items() if v is not None} }")
    if reply:
        print(f"      agent_text: {reply!r}")

distinct = {r.get("design_id") for r in rows}
print(f"\nSMOKE VERDICT: {len(rows)} runs across {len(distinct)} distinct designs "
      f"-> {'OK (LLM swap + design variation work)' if len(distinct) >= 2 and rows else 'FAILED'}")
print("full first result keys:", sorted(rows[0].keys()) if rows else "none")
