"""
OPEN-75: The closed loop — CE-filtered self-generated demonstrations.
Zero exogenous data, zero ER labels.

OPEN-74C killed CE selection over an exogenous already-good pool. A
self-improvement loop draws from the policy's OWN rollouts, where success is
rare (~5-20% at vanilla strength): a random Q=5 draw has ~44% probability of
zero successes (0.85^5) — the regime where 74C's component GREEN (+65/70pp
vs all-failure demo sets) showed selection matters.

Loop:
  Round 0: vanilla policy, no demos, N=30 self-rollouts/scenario.
           CE = phone_captured detector on own rollout (free, CE signal).
  Round 1: three arms x N=20:
             ce-select     : top-5 own rollouts by CE (PC first, fewer turns tiebreak)
             random-select : 5 uniform own rollouts (seed 75, SAME pool)
             no-demo       : stationarity baseline
  Round 2: ce-select arm only — re-select from its OWN round-1 rollouts,
           run N=20 again (stability / collapse check).

Goodhart guard: selection uses CE (PC) only; evaluation uses VC (ER analog).

Pre-committed (PROJECT-GUIDE.md @ 1e3f76e):
  LOOP GREEN : VC(ce) - VC(rand) >= +20pp AND VC(ce) - VC(round0) >= +20pp
  Stability  : round2 VC(ce) >= round1 VC(ce) - 10pp
  Kill       : VC(ce) <= VC(rand)
  NO_BOOTSTRAP: zero CE-positive round-0 rollouts in a scenario

Usage:
  cd openrent-agent && python testfix/open75_closed_loop.py [--n-pool 30] [--n 20]
"""

import argparse, io, json, os, random, sys, time

# Idempotent UTF-8 stdout (cross-import with other testfix scripts)
if (hasattr(sys.stdout, "buffer")
        and (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") != "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Reuse the validated OPEN-74C harness: VanillaPolicy, parallel run_cell,
# cell_stats (single measurement path: signal detector throughout).
from testfix.open74c_learner_headroom import (
    VanillaPolicy, run_cell, cell_stats,
)

# ── constants ─────────────────────────────────────────────────────────────────

SEED_BASE        = 8800   # non-overlapping: 74(9000) 74A(7400) 74B(6200) 74C(7700)
RANDOM_SEL_SEED  = 75     # pre-committed
Q_DEMOS          = 5
GREEN_MARGIN     = 0.20   # +20pp
STABILITY_MARGIN = 0.10   # round2 >= round1 - 10pp

# 74C in-band scenarios only
SCENARIOS = {
    "s02-screening": "outreach-screening-before-phone",
    "s04-phone-req":  "outreach-phone-request",
}

RESULTS = os.path.join(os.path.dirname(__file__), "open75_closed_loop_results.json")


# ── self-rollout demo formatting ──────────────────────────────────────────────
# Same neutral framing as 74C (no "went well" wording — selection is the only
# difference between arms).  Outcome tag uses the CE signal (PC) only; VC is
# never shown to the learner (Goodhart guard).

def format_self_demo(ep, idx):
    lines = [f"--- Example {idx} ---"]
    for row in ep["transcript"]:
        speaker = "Landlord" if row["speaker"] == "actor" else "You (tenant)"
        lines.append(f"{speaker}: {row['message']}")
    lines.append(f"[Result: {'phone number obtained' if ep['pc'] else 'no phone number obtained'}]")
    lines.append("")
    return "\n".join(lines)


def ce_select(pool, q=Q_DEMOS):
    """Top-q by CE: PC-fired first, fewer turns as tiebreak (more efficient)."""
    ranked = sorted(pool, key=lambda e: (-int(e["pc"]), e["n_turns"]))
    return ranked[:min(q, len(pool))]


def random_select(pool, q=Q_DEMOS, seed=RANDOM_SEL_SEED):
    return random.Random(seed).sample(pool, min(q, len(pool)))


def fmt_demos(eps):
    return [format_self_demo(e, i + 1) for i, e in enumerate(eps)]


def pool_summary(pool):
    n = max(len(pool), 1)
    return {
        "n": len(pool),
        "pc_rate": sum(1 for e in pool if e["pc"]) / n,
        "vc_rate": sum(1 for e in pool if e["vc"]) / n,
        "n_ce_positive": sum(1 for e in pool if e["pc"]),
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pool", type=int, default=30)
    ap.add_argument("--n",      type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()

    out = {"experiment": "OPEN-75", "precommit": "PROJECT-GUIDE.md @ 1e3f76e",
           "n_pool": args.n_pool, "n": args.n,
           "seed_base": SEED_BASE, "random_sel_seed": RANDOM_SEL_SEED,
           "scenarios": {}}

    print("=== OPEN-75: closed-loop CE-filtered self-demonstrations ===")
    print(f"  Learner: VanillaPolicy temp={VanillaPolicy.TEMPERATURE}; "
          f"CE = PC detector on own rollouts; eval = VC (ER analog)")
    print(f"  Round 0 pool N={args.n_pool}/scenario; arms N={args.n}/cell\n")

    seed_off = 0
    verdicts = {}

    for sl, scenario_id in SCENARIOS.items():
        print(f"━━━ Scenario {sl} ━━━")
        res = {}

        # ── Round 0: self-rollout pool (no demos) ─────────────────────────────
        print(f"  [round0 pool {sl}]")
        pool = run_cell(sl, scenario_id, VanillaPolicy(), args.n_pool,
                        SEED_BASE + seed_off, f"r0 {sl}")
        seed_off += 100
        ps = pool_summary(pool)
        r0_stats = cell_stats(pool)
        res["round0"] = {**r0_stats, "pool": ps}
        print(f"  round0: VC={r0_stats['vc']*100:.1f}%  PC={r0_stats['pc']*100:.1f}%  "
              f"CE-positive rollouts: {ps['n_ce_positive']}/{ps['n']}")

        if ps["n_ce_positive"] == 0:
            print(f"  NO_BOOTSTRAP: zero CE-positive rollouts — loop cannot start here.\n")
            verdicts[sl] = "NO_BOOTSTRAP"
            res["verdict"] = "NO_BOOTSTRAP"
            out["scenarios"][sl] = res
            continue

        # ── Selection (CE vs random, SAME pool) ───────────────────────────────
        ce_demos_eps   = ce_select(pool)
        rand_demos_eps = random_select(pool)
        res["selection"] = {
            "ce_pc":   [e["pc"] for e in ce_demos_eps],
            "ce_vc":   [e["vc"] for e in ce_demos_eps],     # logged, never shown to learner
            "ce_turns":[e["n_turns"] for e in ce_demos_eps],
            "rand_pc": [e["pc"] for e in rand_demos_eps],
            "rand_vc": [e["vc"] for e in rand_demos_eps],
        }
        print(f"  ce-select demos:     pc={res['selection']['ce_pc']}")
        print(f"  random-select demos: pc={res['selection']['rand_pc']}")

        # ── Round 1: three arms ───────────────────────────────────────────────
        arms = {
            "ce-select":     fmt_demos(ce_demos_eps),
            "random-select": fmt_demos(rand_demos_eps),
            "no-demo":       None,
        }
        r1 = {}
        r1_pools = {}
        for arm, demos in arms.items():
            print(f"  [round1 {sl} {arm}]")
            eps = run_cell(sl, scenario_id, VanillaPolicy(demonstrations=demos),
                           args.n, SEED_BASE + seed_off, f"r1 {sl} {arm}")
            seed_off += 100
            r1[arm] = cell_stats(eps)
            r1_pools[arm] = eps
        res["round1"] = r1

        # ── Round 2: stability (ce-select arm, re-select from OWN r1 rollouts) ─
        r1_ce_pool = r1_pools["ce-select"]
        n_ce_pos_r1 = sum(1 for e in r1_ce_pool if e["pc"])
        if n_ce_pos_r1 == 0:
            res["round2"] = {"note": "no CE-positive r1 rollouts; collapse"}
            r2_vc = 0.0
        else:
            ce2 = ce_select(r1_ce_pool)
            res["round2_selection_pc"] = [e["pc"] for e in ce2]
            print(f"  [round2 {sl} ce-select (from own r1 rollouts)]")
            eps2 = run_cell(sl, scenario_id,
                            VanillaPolicy(demonstrations=fmt_demos(ce2)),
                            args.n, SEED_BASE + seed_off, f"r2 {sl}")
            seed_off += 100
            res["round2"] = cell_stats(eps2)
            r2_vc = res["round2"]["vc"]

        # ── Verdict per precommit ─────────────────────────────────────────────
        vc_ce, vc_rd, vc_nd = r1["ce-select"]["vc"], r1["random-select"]["vc"], r1["no-demo"]["vc"]
        vc_r0 = r0_stats["vc"]
        d_rand = vc_ce - vc_rd
        d_base = vc_ce - vc_r0
        stable = r2_vc >= vc_ce - STABILITY_MARGIN

        if vc_ce <= vc_rd:
            v = "KILL"
        elif d_rand >= GREEN_MARGIN and d_base >= GREEN_MARGIN:
            v = "LOOP_GREEN" if stable else "LOOP_GREEN_UNSTABLE"
        else:
            v = "INCONCLUSIVE"
        verdicts[sl] = v
        res["verdict"] = v
        res["margins"] = {"ce_minus_rand_pp": round(d_rand*100, 1),
                          "ce_minus_round0_pp": round(d_base*100, 1),
                          "round2_vc": round(r2_vc*100, 1), "stable": stable}
        out["scenarios"][sl] = res

        print(f"\n  {sl}: r0={vc_r0*100:.1f}%  no-demo={vc_nd*100:.1f}%  "
              f"rand={vc_rd*100:.1f}%  ce={vc_ce*100:.1f}%  r2(ce)={r2_vc*100:.1f}%")
        print(f"  ce-rand={d_rand*100:+.1f}pp  ce-r0={d_base*100:+.1f}pp  "
              f"stable={stable}  ->  {v}\n")

    # ── Overall ───────────────────────────────────────────────────────────────
    vs = set(verdicts.values())
    if any(v.startswith("LOOP_GREEN") for v in vs):
        overall = ("LOOP_GREEN" if "LOOP_GREEN" in vs else "LOOP_GREEN_UNSTABLE")
    elif vs == {"KILL"}:
        overall = "KILL"
    elif "NO_BOOTSTRAP" in vs and len(vs) == 1:
        overall = "NO_BOOTSTRAP"
    else:
        overall = "MIXED"

    out["verdicts"] = verdicts
    out["overall"] = overall
    out["elapsed_s"] = round(time.time() - t0, 1)
    with open(RESULTS, "w") as fh:
        json.dump(out, fh, indent=2)

    print("-" * 80)
    print(f"Per-scenario verdicts: {verdicts}")
    print(f"Results: {RESULTS}")
    print(f"Verdict: {overall}")


if __name__ == "__main__":
    main()
