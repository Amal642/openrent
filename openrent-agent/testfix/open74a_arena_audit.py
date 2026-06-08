"""
OPEN-74A: Arena validity audit.

Five questions that must be answered before OPEN-74 can be rerun.

Q0  calibration   : signal-detector VC vs summary.viewing_confirmed_ever (108 pilot episodes)
Q1  difficulty    : VC%/PC% across scenario × actor cells (N per cell)
Q2  PC pathway    : PC-before-VC, VC-without-PC, PC-dead-end rates per cell
Q3  strategy depth: multi-turn rate per cell
Q4  discrimination: production vs weak policy; need >= 10pp VC gap
Q5  transfer      : candidate cells (20-80% VC) vs OPEN-71b positive-transfer groups

Usage:
  cd openrent-agent && python testfix/open74a_arena_audit.py [--n 15]
"""

import argparse, glob, json, math, os, sys, time, uuid
from collections import defaultdict
from dataclasses import asdict

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from simulation.actors.base import ActorGoal, ActorProfile
from simulation.actors.landlord_actor import LandlordActor
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

# From OPEN-71b: groups where CE→ER transfer rho > 0
POSITIVE_TRANSFER_GROUPS = {
    "s02-screening-actor-starts-prod",
    "s04-phone-request-actor-starts-prod",
    "s05-reply-actor-starts-prod",
}

SCENARIOS = {
    "s02-screening": "outreach-screening-before-phone",
    "s04-phone-req": "outreach-phone-request",
    "s05-reply":     "reply-after-landlord-question",
}

_PHONE_NUM   = "".join(("07", "123", "456", "789"))
SEED_BASE    = 7400   # non-overlapping with OPEN-74 (9000)
MAX_TURNS    = 5      # higher than OPEN-74 to expose PC→VC sequencing
Q0_AGREE_THR = 0.85
Q4_GAP_THR   = 0.10  # 10pp
VC_CAND_LOW  = 0.20
VC_CAND_HIGH = 0.80

# ── LandlordActorV3 (identical to open74_policy_improvement.py) ───────────────

class LandlordActorV3(RuleBasedActor):
    def __init__(self, variant: str = "default"):
        self.variant = variant
        super().__init__(ActorProfile(
            actor_id=f"landlord-v3-{variant}",
            display_name="Mr Patel",
            persona="Private landlord screening a tenant.",
            tone="brief and practical",
            goal=ActorGoal(
                objective="Confirm suitability, then offer viewing or share phone.",
                patience=3, trust_threshold=0.6,
                required_questions=["move_in_date", "employment_status"],
            ),
        ))

    def initial_message(self) -> str:
        if self.variant == "brusque":
            return "Working? Moving when?"
        if self.variant == "cooperative":
            return ("Hi, thanks for getting in touch! Happy to chat — "
                    "just need to know if you're working and when you'd like to move.")
        if self.variant == "suspicious":
            return ("Hi. I get a lot of messages so I need to be careful. "
                    "Are you actually working at the moment and when would you move?")
        return ("Hi, thanks for your message. Are you working at the moment and "
                "when would you be looking to move?")

    def respond(self, context, agent_reply: str | None) -> str:
        if not agent_reply:
            return "I need a reply before I can continue."
        lo = agent_reply.lower()
        wants_phone   = any(w in lo for w in ["phone", "number", "mobile", "contact", "call"])
        wants_viewing = any(w in lo for w in ["viewing", "view", "come and see", "arrange"])
        ans_employ    = any(w in lo for w in ["work", "employ", "full-time", "part-time",
                                               "job", "manager"])
        ans_move      = any(w in lo for w in ["move", "moving", "available", "next month",
                                               "next week", "immediately", "end of"])
        viewing_offered = context.goal_progress.get("viewing_offered", False)

        if wants_viewing and ans_employ and ans_move and not viewing_offered and not wants_phone:
            context.goal_progress["viewing_offered"] = True
            if self.variant == "suspicious":
                context.trust_score = max(0.0, context.trust_score - 0.05)
                return "I'm a bit cautious about viewings. Can you tell me more about yourself first?"
            if self.variant == "brusque":
                return "Saturday 2pm works."
            return "Yes, that works for me. How about Saturday at 2pm — does that suit you?"

        if viewing_offered and wants_phone:
            context.goal_progress["phone_shared"] = True
            context.trust_score = min(1.0, context.trust_score + 0.35)
            if self.variant == "suspicious":
                return (f"Ok. Yes, that works. You can call me on {_PHONE_NUM} "
                        "just to confirm the viewing time.")
            return (f"Yes, that works. You can call me on {_PHONE_NUM} "
                    "to confirm the viewing details.")

        if wants_phone and ans_employ and ans_move:
            context.goal_progress["phone_shared"] = True
            context.trust_score = min(1.0, context.trust_score + 0.25)
            if self.variant == "suspicious":
                context.trust_score = max(0.0, context.trust_score - 0.1)
                return (f"Hmm, ok. Yes, that works I suppose. "
                        f"My number is {_PHONE_NUM} — call me to arrange a viewing.")
            if self.variant == "brusque":
                return f"Fine. {_PHONE_NUM}. Yes, that works for viewing."
            return (f"Yes, that works for me. You can reach me on {_PHONE_NUM} "
                    "and we can confirm the viewing.")

        if wants_phone:
            context.trust_score = max(0.0, context.trust_score - 0.15)
            if self.variant == "suspicious":
                return "I won't share my number until I know more about you."
            if self.variant == "brusque":
                return "Work and move date first."
            return ("Before I share my number, can you confirm your work situation "
                    "and when you want to move?")

        if self.variant == "brusque":
            return "Still need work and move date."
        if self.variant == "cooperative":
            return ("Thanks for that! Just to confirm — could you tell me your "
                    "work situation and when you're looking to move?")
        if self.variant == "suspicious":
            return ("I'm not sure I have enough information yet. "
                    "What exactly is your work situation and when would you move?")
        return ("Thanks. I still need to know your work situation and move date "
                "before we can progress.")


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
    """
    Weak-policy baseline: answers screening honestly but never proactively
    suggests a viewing or asks for a phone number.  Used in Q4 discrimination test.
    """
    def build_prompt(self, conversation: str) -> str:
        base = super().build_prompt(conversation)
        override = (
            "\n\nFor this conversation: respond ONLY to what the landlord explicitly asks. "
            "Do NOT suggest a viewing, do not offer to arrange anything, and do not ask "
            "for a phone number unless the landlord first confirms a viewing slot."
        )
        return base + override


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


# ── multi-turn runner (parameterised actor) ───────────────────────────────────

def run_fresh_trial(scenario_id: str, seed: int, policy, actor) -> dict:
    """
    Run one fresh episode.  Returns per-episode dict including pc_first_turn,
    vc_first_turn, and derived pathway flags for Q2 analysis.
    Breaks only on VC (not on PC alone) so the PC→VC sequence can be observed.
    """
    scenario = SCENARIO_BUILDERS[scenario_id](MAX_TURNS, "actor_starts")
    ctx = RuntimeContext(session_id=str(uuid.uuid4()), deterministic_seed=seed)

    conv_turns: list[ConversationTurn] = []
    transcript_dicts: list[dict] = []

    actor_msg = actor.initial_message()
    conv_turns.append(ConversationTurn(
        speaker="actor", message=actor_msg, turn_index=0, source_event="ACTOR"))
    transcript_dicts.append({"speaker": "actor", "message": actor_msg})

    pc_first_turn = None
    vc_first_turn = None
    final_state   = "screening"

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
            break  # natural end; keep going after PC to catch PC→VC sequences

    pc = pc_first_turn is not None
    vc = vc_first_turn is not None
    pc_before_vc  = pc and (not vc or pc_first_turn < vc_first_turn)
    vc_without_pc = vc and not pc
    pc_dead_end   = pc and not vc

    return {
        "seed": seed, "n_turns": turn_idx,
        "transcript": [{"speaker": t.speaker, "message": t.message} for t in conv_turns],
        "pc": pc, "vc": vc,
        "pc_first_turn": pc_first_turn, "vc_first_turn": vc_first_turn,
        "pc_before_vc": pc_before_vc, "vc_without_pc": vc_without_pc,
        "pc_dead_end": pc_dead_end, "final_state": final_state,
    }


def run_cell(scenario_label, scenario_id, actor_label, actor_factory, policy, N, seed_offset,
             label_str=""):
    episodes = []
    for i in range(N):
        seed   = SEED_BASE + seed_offset + i
        actor  = actor_factory()
        ep     = run_fresh_trial(scenario_id, seed, policy, actor)
        ep["scenario_label"] = scenario_label
        ep["actor_label"]    = actor_label
        episodes.append(ep)
        done = i + 1
        print(f"  {label_str}  {done:2}/{N}  vc={ep['vc']}  pc={ep['pc']}  "
              f"turns={ep['n_turns']}", end="\r")
    return episodes


# ── Q0: pilot transcript calibration ─────────────────────────────────────────

def load_pilot_episodes():
    eps = []
    for jf in glob.glob(os.path.join(PILOT, "**", "*.jsonl"), recursive=True):
        try:
            with open(jf) as fh:
                for line in fh:
                    ep = json.loads(line)
                    if "turn_rows" not in ep or "summary" not in ep or not ep["turn_rows"]:
                        continue
                    s = ep["summary"]
                    ep["_vc_sum"] = bool(s.get("viewing_confirmed_ever",
                                                s.get("final_state", "") == "viewing_confirmed"))
                    ep["_pc_sum"] = bool(s.get("phone_captured_ever",
                                                s.get("final_state", "") == "phone_captured"))
                    ep["_sk"]     = ep.get("scenario_key", "unk")
                    eps.append(ep)
        except Exception:
            pass
    return eps


def run_q0(eps):
    rows = []
    for ep in eps:
        transcript = [{"speaker": r["speaker"], "message": r.get("message", "")}
                      for r in ep["turn_rows"]]
        try:
            state = analyze_conversation_state(
                transcript, conversation_design_id=VIEWING_FIRST_V1)
            sigs = asdict(state.signals)
            det_vc = bool(sigs.get("viewing_confirmed", False))
            det_pc = bool(sigs.get("phone_captured", False))
        except Exception:
            det_vc = det_pc = False
        rows.append({
            "sk": ep["_sk"], "sum_vc": ep["_vc_sum"], "det_vc": det_vc,
            "sum_pc": ep["_pc_sum"], "det_pc": det_pc,
        })

    n = len(rows)
    if n == 0:
        return {"error": "no pilot episodes found"}

    vc_agree    = sum(1 for r in rows if r["det_vc"] == r["sum_vc"]) / n
    vc_fp_rate  = sum(1 for r in rows if r["det_vc"] and not r["sum_vc"]) / n
    vc_fn_rate  = sum(1 for r in rows if not r["det_vc"] and r["sum_vc"]) / n
    pc_agree    = sum(1 for r in rows if r["det_pc"] == r["sum_pc"]) / n

    # per scenario key breakdown
    by_sk = defaultdict(list)
    for r in rows:
        by_sk[r["sk"]].append(r)

    per_sk = {}
    for sk, sk_rows in sorted(by_sk.items()):
        nk = len(sk_rows)
        per_sk[sk] = {
            "n":       nk,
            "sum_vc":  sum(1 for r in sk_rows if r["sum_vc"])  / nk,
            "det_vc":  sum(1 for r in sk_rows if r["det_vc"])  / nk,
            "sum_pc":  sum(1 for r in sk_rows if r["sum_pc"])  / nk,
            "det_pc":  sum(1 for r in sk_rows if r["det_pc"])  / nk,
        }

    pass_q0 = vc_agree >= Q0_AGREE_THR and vc_fp_rate <= 0.10

    return {
        "n": n,
        "vc_agreement": vc_agree, "vc_fp_rate": vc_fp_rate, "vc_fn_rate": vc_fn_rate,
        "pc_agreement": pc_agree,
        "pass_q0": pass_q0,
        "per_scenario_key": per_sk,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15, help="Fresh episodes per cell (Q1/Q4)")
    args = ap.parse_args()
    N = args.n

    ACTOR_CONFIGS = [
        # (label, factory, pilot_scenario_key_for_transfer_lookup)
        ("original",    LandlordActor,                           "unk"),
        ("V3-default",  lambda: LandlordActorV3("default"),      "s02-screening-actor-starts-prod"),
        ("V3-brusque",  lambda: LandlordActorV3("brusque"),      "s02-brusque"),
        ("V3-coop",     lambda: LandlordActorV3("cooperative"),  "s02-cooperative"),
        ("V3-susp",     lambda: LandlordActorV3("suspicious"),   "s02-suspicious"),
    ]

    prod_policy = _make_production_policy()
    weak_policy = _make_weak_policy()

    # ── Q0: calibration ────────────────────────────────────────────────────────
    print("=== Q0: Measurement calibration (no API calls) ===")
    pilot_eps = load_pilot_episodes()
    print(f"  Loaded {len(pilot_eps)} pilot episodes")
    q0 = run_q0(pilot_eps)
    print(f"  VC agreement (detector vs summary): {q0['vc_agreement']:.3f}  "
          f"(threshold >= {Q0_AGREE_THR})")
    print(f"  VC false-positive rate:             {q0['vc_fp_rate']:.3f}  (threshold <= 0.10)")
    print(f"  VC false-negative rate:             {q0['vc_fn_rate']:.3f}")
    print(f"  PC agreement:                       {q0['pc_agreement']:.3f}")
    print(f"  Q0 PASS: {q0['pass_q0']}")
    print()
    print(f"  {'scenario_key':45}  {'n':>3}  {'sum_VC%':>7}  {'det_VC%':>7}  "
          f"{'sum_PC%':>7}  {'det_PC%':>7}")
    for sk, r in q0["per_scenario_key"].items():
        print(f"  {sk:45}  {r['n']:>3}  {r['sum_vc']*100:>6.1f}%  {r['det_vc']*100:>6.1f}%  "
              f"  {r['sum_pc']*100:>6.1f}%  {r['det_pc']*100:>6.1f}%")
    print()

    if not q0["pass_q0"]:
        print("  WARNING: Q0 FAILED — signal detector and state-machine measure different")
        print("  things.  All Q1-Q5 measurements will use the signal detector consistently")
        print("  for fresh episodes, but comparisons to pilot-derived CE labels are suspect.")
        print()

    # ── Q1-Q3: baseline characterisation ──────────────────────────────────────
    print(f"=== Q1-Q3: Baseline difficulty, pathway, depth (N={N} per cell) ===")
    cell_results = {}   # (scenario_label, actor_label) -> stats dict
    seed_offset  = 0
    total_cells  = len(SCENARIOS) * len(ACTOR_CONFIGS)
    cell_num     = 0

    t0 = time.time()
    for scenario_label, scenario_id in SCENARIOS.items():
        for actor_label, actor_factory, _ in ACTOR_CONFIGS:
            cell_num += 1
            label = f"[{cell_num:2}/{total_cells}] {scenario_label:15} × {actor_label:12}"
            print(f"\n  {label}")
            episodes = run_cell(
                scenario_label, scenario_id, actor_label, actor_factory,
                prod_policy, N, seed_offset, label)
            seed_offset += 100

            n = len(episodes)
            vc_rate  = sum(1 for e in episodes if e["vc"]) / n
            pc_rate  = sum(1 for e in episodes if e["pc"]) / n
            pc_bv    = sum(1 for e in episodes if e["pc_before_vc"]) / n   # Q2
            vc_no_pc = sum(1 for e in episodes if e["vc_without_pc"]) / n  # Q2
            pc_dead  = sum(1 for e in episodes if e["pc_dead_end"]) / n    # Q2
            avg_turns  = sum(e["n_turns"] for e in episodes) / n           # Q3
            multi_turn = sum(1 for e in episodes if e["n_turns"] >= 2) / n # Q3

            candidate = VC_CAND_LOW <= vc_rate <= VC_CAND_HIGH

            cell_results[(scenario_label, actor_label)] = {
                "vc": vc_rate, "pc": pc_rate,
                "pc_before_vc": pc_bv, "vc_without_pc": vc_no_pc, "pc_dead_end": pc_dead,
                "avg_turns": avg_turns, "multi_turn_frac": multi_turn,
                "candidate": candidate, "n": n,
                "episodes": episodes,
            }

    print(f"\n\n  Done in {time.time()-t0:.0f}s\n")

    # Print Q1-Q3 table
    print(f"  {'scenario':15}  {'actor':12}  {'n':>3}  {'VC%':>5}  {'PC%':>5}  "
          f"{'PC>VC%':>7}  {'VCnoPC%':>8}  {'PCdead%':>8}  "
          f"{'avgTrn':>6}  {'multi%':>6}  {'cand?':>5}")
    for (sl, al), r in cell_results.items():
        print(f"  {sl:15}  {al:12}  {r['n']:>3}  "
              f"{r['vc']*100:>4.1f}%  {r['pc']*100:>4.1f}%  "
              f"{r['pc_before_vc']*100:>6.1f}%  "
              f"{r['vc_without_pc']*100:>7.1f}%  "
              f"{r['pc_dead_end']*100:>7.1f}%  "
              f"{r['avg_turns']:>6.1f}  {r['multi_turn_frac']*100:>5.1f}%  "
              f"{'YES' if r['candidate'] else '---':>5}")

    candidate_cells = [(sl, al) for (sl, al), r in cell_results.items() if r["candidate"]]
    print(f"\n  Candidate cells (20-80% VC): {len(candidate_cells)}")
    for c in candidate_cells:
        r = cell_results[c]
        print(f"    {c[0]:15} × {c[1]:12}  VC={r['vc']*100:.1f}%")
    print()

    # ── Q4: policy discrimination ──────────────────────────────────────────────
    print(f"=== Q4: Policy discrimination — production vs weak policy ===")
    q4_results = {}

    if not candidate_cells:
        print("  No candidate cells — Q4 skipped (no valid arena exists)")
    else:
        for sl, al in candidate_cells:
            prod_vc = cell_results[(sl, al)]["vc"]
            scenario_id = SCENARIOS[sl]
            actor_factory = next(af for lbl, af, _ in ACTOR_CONFIGS if lbl == al)
            label = f"  Q4 weak: {sl:15} × {al:12}"
            print(f"\n{label}")
            weak_eps = run_cell(
                sl, scenario_id, al, actor_factory,
                weak_policy, N, seed_offset, label)
            seed_offset += 100
            weak_vc = sum(1 for e in weak_eps if e["vc"]) / max(len(weak_eps), 1)
            gap = prod_vc - weak_vc
            q4_results[(sl, al)] = {
                "prod_vc": prod_vc, "weak_vc": weak_vc, "gap": gap,
                "discriminates": gap >= Q4_GAP_THR,
            }

        print("\n\n  Q4 discrimination table:")
        print(f"  {'scenario':15}  {'actor':12}  {'prod_VC%':>8}  "
              f"{'weak_VC%':>8}  {'gap_pp':>7}  {'>=10pp?':>7}")
        for (sl, al), r in q4_results.items():
            print(f"  {sl:15}  {al:12}  {r['prod_vc']*100:>7.1f}%  "
                  f"{r['weak_vc']*100:>7.1f}%  {r['gap']*100:>+6.1f}pp  "
                  f"{'YES' if r['discriminates'] else 'NO':>7}")

    discriminating_cells = [(sl, al) for (sl, al), r in q4_results.items()
                             if r["discriminates"]]
    print(f"\n  Discriminating cells (gap >= 10pp): {len(discriminating_cells)}")
    print()

    # ── Q5: transfer compatibility ─────────────────────────────────────────────
    print("=== Q5: Transfer compatibility — candidate cells vs OPEN-71b ===")

    # Mapping actor label → pilot scenario key → transfer group membership
    # Based on OPEN-71b: s02-screening, s04, s05 are positive; others negative/zero
    ACTOR_PILOT_SK = {al: psk for al, _, psk in ACTOR_CONFIGS}
    POSITIVE_PILOT_SKS = POSITIVE_TRANSFER_GROUPS
    SCENARIOS_PILOT_SK = {
        "s02-screening": "s02-screening-actor-starts-prod",
        "s04-phone-req": "s04-phone-request-actor-starts-prod",
        "s05-reply":     "s05-reply-actor-starts-prod",
    }

    valid_arena_cells = []
    print(f"  {'scenario':15}  {'actor':12}  {'VC%':>5}  {'Q4_gap':>7}  "
          f"{'transfer':>10}  {'valid_arena':>12}")
    for sl, al in candidate_cells:
        r = cell_results[(sl, al)]
        vc_ok   = r["candidate"]
        q4_ok   = q4_results.get((sl, al), {}).get("discriminates", False)

        # Check transfer: is (scenario × actor) a positive-transfer cell?
        # Use scenario's pilot key AND actor's pilot key
        scen_psk  = SCENARIOS_PILOT_SK.get(sl, "unk")
        actor_psk = ACTOR_PILOT_SK.get(al, "unk")
        # Both the scenario key AND the actor variant should be in a positive-transfer group
        # The scenario contributes the base group; the actor variant is the differentiator
        # For default/V3-default: the actor proxies the pilot scenario key
        # For V3-variants, use actor_psk
        if al == "original":
            transfer_psk = scen_psk
        elif al == "V3-default":
            transfer_psk = scen_psk  # default actor, scenario determines transfer
        else:
            transfer_psk = actor_psk  # brusque/coop/susp → use actor-level transfer

        transfer_positive = transfer_psk in POSITIVE_PILOT_SKS
        valid = vc_ok and q4_ok and transfer_positive

        if valid:
            valid_arena_cells.append((sl, al))

        print(f"  {sl:15}  {al:12}  {r['vc']*100:>4.1f}%  "
              f"{q4_results.get((sl, al), {}).get('gap', 0)*100:>+6.1f}pp  "
              f"{'rho>0' if transfer_positive else 'rho<=0':>10}  "
              f"{'VALID' if valid else '---':>12}")

    print()

    # ── Verdict ────────────────────────────────────────────────────────────────
    print("=== Verdict ===")

    if not q0["pass_q0"]:
        verdict = "MEASUREMENT_MISMATCH"
        reason  = (f"Q0 FAILED: detector-summary VC agreement = "
                   f"{q0['vc_agreement']*100:.1f}% < {Q0_AGREE_THR*100:.0f}% threshold. "
                   "Signal detector and state-machine measure different things. "
                   "CE model was trained on state-machine labels; fresh-episode "
                   "evaluation with the signal detector is a systematic mismatch. "
                   "Fix the measurement path before any OPEN-74 rerun.")
    elif not candidate_cells:
        verdict = "NO_CANDIDATE_CELLS"
        reason  = ("Q1: all scenario × actor cells are at VC ceiling (100%) or floor (0%). "
                   "No room to measure policy improvement. "
                   "Actor redesign required: need an actor where baseline VC is 20-80%.")
    elif not discriminating_cells:
        verdict = "NO_DISCRIMINATION"
        reason  = ("Q1 found candidate cells but Q4 FAILED: production policy does not "
                   "outperform weak policy by >= 10pp in any candidate cell. "
                   "Scenarios exist with non-trivial VC but don't discriminate policy quality.")
    elif not valid_arena_cells:
        verdict = "STRUCTURAL_INCOMPATIBILITY"
        reason  = ("Q4 found discriminating cells but Q5 FAILED: no discriminating cell "
                   "overlaps with OPEN-71b positive-transfer groups (rho > 0). "
                   "Hard scenarios have negative CE transfer; positive-transfer scenarios "
                   "are at VC ceiling. CE proxy is predictive only in the regime that "
                   "makes measurement impossible. "
                   "Two paths forward: (A) redesign CE proxy to be predictive in hard "
                   "scenarios, or (B) redesign actor so PC is structurally on-path to "
                   "VC in positive-transfer scenarios.")
    else:
        verdict = "VALID_ARENA_FOUND"
        reason  = (f"Valid arena cells: {valid_arena_cells}. "
                   "These cells satisfy: 20-80% baseline VC, >=10pp production-vs-weak gap, "
                   "and positive CE->ER transfer from OPEN-71b. "
                   "Register these as the OPEN-74b precommit arena.")

    print(f"  {verdict}")
    print(f"  {reason}")
    print()

    # ── Q0 detail for structural interpretation ────────────────────────────────
    print("=== Structural interpretation of Q0 (no-API result) ===")
    print(f"  The pilot data was generated with the original LandlordActor.")
    print(f"  Original actor phone-share response: 'Sounds good. You can call me on")
    print(f"  07123456789 this evening and we can discuss a viewing.'")
    print(f"  Signal detector on this text: phone_captured=True, viewing_confirmed=False")
    print(f"  (because 'Sounds good' is not in confirmation_words list).")
    print(f"  Pilot summary VC={sum(1 for e in pilot_eps if e['_vc_sum'])/len(pilot_eps)*100:.1f}%")
    print(f"  was set by the state machine, not the signal detector.")
    print(f"  Signal detector VC on those same transcripts:")
    for sk, r in q0["per_scenario_key"].items():
        if r["sum_vc"] > 0 or r["det_vc"] > 0:
            print(f"    {sk}: summary={r['sum_vc']*100:.1f}%  detector={r['det_vc']*100:.1f}%")
    print()

    # ── Save results ───────────────────────────────────────────────────────────
    def strip_episodes(d):
        """Remove full transcript lists from saved JSON to keep file size down."""
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out[k] = {kk: vv for kk, vv in v.items() if kk != "episodes"}
            else:
                out[k] = v
        return out

    output = {
        "experiment": "OPEN-74A",
        "n_per_cell": N,
        "q0": {k: v for k, v in q0.items() if k != "per_episode"},
        "q1_q3_cells": {
            f"{sl}×{al}": strip_episodes(r)
            for (sl, al), r in cell_results.items()
        },
        "q4_cells": {
            f"{sl}×{al}": r for (sl, al), r in q4_results.items()
        },
        "candidate_cells":     [f"{sl}×{al}" for sl, al in candidate_cells],
        "discriminating_cells": [f"{sl}×{al}" for sl, al in discriminating_cells],
        "valid_arena_cells":    [f"{sl}×{al}" for sl, al in valid_arena_cells],
        "verdict": verdict,
        "reason":  reason,
    }
    outpath = os.path.join(os.path.dirname(__file__), "open74a_arena_audit_results.json")
    with open(outpath, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results: {outpath}")
    print(f"Verdict: {verdict}")


if __name__ == "__main__":
    main()
