"""
OPEN-70 corpus expansion runner.
Generates ~450 new episodes (150 per scenario x 3 scenarios) using
LandlordActorV2, which adds a viewing-confirmation branch so that both
phone_captured (CE2 oracle) and viewing_confirmed (ER oracle) can occur.

Output: pilot_matrix_results/a8_open70/<scenario>_trials.jsonl
Episode format matches existing pilot_matrix_results (turn_rows + summary).

Usage (from openrent-agent/):
    python testfix/open70_matrix_runner.py [--n-trials 150] [--seed-base 2000]
"""

import argparse, json, os, re, sys, time, uuid
from dataclasses import asdict

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from simulation.actors.base import ActorGoal, ActorProfile
from simulation.actors.simulated_actor import RuleBasedActor
from simulation.conversation_designs import CORPUS_NUMBER_CAPTURE_V1, build_simulation_persona, get_conversation_design

# Design used for all OPEN-70 trials: agent answers screening, then asks for
# phone after viewing progress — produces both PC and VC outcomes naturally.
OPEN70_DESIGN = CORPUS_NUMBER_CAPTURE_V1
from simulation.conversation_state import analyze_conversation_state
from simulation.engine.deterministic import build_rng
from simulation.engine.event_bus import EventBus
from simulation.engine.orchestrator import SimulationOrchestrator
from simulation.engine.runtime_context import RuntimeContext
from simulation.lab import SCENARIO_BUILDERS, _resolve_policy


# ── LandlordActorV2 ───────────────────────────────────────────────────────────
# Priority order:
#  A  phone ask + employment + move-in answered  → share phone (PC=True)
#  B  viewing request + employment + move-in, no phone ask → confirm viewing (VC=True)
#  C  phone ask but missing screening            → penalise, redirect
#  D  default                                   → screening reminder

_PHONE_NUM = "".join(("07", "700", "900", "123"))
_VC_RESPONSE = (
    "That works. You're welcome to come and view the flat this weekend — "
    "does Saturday morning suit you?"
)


class LandlordActorV2(RuleBasedActor):
    def __init__(self):
        super().__init__(ActorProfile(
            actor_id="landlord-v2",
            display_name="Mr Patel",
            persona="Private landlord screening a tenant.",
            tone="brief and practical",
            goal=ActorGoal(
                objective="Confirm suitability. Will offer viewing OR share phone.",
                patience=3,
                trust_threshold=0.6,
                required_questions=["move_in_date", "employment_status"],
            ),
        ))

    def initial_message(self) -> str:
        return (
            "Hi, thanks for your message. Are you working at the moment and "
            "when would you be looking to move?"
        )

    def respond(self, context, agent_reply: str | None) -> str:
        if not agent_reply:
            return "I need a proper reply before I can continue."
        lo = agent_reply.lower()
        wants_phone   = any(w in lo for w in ["phone","number","mobile","contact","call"])
        wants_viewing = any(w in lo for w in ["viewing","view","come and see","see the flat","arrange a time","arrange a viewing"])
        ans_move      = any(w in lo for w in ["move","available","next month","next week","immediately","end of the month"])
        ans_employ    = any(w in lo for w in ["work","employ","job","full-time","part-time","manager","professional"])

        if wants_phone and ans_move and ans_employ:           # Branch A
            context.goal_progress["phone_shared"] = True
            context.trust_score = min(1.0, context.trust_score + 0.35)
            return f"Sounds good. You can call me on {_PHONE_NUM} this evening and we can discuss a viewing."

        if wants_viewing and ans_employ and ans_move and not wants_phone:  # Branch B
            context.goal_progress["viewing_confirmed"] = True
            context.trust_score = min(1.0, context.trust_score + 0.25)
            return _VC_RESPONSE

        if wants_phone:                                       # Branch C
            context.trust_score = max(0.0, context.trust_score - 0.15)
            return "Before I share my number, can you confirm your work situation and when you want to move?"

        return "Thanks. I still need to know your work situation and move date before sharing contact details."  # Branch D


# ── turn_rows extraction ──────────────────────────────────────────────────────

_PHONE_ASK_RE = re.compile(r"\b(phone|number|mobile|contact|call)\b", re.I)
_SHARE_RE     = re.compile(r"\b(share|send|provide|give|could you|can you|would you)\b", re.I)

def _agent_asked_phone(turn: dict) -> bool:
    if turn["speaker"] != "agent":
        return False
    return bool(_PHONE_ASK_RE.search(turn["message"])) and bool(_SHARE_RE.search(turn["message"]))

def _classify_branch(turn: dict) -> str | None:
    if turn["speaker"] != "actor":
        return None
    msg = turn["message"].lower()
    if re.search(r"07\d{9}|\+44", msg):
        return "branch-2-phone-shared"
    if "that works" in msg or "welcome to" in msg:
        return "branch-5-proactive-offer"
    if "before i share" in msg:
        return "branch-3-early-phone-blocked"
    if "still need to know" in msg or "work situation" in msg:
        return "branch-4-default-screening"
    if "working at the moment" in msg:
        return "branch-1-initial"
    return "branch-unclassified"

def derive_turn_rows(transcript: list[dict]) -> list[dict]:
    prev = {}
    rows = []
    for i, turn in enumerate(transcript):
        state = analyze_conversation_state(transcript[:i+1], conversation_design_id=OPEN70_DESIGN)
        cur   = asdict(state.signals)
        flipped = [k for k, v in cur.items() if v and not prev.get(k, False)]
        rows.append({
            "turn_index_0based": i,
            "speaker":           turn["speaker"],
            "message":           turn["message"],
            "agent_asked_phone": _agent_asked_phone(turn),
            "landlord_branch":   _classify_branch(turn),
            "flipped_signals":   flipped,
            "current_state":     state.current_state,
        })
        prev = cur
    return rows


# ── summary ───────────────────────────────────────────────────────────────────

def derive_summary(transcript: list[dict], turn_rows: list[dict]) -> dict:
    state = analyze_conversation_state(transcript, conversation_design_id=OPEN70_DESIGN)
    sigs  = asdict(state.signals)
    offer_turn = next(
        (r["turn_index_0based"] for r in turn_rows
         if r["speaker"] == "actor" and "viewing_time_offered" in r["flipped_signals"]),
        None,
    )
    return {
        "actor_offered_time_in_window":  sigs.get("viewing_time_offered", False),
        "first_offer_turn_0based":       offer_turn,
        "viewing_confirmed_ever":        sigs.get("viewing_confirmed", False),
        "phone_requested_too_early_ever":sigs.get("phone_requested_too_early", False),
        "safe_path_reached":             sigs.get("viewing_confirmed", False) or sigs.get("phone_captured", False),
        "final_state":                   state.current_state,
    }


# ── single trial ──────────────────────────────────────────────────────────────

def run_trial(scenario_id: str, seed: int, max_turns: int = 7) -> dict:
    scenario    = SCENARIO_BUILDERS[scenario_id](max_turns, "actor_starts")
    persona     = build_simulation_persona(scenario.persona_type, scenario.property)
    conv_design = get_conversation_design(OPEN70_DESIGN)
    actor       = LandlordActorV2()
    policy      = _resolve_policy("production-policy-v1",
                                   conversation_design=conv_design,
                                   persona=persona,
                                   property=scenario.property)
    ctx = RuntimeContext(session_id=str(uuid.uuid4()), deterministic_seed=seed)
    ctx.flags["deterministic"]             = True
    ctx.flags["start_mode"]               = "actor_starts"
    ctx.flags["conversation_design_id"]   = conv_design.design_id
    ctx.flags["conversation_design_name"] = conv_design.name
    ctx.memory["persona"]                 = persona
    ctx.metrics["rng_preview"]            = build_rng(seed).randint(1, 1000)

    raw = SimulationOrchestrator(
        actor=actor, policy=policy, scenario=scenario,
        runtime_context=ctx, event_bus=EventBus(),
    ).run().to_dict()

    transcript = [
        {"speaker": t["speaker"], "message": t["message"]}
        for t in (raw.get("transcript") or [])
    ]
    turn_rows = derive_turn_rows(transcript)
    summary   = derive_summary(transcript, turn_rows)

    return {
        "scenario_key": scenario_id,
        "seed":         seed,
        "max_turns":    max_turns,
        "transcript":   transcript,
        "turn_rows":    turn_rows,
        "summary":      summary,
        "elapsed_ms":   int((raw.get("observability") or {}).get("run_duration_ms", 0)),
    }


# ── matrix ────────────────────────────────────────────────────────────────────

SK_MAP = {
    "outreach-screening-before-phone": "s02-screening-v2",
    "outreach-phone-request":          "s04-phone-request-v2",
    "reply-after-landlord-question":   "s05-reply-v2",
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-trials",   type=int, default=150)
    ap.add_argument("--seed-base",  type=int, default=2000)
    ap.add_argument("--output-dir", default=os.path.join(
        os.path.dirname(__file__), "..", "pilot_matrix_results", "a8_open70"))
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    grand_total = len(SK_MAP) * args.n_trials
    done = errors = 0

    for scenario_id, sk in SK_MAP.items():
        out = os.path.join(args.output_dir, f"{sk}_trials.jsonl")
        pc = vc = 0
        print(f"\n{sk}  ({args.n_trials} trials → {out})")
        with open(out, "w") as fout:
            for i in range(args.n_trials):
                seed = args.seed_base + i
                t0 = time.time()
                try:
                    ep = run_trial(scenario_id, seed)
                    ep["scenario_key"] = sk
                    pc += 1 if ep["summary"]["final_state"] == "phone_captured" else 0
                    vc += 1 if ep["summary"]["viewing_confirmed_ever"] else 0
                    fout.write(json.dumps(ep) + "\n")
                    fout.flush()
                    done += 1
                    print(f"  {i+1:>4}/{args.n_trials}  seed={seed}  "
                          f"final={ep['summary']['final_state']:<20}  "
                          f"PC={pc}  VC={vc}  ({time.time()-t0:.1f}s)", end="\r")
                except Exception as exc:
                    errors += 1
                    print(f"\n  ERROR seed={seed}: {exc}")
        print(f"\n  -> {sk}: PC={pc}  VC={vc}  of {args.n_trials} trials")

    print(f"\nFinished. {done}/{grand_total} episodes, {errors} errors.")


if __name__ == "__main__":
    main()
