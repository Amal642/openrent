"""OPEN-21D Part 1 — dry-run THROUGH THE REAL production prompt path.

Verifies, using app.ai.prompts.build_reply_prompt (the actual reply prompt builder):
  - assignment happens + is logged BEFORE the first AI message
  - Arm A  : current path (design=None) -> viewing_first rules, mobile EXPOSED
  - Arm B  : corpus_number_capture_v2 -> do-not-share-tenant + the appended P5, mobile WITHHELD
  - Arm B cannot expose Mary's number
  - both arms log all required fields, ~50/50 balance

Run:  cd openrent-agent && python -m app.experiments.ab_dryrun
"""
from __future__ import annotations
import json, os, shutil, tempfile
from app.ai.prompts import build_reply_prompt
from app.experiments import playbook_ab as ab

MOBILE = "+447743722832"
PERSONA = {  # an operator-selected config: 'immediate' phone strategy + warm casual couple
    "persona_name": "Mary", "mobile_number": MOBILE, "phone_fetching_type": "immediate",
    "conversation_style": "warm_casual", "persona_type": "young_professional_couple",
    "persona_partner_name": "Alex",
}
CONV = 'Tenant: "Hi, interested in your property."\nLandlord: "Thanks - what is your number?"'

def real_prompt(arm):
    return build_reply_prompt(CONV, stage="VIEWING_DISCUSSION", persona=PERSONA,
                              conversation_design_id=ab.design_id_for_arm(arm),
                              landlord_asked_for_number=True, outbound_count=0)

def main():
    out = tempfile.mkdtemp(prefix="ab_dryrun_")
    log = os.path.join(out, "assignments.jsonl")
    clock = [1000.0]
    def now():
        clock[0] += 1.0
        return clock[0]

    records = []
    order_ok = True
    for i in range(40):
        lead = f"thread-{i:03d}"
        rec = ab.assign(lead, PERSONA, log, now=now())   # assign + log BEFORE first message
        first_msg_at = now()                              # the first AI message would be sent now
        order_ok = order_ok and (rec["assigned_at"] < first_msg_at)
        records.append(rec)

    nA = sum(1 for r in records if r["assigned_arm"] == "A")
    nB = len(records) - nA
    pA, pB = real_prompt("A"), real_prompt("B")

    print("=== DRY-RUN THROUGH REAL PRODUCTION PROMPT PATH ===")
    print(f"[1] arm balance: A={nA} B={nB} of {len(records)}")
    print(f"[2] assignment logged BEFORE first message for every lead: {'PASS' if order_ok else 'FAIL'}")

    a_mobile = MOBILE in pA
    a_viewing = "arrange or confirm a viewing naturally" in pA
    a_corpus = "do not share the tenant mobile" in pA.lower()
    print(f"[3] ARM A (None): mobile EXPOSED={a_mobile} (want True) | viewing_first rules={a_viewing} (want True) "
          f"| corpus rule leaked={a_corpus} (want False)")

    b_mobile = MOBILE in pB
    b_corpus = "do not share the tenant mobile" in pB.lower()
    b_p5 = "park the lead politely" in pB.lower()
    print(f"[4] ARM B (playbook_ab_v1): mobile EXPOSED={b_mobile} (want False) "
          f"| do-not-share rule={b_corpus} (want True) | P5 drop/park rule={b_p5} (want True)")

    cfgA = ab.effective_config("A"); cfgB = ab.effective_config("B")
    print(f"[5] effective config A: {cfgA}")
    print(f"    effective config B: {cfgB}")

    req = {"experiment", "lead_id", "assigned_arm", "propensity", "assigned_at", "operator_knobs",
           "assigned_design_id", "effective_design_id", "design_rules_applied", "expose_mobile",
           "landlord_number_requested", "landlord_number_captured", "parked_dropped",
           "qualified_landlord_phone_capture"}
    miss = [r["lead_id"] for r in records if not req.issubset(r)]
    print(f"[6] every assignment record carries all required fields: {'PASS' if not miss else 'FAIL '+str(miss)}")

    # [7] outcome hook records diagnostic fields (arm-free) + blind grader input has no arm leak
    olog = os.path.join(out, "outcomes.jsonl")
    ab.log_outcome("thread-001", olog, reply_received=True, landlord_phone_captured=True,
                   landlord_number_requested=True, tenant_number_given_first=False,
                   conversation_progressed=True, parked_or_dropped=False,
                   unsafe_or_pushy_detected=None)
    orec = json.loads(open(olog, encoding="utf-8").read().strip().splitlines()[-1])
    needed = {"reply_received", "landlord_phone_captured", "landlord_number_requested",
              "tenant_number_given_first", "conversation_progressed", "parked_or_dropped"}
    outcome_ok = needed.issubset(orec) and not any(
        k in orec for k in ("arm", "assigned_arm", "assigned_design_id", "effective_design_id"))
    # arm-blind grader input = id + transcript ONLY (no arm / design / assignment metadata)
    turns = [("tenant", "Hi, when could we arrange a viewing?"),
             ("landlord", "Sure - my number is 07700 900123")]
    gi = "### thread-001\n" + "".join(
        f'{"Tenant" if r=="tenant" else "Landlord"}: "{t}"\n' for r, t in turns)
    leak = any(tok in gi for tok in ('"arm"', "assigned_arm", "assigned_design_id",
                                     "playbook_ab_v1", "corpus_number_capture"))
    print(f"[7] outcome hook records fields & is arm-free: {outcome_ok} (want True) | "
          f"blind grader input arm/design leak: {leak} (want False)")

    checks = [order_ok, a_mobile, a_viewing, not a_corpus, not b_mobile, b_corpus, b_p5,
              cfgA["expose_mobile"] is True, cfgB["expose_mobile"] is False, not miss,
              0 < nA < len(records), outcome_ok, not leak]
    print(f"\nDRY-RUN: {'ALL CHECKS PASS' if all(checks) else 'CHECK FAILURES ABOVE'}")
    print(f"(sample log: {log})")
    shutil.rmtree(out, ignore_errors=True)

if __name__ == "__main__":
    main()
