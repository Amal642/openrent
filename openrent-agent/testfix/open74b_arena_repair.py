"""
OPEN-74B: Arena repair.

Implements the two fixes required by OPEN-74A:
  Fix 1 — Single measurement path: signal detector used everywhere; pilot VC
           is re-characterised under the detector (PC agreement = 100%, so CE
           model training labels are unchanged; only VC metric is re-aligned).
  Fix 2 — LandlordActorV4: two-step PC→VC sequence.
           Turn 1 actor response: shares phone WITHOUT confirmation wording
             e.g. "Thanks. My number is 07123456789. What day suits you for a viewing?"
             → phone_captured fires, viewing_confirmed does NOT
           Turn 2 actor response (after agent gives a day/time): confirms
             e.g. "Yes, that works for me. Saturday at 2pm."
             → viewing_confirmed fires ("that works" + "2pm/pm")

Then runs OPEN-74A-style arena gates:
  Q1  baseline difficulty    : 20-80% VC under production policy + V4 actor
  Q2  PC pathway visibility  : PC must precede VC in some episodes
  Q3  strategy depth         : >= 50% multi-turn episodes
  Q4  policy discrimination  : production beats weak policy by >= 10pp VC
  Q5  transfer compatibility : candidate cells must have rho(g) > 0 (OPEN-71b)

Verdict: if all gates pass, arena is valid for OPEN-74 rerun.

Usage:
  cd openrent-agent && python testfix/open74b_arena_repair.py [--n 20]
"""

import argparse, glob, io, json, math, os, sys, time, uuid
from collections import defaultdict
from dataclasses import asdict

# Force UTF-8 stdout so Unicode box-drawing and arrow characters survive cp1252 consoles
# (idempotent: skip if already utf-8, e.g. when imported by another testfix script)
if (hasattr(sys.stdout, "buffer")
        and (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") != "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from simulation.actors.base import ActorGoal, ActorProfile
from simulation.actors.simulated_actor import RuleBasedActor
from simulation.conversation_designs import (
    VIEWING_FIRST_V1, build_simulation_persona, get_conversation_design,
)
from simulation.conversation_state import analyze_conversation_state
from simulation.engine.runtime_context import RuntimeContext
from simulation.lab import SCENARIO_BUILDERS
from simulation.policies.production_policy import ProductionPolicy
from app.ai.replies import generate_reply_result, _format_simulation_conversation
from simulation.sessions.transcript import ConversationTurn

# ── constants ─────────────────────────────────────────────────────────────────

PILOT = os.path.join(os.path.dirname(__file__), "..", "pilot_matrix_results")

# OPEN-71b positive-transfer groups
POSITIVE_TRANSFER = {
    "s02-screening-actor-starts-prod",
    "s04-phone-request-actor-starts-prod",
    "s05-reply-actor-starts-prod",
}

SCENARIOS = {
    "s02-screening": ("outreach-screening-before-phone",    "s02-screening-actor-starts-prod"),
    "s04-phone-req": ("outreach-phone-request",             "s04-phone-request-actor-starts-prod"),
    "s05-reply":     ("reply-after-landlord-question",      "s05-reply-actor-starts-prod"),
}

_PHONE_NUM  = "".join(("07", "123", "456", "789"))
SEED_BASE   = 6200   # non-overlapping with OPEN-74 (9000) and OPEN-74A (7400)
MAX_TURNS   = 7      # enough for 4-turn quality-gate flow: screen→quality-ask→quality-ans→phone→time→VC
_NEG_SIGS   = {"conversation_stalled", "phone_requested_too_early"}

# Arena gate thresholds (from OPEN-74A precommit)
VC_CAND_LOW  = 0.20
VC_CAND_HIGH = 0.80
Q4_GAP_THR   = 0.10  # 10pp

# ── LandlordActorV4 ────────────────────────────────────────────────────────────

class LandlordActorV4(RuleBasedActor):
    """
    Two-step actor that fires PC and VC in separate turns.

    Step 1 — phone share (fires PC only):
      Actor shares phone number WITHOUT confirmation wording after tenant
      answers screening + requests viewing.
      e.g. "Thanks. My number is 07123456789. What day suits you for a viewing?"
      phone_captured fires; viewing_confirmed does NOT.

    Step 2 — viewing confirmation (fires VC only):
      After phone is shared, actor confirms a specific slot when tenant
      proposes a day/time.
      e.g. "Yes, that works for me. Saturday at 2pm."
      viewing_confirmed fires.

    State is accumulated across turns in context.goal_progress.

    Branch map (evaluated in order):
      B  phone shared + time/viewing in current msg
           → confirm slot (fires VC)
      C  phone shared + no time yet
           → ask for preferred day
      A  employ+move+viewing+quality all confirmed + no phone ask
           → share phone (fires PC)
      D  early phone ask, screening not done
           → deflect
      D2 phone asked + screening+quality confirmed
           → share phone (fires PC)
      A2 employ+move+viewing confirmed but quality not yet
           → ask for rental history / property interest
      E  default
           → ask for missing screening info
    """

    _TIME_WORDS = [
        "saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday",
        "weekend", "morning", "afternoon", "evening", "tonight", "tomorrow",
        " pm", " am", "2pm", "3pm", "4pm", "noon", "midday", "week",
    ]
    # Cumulative quality words: rental history evidence OR specific property interest
    _QUALITY_WORDS = [
        # rental history
        "reference", "references", "rental history", "previous landlord",
        "always paid", "great references", "excellent reference",
        "reliable tenant", "reliable", "clean record", "no issues",
        "no problems", "good track record", "never missed",
        # property interest / location
        "location", "area", "garden", "parking", "love the", "perfect for",
        "ideal for", "commute", "close to", "near the", "neighbourhood",
        "neighborhood", "local", "schools", "transport", "convenient",
        "suits", "drawn to", "interest in", "caught my eye",
        "love the flat", "great property", "lovely",
    ]

    def __init__(self):
        super().__init__(ActorProfile(
            actor_id="landlord-v4",
            display_name="Mr Patel",
            persona="Private landlord screening a tenant.",
            tone="brief and practical",
            goal=ActorGoal(
                objective="Screen the tenant, share phone, then confirm a viewing time.",
                patience=4, trust_threshold=0.5,
                required_questions=["move_in_date", "employment_status"],
            ),
        ))

    def initial_message(self) -> str:
        return ("Hi, thanks for your message. Are you currently working and "
                "when would you be looking to move in?")

    def respond(self, context, agent_reply: str | None) -> str:
        if not agent_reply:
            return "I need a reply to continue."

        lo = agent_reply.lower()

        # ── Accumulate state across turns ──────────────────────────────────────
        if any(w in lo for w in ["work", "employ", "full-time", "part-time",
                                   "job", "manager", "employed"]):
            context.goal_progress["employ_confirmed"] = True
        if any(w in lo for w in ["move", "moving", "available", "next month",
                                   "next week", "immediately", "end of", "soon"]):
            context.goal_progress["move_confirmed"] = True
        if any(w in lo for w in ["viewing", "view", "come and see", "see the"]):
            context.goal_progress["viewing_requested"] = True
        if any(w in lo for w in self._QUALITY_WORDS):
            context.goal_progress["quality_confirmed"] = True

        phone_shared      = context.goal_progress.get("phone_shared", False)
        employ_confirmed  = context.goal_progress.get("employ_confirmed", False)
        move_confirmed    = context.goal_progress.get("move_confirmed", False)
        viewing_requested = context.goal_progress.get("viewing_requested", False)
        quality_confirmed = context.goal_progress.get("quality_confirmed", False)

        wants_phone   = any(w in lo for w in ["phone", "number", "mobile", "contact", "call"])
        mentions_time = any(w in lo for w in self._TIME_WORDS)
        wants_viewing = context.goal_progress.get("viewing_requested", False)  # from state

        # ── Branch B: phone shared + tenant gives a day/time ───────────────────
        if phone_shared and (mentions_time or any(w in lo for w in ["viewing", "view"])):
            context.goal_progress["vc_confirmed"] = True
            return "Yes, that works for me. Saturday at 2pm — I'll see you then."

        # ── Branch C: phone shared but no time proposed yet ────────────────────
        if phone_shared:
            return "What day and time works for you for the viewing?"

        # ── Branch A: all conditions met → share phone (fires PC) ──────────────
        if (employ_confirmed and move_confirmed and viewing_requested
                and quality_confirmed and not wants_phone):
            context.goal_progress["phone_shared"] = True
            return (f"Thanks for that. My number is {_PHONE_NUM}. "
                    "What day suits you for a viewing?")

        # ── Branch D: early phone ask, screening not done ──────────────────────
        if wants_phone and not (employ_confirmed and move_confirmed):
            return ("Before I share my number, could you let me know your "
                    "employment situation and when you're looking to move?")

        # ── Branch D2: phone asked with full screening + quality confirmed ──────
        if wants_phone and employ_confirmed and move_confirmed and quality_confirmed:
            context.goal_progress["phone_shared"] = True
            return (f"Sure. My number is {_PHONE_NUM}. "
                    "What day would you like to come and view?")

        # ── Branch A2: screening+viewing done, quality not yet given ───────────
        if employ_confirmed and move_confirmed and viewing_requested and not quality_confirmed:
            return ("Thanks. Before I share my contact details, could you tell me "
                    "about your rental history or what draws you to this property?")

        # ── Branch E: still waiting for screening info ─────────────────────────
        missing = []
        if not employ_confirmed: missing.append("employment status")
        if not move_confirmed:   missing.append("when you're looking to move")
        info = " and ".join(missing) if missing else "your details"
        return f"Thanks. I still need to know {info} before we go further."


# ── CE scoring (from OPEN-71/72/74) ──────────────────────────────────────────

_SPK   = {"actor": 0.0, "landlord": 0.0, "agent": 1.0}
_STATES = ["screening","viewing_negotiation","viewing_confirmed","phone_captured","stalled"]

def _episode_features(ep):
    rows = ep["turn_rows"]
    n = max(len(rows), 1)
    idx_mean  = sum(r["turn_index_0based"] for r in rows) / n / max(n-1, 1)
    spk_mean  = sum(_SPK.get(r["speaker"], 0.0) for r in rows) / n
    aph_frac  = sum(1 for r in rows if r.get("agent_asked_phone")) / n
    mlen_mean = sum(min(len(r.get("message",""))/500.0, 1.0) for r in rows) / n
    state_frac = [sum(1 for r in rows if r.get("current_state","") == s) / n
                  for s in _STATES]
    actor_rows = [r for r in rows if r["speaker"] == "actor"]
    na = max(len(actor_rows), 1)
    branch_frac = [
        sum(1 for r in actor_rows if r.get("landlord_branch") == k) / na
        for k in ["branch-1-initial","branch-2-phone-shared",
                  "branch-4-default-screening","branch-5-proactive-offer"]
    ]
    ce2_frac = sum(
        1 for r in rows
        if r.get("flipped_signals") and
           any(s not in _NEG_SIGS for s in r["flipped_signals"])
    ) / n
    return ([idx_mean, spk_mean, aph_frac, mlen_mean]
            + state_frac + branch_frac + [ce2_frac, n / 7.0])

def _sigmoid(x): return 1.0 / (1.0 + math.exp(-max(-60, min(60, x))))
def _dot(w, x):  return sum(a*b for a, b in zip(w, x))

def _lr_train(Xs, ys, lr=0.05, epochs=400, l2=0.01):
    w = [0.0] * len(Xs[0]); b = 0.0
    for _ in range(epochs):
        for x, y in zip(Xs, ys):
            p = _sigmoid(_dot(w, x) + b); g = p - y
            w = [wi - lr*(g*xi + l2*wi) for wi, xi in zip(w, x)]
            b -= lr * g
    return w, b

def _ce_score(w, b, ep):
    return _sigmoid(_dot(w, _episode_features(ep)) + b)


# ── pilot loading (signal-detector labels for VC) ─────────────────────────────

def load_pilot_episodes():
    """
    Load pilot episodes. VC is labelled using the signal detector (Fix 1:
    single measurement path). PC labels are unchanged (PC agreement = 100%).
    """
    eps = []
    for jf in glob.glob(os.path.join(PILOT, "**", "*.jsonl"), recursive=True):
        try:
            with open(jf) as fh:
                for line in fh:
                    ep = json.loads(line)
                    if "turn_rows" not in ep or "summary" not in ep or not ep["turn_rows"]:
                        continue
                    # PC: from summary (100% agreement with detector)
                    all_signals = {sig for tr in ep["turn_rows"]
                                   for sig in tr.get("flipped_signals", [])}
                    ep["_pc"] = "phone_captured" in all_signals
                    # VC: relabelled using signal detector (Fix 1)
                    transcript = [{"speaker": r["speaker"], "message": r.get("message","")}
                                  for r in ep["turn_rows"]]
                    try:
                        state = analyze_conversation_state(
                            transcript, conversation_design_id=VIEWING_FIRST_V1)
                        ep["_vc"] = bool(asdict(state.signals).get("viewing_confirmed", False))
                    except Exception:
                        ep["_vc"] = False
                    ep["_sk"]   = ep.get("scenario_key", "unk")
                    ep["_seed"] = ep.get("seed", 0)
                    eps.append(ep)
        except Exception:
            pass
    return eps


# ── policies ──────────────────────────────────────────────────────────────────

def _make_production_policy():
    conv_design = get_conversation_design(VIEWING_FIRST_V1)
    persona = build_simulation_persona(
        "professional",
        {"title": "2-bed flat", "rent_pcm": 1500, "location": "Manchester"},
    )
    return ProductionPolicy(
        conversation_design_id=VIEWING_FIRST_V1,
        conversation_design=asdict(conv_design),
        persona=persona,
    )


class WeakPolicy(ProductionPolicy):
    """Weak-policy baseline: answers screening honestly but never proactively
    suggests a viewing time or asks for contact details.  Used in Q4."""
    def build_prompt(self, conversation: str) -> str:
        base = super().build_prompt(conversation)
        return base + (
            "\n\nFor this conversation: respond ONLY to what the landlord explicitly "
            "asks. Do NOT suggest a viewing time or day, and do not ask for a phone "
            "number. Simply answer the landlord's questions."
        )


class DemonstrationPolicy(ProductionPolicy):
    """ProductionPolicy with few-shot demonstrations injected before 'Conversation:'."""
    def __init__(self, demonstrations: list[str], **kwargs):
        super().__init__(**kwargs)
        self.demonstrations = demonstrations

    def build_prompt(self, conversation: str) -> str:
        base = super().build_prompt(conversation)
        if not self.demonstrations:
            return base
        demo_block = (
            "\n\nExamples of conversations from similar situations that went well "
            "(study the approach, then apply it to your current conversation):\n\n"
            + "\n".join(self.demonstrations)
            + "\n--- End examples ---\n"
        )
        return base.replace("Conversation:\n", demo_block + "\nConversation:\n", 1)


def _make_weak_policy():
    conv_design = get_conversation_design(VIEWING_FIRST_V1)
    persona = build_simulation_persona(
        "professional",
        {"title": "2-bed flat", "rent_pcm": 1500, "location": "Manchester"},
    )
    return WeakPolicy(
        conversation_design_id=VIEWING_FIRST_V1,
        conversation_design=asdict(conv_design),
        persona=persona,
    )


def _make_demo_policy(demonstrations: list[str]):
    conv_design = get_conversation_design(VIEWING_FIRST_V1)
    persona = build_simulation_persona(
        "professional",
        {"title": "2-bed flat", "rent_pcm": 1500, "location": "Manchester"},
    )
    return DemonstrationPolicy(
        demonstrations=demonstrations,
        conversation_design_id=VIEWING_FIRST_V1,
        conversation_design=asdict(conv_design),
        persona=persona,
    )


# ── episode runner ─────────────────────────────────────────────────────────────

def run_fresh_trial(scenario_id: str, seed: int, policy, actor=None) -> dict:
    if actor is None:
        actor = LandlordActorV4()
    scenario = SCENARIO_BUILDERS[scenario_id](MAX_TURNS, "actor_starts")
    ctx = RuntimeContext(session_id=str(uuid.uuid4()), deterministic_seed=seed)

    conv_turns = []
    transcript_dicts = []

    actor_msg = actor.initial_message()
    conv_turns.append(ConversationTurn(
        speaker="actor", message=actor_msg, turn_index=0, source_event="ACTOR"))
    transcript_dicts.append({"speaker": "actor", "message": actor_msg})

    pc_first_turn = vc_first_turn = None
    final_state = "screening"

    for turn_idx in range(1, MAX_TURNS + 1):
        conv_str = _format_simulation_conversation(conv_turns)
        result   = generate_reply_result(
            conv_str, model=policy.model, temperature=policy.temperature,
            prompt_builder=policy.build_prompt,
        )
        agent_msg = (result.reply or "").strip()
        if not agent_msg:
            break

        conv_turns.append(ConversationTurn(
            speaker="agent", message=agent_msg, turn_index=turn_idx, source_event="AGENT"))
        transcript_dicts.append({"speaker": "agent", "message": agent_msg})

        actor_msg = actor.respond(ctx, agent_msg)
        conv_turns.append(ConversationTurn(
            speaker="actor", message=actor_msg, turn_index=turn_idx, source_event="ACTOR"))
        transcript_dicts.append({"speaker": "actor", "message": actor_msg})

        state = analyze_conversation_state(
            transcript_dicts, conversation_design_id=VIEWING_FIRST_V1)
        sigs = asdict(state.signals)
        final_state = state.current_state

        if sigs.get("phone_captured") and pc_first_turn is None:
            pc_first_turn = turn_idx
        if sigs.get("viewing_confirmed") and vc_first_turn is None:
            vc_first_turn = turn_idx

        if vc_first_turn is not None:
            break  # natural end; don't break on PC alone (track PC→VC sequencing)

    return {
        "seed": seed, "n_turns": turn_idx,
        "transcript": [{"speaker": t.speaker, "message": t.message} for t in conv_turns],
        "pc": pc_first_turn is not None,
        "vc": vc_first_turn is not None,
        "pc_first_turn": pc_first_turn,
        "vc_first_turn": vc_first_turn,
        "pc_before_vc":  (pc_first_turn is not None
                          and (vc_first_turn is None or pc_first_turn < vc_first_turn)),
        "vc_without_pc": (vc_first_turn is not None and pc_first_turn is None),
        "final_state":   final_state,
    }


def _run_cell(scenario_label, scenario_id, policy, N, seed_base, label=""):
    episodes = []
    for i in range(N):
        ep = run_fresh_trial(scenario_id, seed_base + i, policy)
        ep["scenario_label"] = scenario_label
        episodes.append(ep)
        n = len(episodes)
        print(f"  {label}  {n:2}/{N}  pc={ep['pc']}  vc={ep['vc']}  turns={ep['n_turns']}",
              end="\r")
    return episodes


def _cell_stats(episodes):
    n = max(len(episodes), 1)
    return {
        "n": n,
        "vc": sum(1 for e in episodes if e["vc"]) / n,
        "pc": sum(1 for e in episodes if e["pc"]) / n,
        "pc_before_vc":  sum(1 for e in episodes if e["pc_before_vc"]) / n,
        "vc_without_pc": sum(1 for e in episodes if e["vc_without_pc"]) / n,
        "avg_turns":     sum(e["n_turns"] for e in episodes) / n,
        "multi_turn":    sum(1 for e in episodes if e["n_turns"] >= 2) / n,
    }


# ── demonstrations ────────────────────────────────────────────────────────────

def _select_demos(eps, w, b, source_groups=None, q=5):
    pool = [e for e in eps if source_groups is None or e["_sk"] in source_groups]
    scored = sorted([(e, _ce_score(w, b, e)) for e in pool], key=lambda x: -x[1])
    return scored[:q]


def _format_demo(ep, idx):
    lines = [f"--- Example {idx} ---"]
    for row in ep["turn_rows"]:
        speaker = "Landlord" if row["speaker"] == "actor" else "You (tenant)"
        lines.append(f"{speaker}: {row['message']}")
    parts = []
    if ep["_pc"]: parts.append("phone captured")
    if ep["_vc"]: parts.append("viewing confirmed")
    lines.append(f"[Result: {', '.join(parts) or 'no positive outcome'}]")
    lines.append("")
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n",          type=int, default=20,
                    help="Episodes per cell (default 20)")
    ap.add_argument("--n-gate",     type=int, default=15,
                    help="Episodes per cell for arena gates (default 15)")
    ap.add_argument("--skip-gates", action="store_true",
                    help="Skip arena gates and go straight to policy improvement")
    args = ap.parse_args()
    N      = args.n
    N_GATE = args.n_gate

    t_start = time.time()
    prod_policy = _make_production_policy()
    weak_policy = _make_weak_policy()

    # ── Fix 1 announcement ────────────────────────────────────────────────────
    print("=== Fix 1: Single measurement path ===")
    print("  VC labelled by signal detector throughout (pilot + fresh episodes).")
    print("  PC labels unchanged (detector-summary agreement was 100% in OPEN-74A).")
    print("  CE model trained on PC labels — no retraining needed.")
    print()

    # ── Fix 2 announcement + quick sanity test ────────────────────────────────
    print("=== Fix 2: LandlordActorV4 two-step PC->VC ===")
    from simulation.conversation_state import analyze_conversation_state
    _t1 = [
        {"speaker": "actor",  "message": "Hi, are you working and when to move?"},
        {"speaker": "agent",  "message": "Yes full time, moving next month. Can I view the flat?"},
        {"speaker": "actor",  "message": f"Thanks for that. My number is {_PHONE_NUM}. What day suits you for a viewing?"},
    ]
    _t2 = _t1 + [
        {"speaker": "agent",  "message": "How about Saturday at 2pm?"},
        {"speaker": "actor",  "message": "Yes, that works for me. Saturday at 2pm — I'll see you then."},
    ]
    _s1 = asdict(analyze_conversation_state(_t1, VIEWING_FIRST_V1).signals)
    _s2 = asdict(analyze_conversation_state(_t2, VIEWING_FIRST_V1).signals)
    print(f"  After phone share:           PC={_s1['phone_captured']}  VC={_s1['viewing_confirmed']}")
    print(f"  After time confirmation:     PC={_s2['phone_captured']}  VC={_s2['viewing_confirmed']}")
    assert _s1["phone_captured"] and not _s1["viewing_confirmed"], "SANITY FAIL: phone share must fire PC only"
    assert _s2["viewing_confirmed"],                               "SANITY FAIL: time confirmation must fire VC"
    print("  Sanity checks passed.")
    print()

    # ══════════════════════════════════════════════════════════════════════════
    # Phase 1: Arena gates
    # ══════════════════════════════════════════════════════════════════════════

    gate_results = {}  # scenario_label -> {prod_stats, weak_stats}
    gates_passed = True

    if args.skip_gates:
        print("=== Arena gates skipped (--skip-gates) ===")
    else:
        print(f"=== Arena gates (N_gate={N_GATE} per cell) ===")
        seed_off = 0

        for sl, (scenario_id, pilot_sk) in SCENARIOS.items():
            # Q1-Q3: production policy
            lbl = f"gate prod {sl}"
            print(f"\n  [{lbl}]")
            prod_eps = _run_cell(sl, scenario_id, prod_policy, N_GATE,
                                 SEED_BASE + seed_off, lbl)
            seed_off += 200
            ps = _cell_stats(prod_eps)

            # Q4: weak policy
            lbl = f"gate weak {sl}"
            print(f"\n  [{lbl}]")
            weak_eps = _run_cell(sl, scenario_id, weak_policy, N_GATE,
                                 SEED_BASE + seed_off, lbl)
            seed_off += 200
            ws = _cell_stats(weak_eps)

            # Q5: transfer (static lookup)
            transfer = pilot_sk in POSITIVE_TRANSFER

            gate_results[sl] = {
                "prod": ps, "weak": ws,
                "gap": ps["vc"] - ws["vc"],
                "transfer": transfer, "pilot_sk": pilot_sk,
            }

        print("\n\n" + "-"*80)
        print(f"\n=== Arena gate results ===\n")
        hdr = (f"  {'scenario':15}  {'baseVC%':>7}  {'PC%':>5}  "
               f"{'PCbeVC%':>7}  {'multi%':>6}  "
               f"{'weakVC%':>7}  {'gap_pp':>7}  {'rho>0':>6}  "
               f"{'Q1':>3}  {'Q2':>3}  {'Q3':>3}  {'Q4':>3}  {'Q5':>3}")
        print(hdr)

        for sl, r in gate_results.items():
            ps, ws = r["prod"], r["weak"]
            q1 = VC_CAND_LOW <= ps["vc"] <= VC_CAND_HIGH
            q2 = ps["pc_before_vc"] > 0.05              # PC precedes VC in >5% of episodes
            q3 = ps["multi_turn"]   >= 0.50             # >=50% multi-turn
            q4 = r["gap"]           >= Q4_GAP_THR       # production beats weak by >=10pp
            q5 = r["transfer"]
            row_pass = all([q1, q2, q3, q4, q5])
            if not row_pass:
                gates_passed = False

            def _f(b): return "OK " if b else "FAIL"
            print(f"  {sl:15}  {ps['vc']*100:>6.1f}%  {ps['pc']*100:>4.1f}%  "
                  f"{ps['pc_before_vc']*100:>6.1f}%  {ps['multi_turn']*100:>5.1f}%  "
                  f"{ws['vc']*100:>6.1f}%  {r['gap']*100:>+6.1f}pp  "
                  f"{'YES' if r['transfer'] else 'NO':>6}  "
                  f"{_f(q1)}  {_f(q2)}  {_f(q3)}  {_f(q4)}  {_f(q5)}")

        print()
        if gates_passed:
            print("  ALL GATES PASSED — arena is valid. Proceeding to policy improvement.")
        else:
            print("  ONE OR MORE GATES FAILED — arena is not yet valid.")
            print("  Diagnosis:")
            for sl, r in gate_results.items():
                ps = r["prod"]
                if not (VC_CAND_LOW <= ps["vc"] <= VC_CAND_HIGH):
                    print(f"    Q1 FAIL {sl}: baseline VC={ps['vc']*100:.1f}% "
                          f"(need 20-80%)")
                if not (ps["pc_before_vc"] > 0.05):
                    print(f"    Q2 FAIL {sl}: PC precedes VC in only "
                          f"{ps['pc_before_vc']*100:.1f}% of episodes (need >5%)")
                if not (ps["multi_turn"] >= 0.50):
                    print(f"    Q3 FAIL {sl}: multi-turn {ps['multi_turn']*100:.1f}% "
                          f"(need >=50%)")
                if not (r["gap"] >= Q4_GAP_THR):
                    print(f"    Q4 FAIL {sl}: gap={r['gap']*100:+.1f}pp (need >=10pp)")
                if not r["transfer"]:
                    print(f"    Q5 FAIL {sl}: pilot_sk={r['pilot_sk']} "
                          f"not in positive-transfer groups")
        print()

    # ══════════════════════════════════════════════════════════════════════════
    # Phase 2: Policy improvement (only if gates passed or skipped)
    # ══════════════════════════════════════════════════════════════════════════

    if not gates_passed and not args.skip_gates:
        # Save gate results and exit
        out = {
            "experiment": "OPEN-74B",
            "phase": "arena_gates_only",
            "gate_results": {
                sl: {k: (v if k != "prod" and k != "weak" else
                         {kk: vv for kk, vv in v.items()})
                     for k, v in r.items()}
                for sl, r in gate_results.items()
            },
            "gates_passed": False,
            "verdict": "GATES_FAILED",
        }
        _save(out)
        return

    print(f"=== Policy improvement (N={N} per scenario per condition) ===")

    # Load pilot corpus
    print("Loading pilot corpus (signal-detector VC labels)...")
    eps = load_pilot_episodes()
    n_pc = sum(1 for e in eps if e["_pc"])
    n_vc = sum(1 for e in eps if e["_vc"])
    print(f"  {len(eps)} episodes  PC={n_pc} ({100*n_pc//len(eps)}%)  "
          f"VC={n_vc} ({100*n_vc//len(eps)}%)")

    # Train CE model
    Xs = [_episode_features(e) for e in eps]
    ys = [1 if e["_pc"] else 0 for e in eps]
    w, b = _lr_train(Xs, ys)
    for e in eps:
        e["_ce"] = _ce_score(w, b, e)

    # Select demonstrations
    Q_DEMOS = 5
    demos_ungated = _select_demos(eps, w, b, source_groups=None,        q=Q_DEMOS)
    demos_gated   = _select_demos(eps, w, b, source_groups=POSITIVE_TRANSFER, q=Q_DEMOS)

    print(f"\n  Ungated top-{Q_DEMOS}:")
    for ep, sc in demos_ungated:
        print(f"    [{ep['_sk']:45}] CE={sc:.3f}  PC={ep['_pc']}  VC={ep['_vc']}")
    print(f"  Gated top-{Q_DEMOS} (positive-transfer groups only):")
    for ep, sc in demos_gated:
        print(f"    [{ep['_sk']:45}] CE={sc:.3f}  PC={ep['_pc']}  VC={ep['_vc']}")
    print()

    demo_txt_ungated = [_format_demo(ep, i+1) for i, (ep, _) in enumerate(demos_ungated)]
    demo_txt_gated   = [_format_demo(ep, i+1) for i, (ep, _) in enumerate(demos_gated)]

    conditions = {
        "baseline":   prod_policy,
        "ungated_ce": _make_demo_policy(demo_txt_ungated),
        "gated_ce":   _make_demo_policy(demo_txt_gated),
    }

    results = defaultdict(list)  # condition -> [ep, ...]
    total = len(conditions) * len(SCENARIOS) * N
    done  = 0
    seed_off = 5000  # offset for policy-improvement phase

    for cond, policy in conditions.items():
        for sl, (scenario_id, _) in SCENARIOS.items():
            for i in range(N):
                seed = SEED_BASE + seed_off + i
                ep   = run_fresh_trial(scenario_id, seed, policy)
                ep["condition"] = cond
                ep["scenario_label"] = sl
                results[cond].append(ep)
                done += 1
                elapsed = time.time() - t_start
                eta = (total - done) / (done / elapsed) if elapsed > 0 else 0
                print(f"  {done:3}/{total}  {cond:12} {sl:15}  "
                      f"pc={ep['pc']}  vc={ep['vc']}  turns={ep['n_turns']}  "
                      f"ETA={eta:.0f}s", end="\r")
            seed_off += 100

    print(f"\n  Done in {time.time()-t_start:.0f}s\n")

    # ── Results table ─────────────────────────────────────────────────────────
    print("=== Results: VC% and PC% by condition × scenario ===")
    print(f"  {'cond':12}  {'scenario':15}  n  {'PC%':>5}  {'VC%':>5}  "
          f"{'PCbeVC%':>7}  {'dVC':>7}")

    base_vc = {}
    for sl in SCENARIOS:
        beps = [e for e in results["baseline"] if e["scenario_label"] == sl]
        base_vc[sl] = sum(1 for e in beps if e["vc"]) / max(len(beps), 1)

    full_stats = {}
    for cond in conditions:
        full_stats[cond] = {}
        for sl in SCENARIOS:
            eps_sl = [e for e in results[cond] if e["scenario_label"] == sl]
            s = _cell_stats(eps_sl)
            full_stats[cond][sl] = s
            dvc = s["vc"] - base_vc[sl] if cond != "baseline" else 0.0
            print(f"  {cond:12}  {sl:15}  {s['n']}  "
                  f"{s['pc']*100:>4.1f}%  {s['vc']*100:>4.1f}%  "
                  f"{s['pc_before_vc']*100:>6.1f}%  "
                  f"{'base' if cond == 'baseline' else f'{dvc*100:+.1f}pp':>7}")

    # Aggregate over positive-transfer scenarios
    print("\n=== Aggregate (all scenarios) ===")
    agg = {}
    for cond in conditions:
        all_eps = results[cond]
        n = max(len(all_eps), 1)
        agg[cond] = {
            "pc": sum(1 for e in all_eps if e["pc"]) / n,
            "vc": sum(1 for e in all_eps if e["vc"]) / n,
            "n":  n,
        }
        print(f"  {cond:12}  n={n}  PC={agg[cond]['pc']*100:.1f}%  "
              f"VC={agg[cond]['vc']*100:.1f}%")

    base_vc_all = agg["baseline"]["vc"]
    d_vc_ungated = agg["ungated_ce"]["vc"] - base_vc_all
    d_vc_gated   = agg["gated_ce"]["vc"]   - base_vc_all
    d_pc_ungated = agg["ungated_ce"]["pc"] - agg["baseline"]["pc"]
    d_pc_gated   = agg["gated_ce"]["pc"]   - agg["baseline"]["pc"]
    print(f"\n  delta VC ungated vs base: {d_vc_ungated*100:+.1f}pp")
    print(f"  delta VC gated   vs base: {d_vc_gated*100:+.1f}pp")

    mechanism_gated   = abs(d_pc_gated)   > 0.03
    mechanism_ungated = abs(d_pc_ungated) > 0.03
    print(f"\n=== Mechanism check (CE proxy shift) ===")
    print(f"  baseline   PC: {agg['baseline']['pc']*100:.1f}%")
    print(f"  ungated_ce PC: {agg['ungated_ce']['pc']*100:.1f}%  "
          f"delta={d_pc_ungated*100:+.1f}pp  visible={mechanism_ungated}")
    print(f"  gated_ce   PC: {agg['gated_ce']['pc']*100:.1f}%  "
          f"delta={d_pc_gated*100:+.1f}pp  visible={mechanism_gated}")

    # Verdict
    vc_pp = d_vc_gated * 100
    if not mechanism_gated:
        verdict = "MECHANISM_INERT"
        reason  = (f"CE rate shift |{d_pc_gated*100:.1f}pp| <= 3pp — "
                   "demonstrations did not change agent CE-proxy actions")
    elif vc_pp >= 10.0:
        verdict = "GREEN"
        reason  = f"VC improvement +{vc_pp:.1f}pp >= 10pp threshold"
    elif vc_pp >= 3.0:
        verdict = "YELLOW"
        reason  = f"VC improvement +{vc_pp:.1f}pp in 3-9pp range"
    elif vc_pp > 0:
        verdict = "RED"
        reason  = f"VC improvement +{vc_pp:.1f}pp < 3pp threshold"
    else:
        verdict = "RED"
        reason  = f"VC improvement {vc_pp:.1f}pp (zero or negative)"

    print(f"\n=== Verdict ===")
    print(f"  {verdict}: {reason}")

    out = {
        "experiment": "OPEN-74B",
        "phase": "full",
        "fix1_measurement": "signal_detector_throughout",
        "fix2_actor": "LandlordActorV4_two_step",
        "n_gate": N_GATE,
        "n_policy": N,
        "gate_results": {
            sl: {k: v for k, v in r.items() if k not in ("prod", "weak")}
            for sl, r in gate_results.items()
        } if gate_results else {},
        "gates_passed": gates_passed,
        "pilot_stats": {
            "n": len(eps), "pc": n_pc / len(eps), "vc": n_vc / len(eps)
        },
        "demo_pool": {
            "ungated": [{"sk": ep["_sk"], "ce": float(s), "pc": ep["_pc"], "vc": ep["_vc"]}
                        for ep, s in demos_ungated],
            "gated":   [{"sk": ep["_sk"], "ce": float(s), "pc": ep["_pc"], "vc": ep["_vc"]}
                        for ep, s in demos_gated],
        },
        "per_condition_per_scenario": {
            cond: {sl: {k: v for k, v in s.items() if k not in ("episodes",)}
                   for sl, s in full_stats[cond].items()}
            for cond in conditions
        },
        "aggregate": agg,
        "delta_vc_ungated": d_vc_ungated,
        "delta_vc_gated":   d_vc_gated,
        "delta_pc_ungated": d_pc_ungated,
        "delta_pc_gated":   d_pc_gated,
        "mechanism_visible_gated":   mechanism_gated,
        "mechanism_visible_ungated": mechanism_ungated,
        "verdict": verdict,
        "reason":  reason,
    }
    _save(out)


def _save(out):
    path = os.path.join(os.path.dirname(__file__), "open74b_arena_repair_results.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults: {path}")
    print(f"Verdict: {out.get('verdict', 'N/A')}")


if __name__ == "__main__":
    main()
