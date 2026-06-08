"""
OPEN-74C: Learner-side headroom — is the CE score informative for SELECTING
which episodes teach?

Reframe of OPEN-74B: the arena CAN discriminate (weak 0-10% vs prod 100%);
the learner was at the top of the gradient. Place it at the BOTTOM instead:
a VanillaPolicy with NO playbook (no strategy, no conversation design, no
instruction to pursue viewings/phone). Then test whether CE-SELECTED
demonstrations beat random and anti-selected demonstrations.

Phase 0 gate: vanilla baseline VC must land in 20-80% on >=1 scenario
              (N=15/scenario). Else verdict NO_HEADROOM, stop.
Phase 1:      per qualifying scenario, 4 conditions x N=20:
              no-demo / random-demo (seed 74) / ce-top-demo / ce-bottom-demo

Pre-committed criteria (registered in PROJECT-GUIDE.md @ f9bdb9e):
  Mechanism GREEN : VC(ce-top) - VC(random) >= +10pp AND
                    VC(ce-top) - VC(ce-bottom) >= +10pp
  Few-shot-only   : VC(demo) > VC(no-demo) but ce-top ~ random
  Kill condition  : VC(ce-top) <= VC(random)  ->  Thread C closes

Usage:
  cd openrent-agent && python testfix/open74c_learner_headroom.py [--n-phase0 15] [--n 20]
"""

import argparse, glob, io, json, math, os, random, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

# Force UTF-8 stdout (cp1252 consoles choke on box-drawing/arrows)
# (idempotent guard — open74b_arena_repair also wraps on import)
if (hasattr(sys.stdout, "buffer")
        and (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") != "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import settings
from simulation.conversation_designs import VIEWING_FIRST_V1
from simulation.conversation_state import analyze_conversation_state
from simulation.engine.runtime_context import RuntimeContext
from simulation.lab import SCENARIO_BUILDERS
from simulation.policies.base import AgentPolicy
from app.ai.replies import generate_reply_result, _format_simulation_conversation
from simulation.sessions.transcript import ConversationTurn

# Reuse OPEN-74B components: actor, CE scoring, pilot loading (single
# measurement path), demo formatting.
from testfix.open74b_arena_repair import (
    LandlordActorV4, MAX_TURNS, POSITIVE_TRANSFER, SCENARIOS,
    _episode_features, _lr_train, _ce_score, _format_demo,
    load_pilot_episodes,
)

# ── constants ─────────────────────────────────────────────────────────────────

SEED_BASE   = 7700        # non-overlapping with 74 (9000), 74A (7400), 74B (6200)
RANDOM_DEMO_SEED = 74     # pre-committed
Q_DEMOS     = 5
VC_LOW, VC_HIGH = 0.20, 0.80
GREEN_MARGIN = 0.10       # +10pp

RESULTS = os.path.join(os.path.dirname(__file__), "open74c_learner_headroom_results.json")


# ── VanillaPolicy: no playbook ─────────────────────────────────────────────────

class VanillaPolicy(AgentPolicy):
    """
    Naturally weak learner: same model/temperature as production, but the
    prompt has NO playbook — no persona strategy, no conversation design,
    no instruction to pursue a viewing or phone number.  Its weakness comes
    from absence of strategy knowledge, not an explicit countermand
    (unlike OPEN-74B's WeakPolicy, which is invalid as a learner).
    """

    # APPARATUS NOTE (deviation from precommit "same temperature as production"):
    # SIMULATION_DEFAULT_TEMPERATURE = 0.0 makes the policy deterministic, so
    # cell VC% is degenerate at {0,100} BY CONSTRUCTION and the 20-80% band is
    # mechanically unreachable.  Stochastic decoding (0.7, the
    # generate_reply_result default) is required for the band to be expressible.
    # Fixed before any Phase-1 data was collected; applied to ALL conditions.
    TEMPERATURE = 0.7

    def __init__(self, demonstrations: list[str] | None = None):
        super().__init__(
            policy_id="vanilla-policy-v1",
            model=settings.OPENAI_REPLY_MODEL,
            temperature=self.TEMPERATURE,
        )
        self.demonstrations = demonstrations or []

    def build_prompt(self, conversation: str) -> str:
        demo_block = ""
        if self.demonstrations:
            demo_block = (
                "Here are some example conversations between tenants and "
                "landlords from this platform:\n\n"
                + "\n".join(self.demonstrations)
                + "\n--- End examples ---\n\n"
            )
        return (
            "You are a prospective tenant on a property rental platform. "
            "You messaged a landlord about a 2-bed flat in Manchester "
            "(rent 1500 pcm) and the landlord has replied.\n\n"
            + demo_block +
            "Continue the conversation naturally and briefly, as a real "
            "person would. Reply with the message text only.\n\n"
            "Conversation:\n"
            f"{conversation}\n\n"
            "Your reply:"
        )


# ── episode runner (same harness as OPEN-74B) ─────────────────────────────────

def run_episode(scenario_id: str, seed: int, policy) -> dict:
    actor = LandlordActorV4()
    scenario = SCENARIO_BUILDERS[scenario_id](MAX_TURNS, "actor_starts")
    ctx = RuntimeContext(session_id=str(uuid.uuid4()), deterministic_seed=seed)

    conv_turns, transcript_dicts = [], []
    actor_msg = actor.initial_message()
    conv_turns.append(ConversationTurn(
        speaker="actor", message=actor_msg, turn_index=0, source_event="ACTOR"))
    transcript_dicts.append({"speaker": "actor", "message": actor_msg})

    pc_first_turn = vc_first_turn = None
    final_state = "screening"
    turn_idx = 0

    for turn_idx in range(1, MAX_TURNS + 1):
        conv_str = _format_simulation_conversation(conv_turns)
        result = generate_reply_result(
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
            break

    return {
        "seed": seed, "n_turns": turn_idx,
        "transcript": [{"speaker": t.speaker, "message": t.message} for t in conv_turns],
        "pc": pc_first_turn is not None,
        "vc": vc_first_turn is not None,
        "pc_first_turn": pc_first_turn,
        "vc_first_turn": vc_first_turn,
        "pc_before_vc": (pc_first_turn is not None
                         and (vc_first_turn is None or pc_first_turn < vc_first_turn)),
        "final_state": final_state,
    }


MAX_WORKERS = 8  # episodes are independent; parallelism is API-latency-bound

def run_cell(scenario_label, scenario_id, policy, n, seed_base, label=""):
    eps = [None] * n
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(run_episode, scenario_id, seed_base + i, policy): i
                for i in range(n)}
        for fut in as_completed(futs):
            i = futs[fut]
            eps[i] = fut.result()
            done += 1
            print(f"  {label}  {done:2}/{n}  (seed {seed_base+i})  "
                  f"pc={eps[i]['pc']}  vc={eps[i]['vc']}  turns={eps[i]['n_turns']}",
                  flush=True)
    return eps


def cell_stats(eps):
    n = max(len(eps), 1)
    return {
        "n": n,
        "vc": sum(1 for e in eps if e["vc"]) / n,
        "pc": sum(1 for e in eps if e["pc"]) / n,
        "pc_before_vc": sum(1 for e in eps if e["pc_before_vc"]) / n,
        "avg_turns": sum(e["n_turns"] for e in eps) / n,
    }


# ── demo selection ─────────────────────────────────────────────────────────────

def build_demo_sets(pilot_eps):
    """Train CE model on pilot PC labels; return (top, random, bottom) demo lists.
    Pool = positive-transfer groups only.  Identical formatting everywhere."""
    pool = [e for e in pilot_eps if e["_sk"] in POSITIVE_TRANSFER]
    Xs = [_episode_features(e) for e in pilot_eps]
    ys = [1.0 if e["_pc"] else 0.0 for e in pilot_eps]
    w, b = _lr_train(Xs, ys)

    scored = sorted([(e, _ce_score(w, b, e)) for e in pool], key=lambda x: -x[1])
    top    = [e for e, _ in scored[:Q_DEMOS]]
    bottom = [e for e, _ in scored[-Q_DEMOS:]]
    rng    = random.Random(RANDOM_DEMO_SEED)
    rand   = rng.sample(pool, Q_DEMOS)

    fmt = lambda eps: [_format_demo(e, i + 1) for i, e in enumerate(eps)]
    meta = {
        "pool_size": len(pool),
        "top_scores":    [round(s, 4) for _, s in scored[:Q_DEMOS]],
        "bottom_scores": [round(s, 4) for _, s in scored[-Q_DEMOS:]],
        "top_pc":    [e["_pc"] for e in top],
        "top_vc":    [e["_vc"] for e in top],
        "bottom_pc": [e["_pc"] for e in bottom],
        "bottom_vc": [e["_vc"] for e in bottom],
        "rand_pc":   [e["_pc"] for e in rand],
        "rand_vc":   [e["_vc"] for e in rand],
    }
    return fmt(top), fmt(rand), fmt(bottom), meta


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-phase0", type=int, default=15)
    ap.add_argument("--n",        type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()

    # ── Phase 0: vanilla baseline headroom gate ──────────────────────────────
    print("=== Phase 0: vanilla baseline (headroom gate) ===")
    print(f"  Learner: VanillaPolicy (no playbook), model={settings.OPENAI_REPLY_MODEL}, "
          f"temp={VanillaPolicy.TEMPERATURE} (stochastic decoding; see apparatus note)")
    print(f"  Gate: VC in [{VC_LOW:.0%}, {VC_HIGH:.0%}] on >=1 scenario, "
          f"N={args.n_phase0}/scenario\n")

    vanilla = VanillaPolicy()
    phase0 = {}
    qualifying = []
    seed_off = 0
    for sl, (scenario_id, pilot_sk) in SCENARIOS.items():
        eps = run_cell(sl, scenario_id, vanilla, args.n_phase0,
                       SEED_BASE + seed_off, f"phase0 {sl}")
        seed_off += 100
        st = cell_stats(eps)
        in_band = VC_LOW <= st["vc"] <= VC_HIGH
        phase0[sl] = {**st, "in_band": in_band, "scenario_id": scenario_id}
        if in_band:
            qualifying.append(sl)
        print(f"  {sl:15}  VC={st['vc']*100:5.1f}%  PC={st['pc']*100:5.1f}%  "
              f"avg_turns={st['avg_turns']:.1f}  "
              f"{'IN BAND' if in_band else 'out of band'}")

    print()
    if not qualifying:
        print("  NO_HEADROOM: vanilla learner is also ceiling/floor everywhere.")
        print("  Per precommit: experiment stops; arena unusable at every learner strength.")
        out = {"experiment": "OPEN-74C", "verdict": "NO_HEADROOM",
               "phase0": phase0, "elapsed_s": round(time.time() - t0, 1)}
        with open(RESULTS, "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"\nResults: {RESULTS}\nVerdict: NO_HEADROOM")
        return

    print(f"  Qualifying scenarios: {qualifying}\n")

    # ── Demo sets ─────────────────────────────────────────────────────────────
    print("=== Demo selection (CE model on pilot PC labels) ===")
    pilot_eps = load_pilot_episodes()
    print(f"  Pilot episodes loaded: {len(pilot_eps)}")
    top_demos, rand_demos, bottom_demos, demo_meta = build_demo_sets(pilot_eps)
    print(f"  Pool (positive-transfer groups): {demo_meta['pool_size']}")
    print(f"  CE-top scores:    {demo_meta['top_scores']}  "
          f"pc={demo_meta['top_pc']}  vc={demo_meta['top_vc']}")
    print(f"  CE-bottom scores: {demo_meta['bottom_scores']}  "
          f"pc={demo_meta['bottom_pc']}  vc={demo_meta['bottom_vc']}")
    print(f"  Random (seed {RANDOM_DEMO_SEED}): "
          f"pc={demo_meta['rand_pc']}  vc={demo_meta['rand_vc']}\n")

    # ── Phase 1: demo conditions on qualifying scenarios ─────────────────────
    CONDITIONS = [
        ("no-demo",        None),
        ("random-demo",    rand_demos),
        ("ce-top-demo",    top_demos),
        ("ce-bottom-demo", bottom_demos),
    ]

    print(f"=== Phase 1: demo conditions (N={args.n} per cell) ===\n")
    results = {}
    seed_off = 1000
    for sl in qualifying:
        scenario_id = phase0[sl]["scenario_id"]
        results[sl] = {}
        for cond_name, demos in CONDITIONS:
            policy = VanillaPolicy(demonstrations=demos)
            lbl = f"{sl} {cond_name}"
            print(f"  [{lbl}]")
            eps = run_cell(sl, scenario_id, policy, args.n,
                           SEED_BASE + seed_off, lbl)
            seed_off += 100
            results[sl][cond_name] = cell_stats(eps)

    # ── Verdict per precommit ─────────────────────────────────────────────────
    print("\n" + "-" * 80)
    print("\n=== OPEN-74C results: VC% by condition x scenario ===\n")
    hdr = f"  {'scenario':15}  {'no-demo':>8}  {'random':>8}  {'ce-top':>8}  {'ce-bot':>8}  {'top-rand':>9}  {'top-bot':>8}"
    print(hdr)

    verdicts = {}
    for sl in qualifying:
        r = results[sl]
        vc_no, vc_r  = r["no-demo"]["vc"], r["random-demo"]["vc"]
        vc_t, vc_b   = r["ce-top-demo"]["vc"], r["ce-bottom-demo"]["vc"]
        d_tr, d_tb   = vc_t - vc_r, vc_t - vc_b

        if d_tr >= GREEN_MARGIN and d_tb >= GREEN_MARGIN:
            v = "MECHANISM_GREEN"
        elif vc_t <= vc_r:
            v = "KILL"            # CE selection carries no teaching signal
        elif max(vc_r, vc_t, vc_b) > vc_no and abs(d_tr) < GREEN_MARGIN:
            v = "FEW_SHOT_ONLY"   # demos transfer, selection decorative
        else:
            v = "INCONCLUSIVE"
        verdicts[sl] = v
        print(f"  {sl:15}  {vc_no*100:>7.1f}%  {vc_r*100:>7.1f}%  "
              f"{vc_t*100:>7.1f}%  {vc_b*100:>7.1f}%  "
              f"{d_tr*100:>+8.1f}pp  {d_tb*100:>+7.1f}pp   {v}")

    # Overall: GREEN if any scenario GREEN; KILL only if all qualifying are KILL
    if any(v == "MECHANISM_GREEN" for v in verdicts.values()):
        overall = "MECHANISM_GREEN"
    elif all(v == "KILL" for v in verdicts.values()):
        overall = "KILL"
    elif any(v == "FEW_SHOT_ONLY" for v in verdicts.values()):
        overall = "FEW_SHOT_ONLY"
    else:
        overall = "INCONCLUSIVE"

    out = {
        "experiment": "OPEN-74C",
        "precommit": "PROJECT-GUIDE.md @ f9bdb9e",
        "phase0": phase0,
        "qualifying": qualifying,
        "demo_meta": demo_meta,
        "results": results,
        "verdicts": verdicts,
        "overall": overall,
        "n_phase0": args.n_phase0, "n": args.n,
        "seed_base": SEED_BASE, "random_demo_seed": RANDOM_DEMO_SEED,
        "elapsed_s": round(time.time() - t0, 1),
    }
    with open(RESULTS, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nResults: {RESULTS}")
    print(f"Verdict: {overall}")


if __name__ == "__main__":
    main()
