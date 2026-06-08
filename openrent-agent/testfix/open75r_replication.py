"""
OPEN-75R: Replication/stability stress-test of OPEN-75's LOOP_GREEN.

Mechanism FROZEN (imports the OPEN-75/74C harness verbatim): VanillaPolicy
temp 0.7, LandlordActorV4, CE = PC detector on own rollouts, eval = VC,
Q=5, same demo formatting, same scenarios, same arms.

Added (measurement only):
  R=3 replicates (seed-bases 11000/12000/13000), fresh round-0 pool each.
  K=3 random-select draws per replicate (seeds 75/76/77), each its own arm.
  Sparse pre-committed: pool CE-positive rate p <= 0.25.
  Diagnostics: zero-success draw rate vs (1-p)^Q; expected-vs-observed
  random VC; ce vs any-success-random subgroup.

Precommit (PROJECT-GUIDE.md @ f96cd2c):
  GREEN : sparse cells: mean[ce]-mean[rand] >= +20pp AND mean[ce]-mean[r0]
          >= +20pp AND ce>within-rep-rand-mean in strict majority of sparse
          reps AND no r2 collapse (r2 >= r1ce-10pp everywhere sparse)
  YELLOW: ce-r0 >= +20pp but ce-rand < +20pp; or seed-fragile
  RED   : mean[ce] <= mean[rand] on sparse cells, or any r2 collapse
  NO_SPARSE_POOLS if all 6 pools rich.

Usage:
  cd openrent-agent && python testfix/open75r_replication.py [--reps 0,1,2]
"""

import argparse, io, json, os, sys, time

if (hasattr(sys.stdout, "buffer")
        and (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") != "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import testfix.open74c_learner_headroom as o74c
o74c.MAX_WORKERS = 16   # 900-episode budget; episodes independent, API-bound

from testfix.open74c_learner_headroom import VanillaPolicy, run_cell, cell_stats
from testfix.open75_closed_loop import (
    ce_select, random_select, fmt_demos, pool_summary, Q_DEMOS,
)

# ── frozen design constants ───────────────────────────────────────────────────

SEED_BASES   = [11000, 12000, 13000]   # non-overlapping with all prior OPENs
RANDOM_SEEDS = [75, 76, 77]
SPARSE_P     = 0.25
GREEN_MARGIN = 0.20
STAB_MARGIN  = 0.10
N_POOL, N_ARM = 30, 20

SCENARIOS = {
    "s02-screening": "outreach-screening-before-phone",
    "s04-phone-req":  "outreach-phone-request",
}

RESULTS = os.path.join(os.path.dirname(__file__), "open75r_replication_results.json")


def save(out):
    with open(RESULTS, "w") as fh:
        json.dump(out, fh, indent=2)


def run_replicate(rep_idx, seed_base):
    rep = {"seed_base": seed_base, "scenarios": {}}
    seed_off = 0
    for sl, scenario_id in SCENARIOS.items():
        print(f"\n━━━ rep{rep_idx} {sl} (seed_base {seed_base}) ━━━")
        res = {}

        # Round 0: fresh self-rollout pool
        print(f"  [rep{rep_idx} r0 {sl}]")
        pool = run_cell(sl, scenario_id, VanillaPolicy(), N_POOL,
                        seed_base + seed_off, f"rep{rep_idx} r0 {sl}")
        seed_off += 100
        ps = pool_summary(pool)
        res["round0"] = {**cell_stats(pool), "pool": ps}
        res["sparse"] = ps["pc_rate"] <= SPARSE_P
        print(f"  r0: VC={res['round0']['vc']*100:.1f}%  p={ps['pc_rate']*100:.1f}%  "
              f"CE-pos {ps['n_ce_positive']}/{ps['n']}  "
              f"{'SPARSE' if res['sparse'] else 'rich'}")

        if ps["n_ce_positive"] == 0:
            res["verdict_note"] = "NO_BOOTSTRAP"
            rep["scenarios"][sl] = res
            continue

        # ce-select arm (one, deterministic given pool)
        ce_eps = ce_select(pool)
        res["ce_demos_pc"] = [e["pc"] for e in ce_eps]
        print(f"  [rep{rep_idx} r1 ce {sl}]  demos pc={res['ce_demos_pc']}")
        r1_ce_pool = run_cell(sl, scenario_id,
                              VanillaPolicy(demonstrations=fmt_demos(ce_eps)),
                              N_ARM, seed_base + seed_off, f"rep{rep_idx} r1ce {sl}")
        seed_off += 100
        res["r1_ce"] = cell_stats(r1_ce_pool)

        # K random-select arms
        res["r1_random"] = []
        for rs in RANDOM_SEEDS:
            rd_eps = random_select(pool, seed=rs)
            n_succ = sum(1 for e in rd_eps if e["pc"])
            print(f"  [rep{rep_idx} r1 rand(seed {rs}) {sl}]  demos pc: {n_succ}/{Q_DEMOS}")
            eps = run_cell(sl, scenario_id,
                           VanillaPolicy(demonstrations=fmt_demos(rd_eps)),
                           N_ARM, seed_base + seed_off, f"rep{rep_idx} r1rd{rs} {sl}")
            seed_off += 100
            res["r1_random"].append(
                {"seed": rs, "n_success_demos": n_succ, **cell_stats(eps)})

        # no-demo stationarity arm
        print(f"  [rep{rep_idx} r1 no-demo {sl}]")
        nd = run_cell(sl, scenario_id, VanillaPolicy(), N_ARM,
                      seed_base + seed_off, f"rep{rep_idx} r1nd {sl}")
        seed_off += 100
        res["r1_no_demo"] = cell_stats(nd)

        # Round 2: ce re-select from own r1 rollouts
        n_ce_pos_r1 = sum(1 for e in r1_ce_pool if e["pc"])
        if n_ce_pos_r1 == 0:
            res["round2"] = {"vc": 0.0, "note": "no CE-positive r1 rollouts; collapse"}
        else:
            ce2 = ce_select(r1_ce_pool)
            print(f"  [rep{rep_idx} r2 ce {sl}]")
            eps2 = run_cell(sl, scenario_id,
                            VanillaPolicy(demonstrations=fmt_demos(ce2)),
                            N_ARM, seed_base + seed_off, f"rep{rep_idx} r2 {sl}")
            seed_off += 100
            res["round2"] = cell_stats(eps2)

        rand_mean = sum(r["vc"] for r in res["r1_random"]) / len(res["r1_random"])
        print(f"  rep{rep_idx} {sl}: r0={res['round0']['vc']*100:.0f}%  "
              f"nd={res['r1_no_demo']['vc']*100:.0f}%  "
              f"rand(mean of {len(RANDOM_SEEDS)})={rand_mean*100:.0f}%  "
              f"ce={res['r1_ce']['vc']*100:.0f}%  r2={res['round2']['vc']*100:.0f}%")
        rep["scenarios"][sl] = res
    return rep


def aggregate(out):
    """Pre-committed verdict + diagnostics over all completed replicates."""
    sparse_cells, rich_cells, law_points = [], [], []
    zero_draws, draws = 0, 0
    fail_cells, succ_cells = [], []   # random cells by demo-success content

    for rep in out["replicates"]:
        for sl, res in rep["scenarios"].items():
            if "r1_ce" not in res:
                continue
            p = res["round0"]["pool"]["pc_rate"]
            rand_vcs = [r["vc"] for r in res["r1_random"]]
            rand_mean = sum(rand_vcs) / len(rand_vcs)
            cell = {
                "rep_seed_base": rep["seed_base"], "scenario": sl, "p": p,
                "r0_vc": res["round0"]["vc"], "ce_vc": res["r1_ce"]["vc"],
                "rand_vcs": rand_vcs, "rand_mean": rand_mean,
                "r2_vc": res["round2"]["vc"],
                "r2_collapse": res["round2"]["vc"] < res["r1_ce"]["vc"] - STAB_MARGIN,
                "gap_vs_rand_mean": res["r1_ce"]["vc"] - rand_mean,
            }
            (sparse_cells if res["sparse"] else rich_cells).append(cell)
            law_points.append({"p": p, "ce_minus_rand_pp":
                               round((res["r1_ce"]["vc"] - rand_mean) * 100, 1)})
            for r in res["r1_random"]:
                draws += 1
                if r["n_success_demos"] == 0:
                    zero_draws += 1
                    fail_cells.append(r["vc"])
                else:
                    succ_cells.append(r["vc"])

    diag = {
        "law_points": law_points,
        "zero_success_draws": f"{zero_draws}/{draws}",
        "v_fail_mean": (sum(fail_cells)/len(fail_cells)) if fail_cells else None,
        "v_succ_mean": (sum(succ_cells)/len(succ_cells)) if succ_cells else None,
        "n_sparse_cells": len(sparse_cells), "n_rich_cells": len(rich_cells),
    }

    if not sparse_cells:
        return "NO_SPARSE_POOLS", diag, sparse_cells, rich_cells

    m = lambda k: sum(c[k] for c in sparse_cells) / len(sparse_cells)
    mean_ce, mean_r0 = m("ce_vc"), m("r0_vc")
    mean_rand = sum(c["rand_mean"] for c in sparse_cells) / len(sparse_cells)
    d_rand, d_r0 = mean_ce - mean_rand, mean_ce - mean_r0
    majority = sum(1 for c in sparse_cells if c["gap_vs_rand_mean"] > 0)
    majority_ok = majority * 2 > len(sparse_cells)
    collapse = any(c["r2_collapse"] for c in sparse_cells)

    diag.update({
        "sparse_mean_ce": round(mean_ce, 3), "sparse_mean_rand": round(mean_rand, 3),
        "sparse_mean_r0": round(mean_r0, 3),
        "sparse_d_rand_pp": round(d_rand*100, 1), "sparse_d_r0_pp": round(d_r0*100, 1),
        "majority": f"{majority}/{len(sparse_cells)}", "r2_collapse_any": collapse,
    })

    if mean_ce <= mean_rand or collapse:
        v = "RED"
    elif d_rand >= GREEN_MARGIN and d_r0 >= GREEN_MARGIN and majority_ok:
        v = "GREEN"
    elif d_r0 >= GREEN_MARGIN or not majority_ok:
        v = "YELLOW"
    else:
        v = "YELLOW"
    return v, diag, sparse_cells, rich_cells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", default="0,1,2",
                    help="comma-separated replicate indices to run")
    args = ap.parse_args()
    rep_ids = [int(x) for x in args.reps.split(",")]
    t0 = time.time()

    # Resume support: load existing results if present
    if os.path.exists(RESULTS):
        with open(RESULTS) as fh:
            out = json.load(fh)
        done = {r["seed_base"] for r in out.get("replicates", [])}
    else:
        out = {"experiment": "OPEN-75R", "precommit": "PROJECT-GUIDE.md @ f96cd2c",
               "replicates": []}
        done = set()

    print("=== OPEN-75R: replication/stability stress-test (mechanism frozen) ===")
    print(f"  R={len(SEED_BASES)} seed-bases, K={len(RANDOM_SEEDS)} random draws/rep, "
          f"sparse p<={SPARSE_P}, workers={o74c.MAX_WORKERS}")

    for i in rep_ids:
        sb = SEED_BASES[i]
        if sb in done:
            print(f"  rep{i} (seed_base {sb}) already done — skipping")
            continue
        rep = run_replicate(i, sb)
        out["replicates"].append(rep)
        save(out)   # incremental save after each replicate

    verdict, diag, sparse_cells, rich_cells = aggregate(out)
    out["diagnostics"] = diag
    out["sparse_cells"] = sparse_cells
    out["rich_cells"] = rich_cells
    out["verdict"] = verdict
    out["elapsed_s"] = round(time.time() - t0, 1)
    save(out)

    print("\n" + "-" * 80)
    print("=== Aggregate (sparse cells) ===")
    for k, v in diag.items():
        if k != "law_points":
            print(f"  {k}: {v}")
    print("  selection-law points (p, ce-rand pp):",
          [(round(lp['p'],2), lp['ce_minus_rand_pp']) for lp in diag["law_points"]])
    print(f"\nResults: {RESULTS}")
    print(f"Verdict: {verdict}")


if __name__ == "__main__":
    main()
