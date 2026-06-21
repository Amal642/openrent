"""OPEN-21D Part 1 - playbook A/B routing + assignment + logging (production).

Locked 2-arm A/B (see the hippocampus repo: experiments/open21d-real-conversations/PLAYBOOK-AB-SPEC.md):

  Arm A (control)  = baseline capture AI on the CURRENT production path:
      conversation_design_id = None  -> _DESIGN_RULES falls back to viewing_first_v1,
      mobile EXPOSED, operator's selected knobs (phone_fetching_type / conversation_style) kept.
  Arm B (playbook) = capture AI using the dedicated playbook_ab_v1 design
      (a clone of corpus_number_capture_v2 plus P5 'drop/park dead leads'):
      mobile WITHHELD (expose_mobile=False, since the design is in LANDLORD_NUMBER_CAPTURE_DESIGNS),
      landlord-number-first policy, answer-screening-first, respect-refusal.

Note: the shared human-operated message history is REFERENCE/BASELINE only - it is NOT arm A.
Both arms are AI. This module does NOT change message generation; it only (1) assigns the arm
per lead before the first AI message, (2) tells the caller which conversation_design_id to pass
to generate_reply, and (3) logs the decision + outcome fields. No ML, no triage.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, os, re, time

try:
    from app.ai.prompts import LANDLORD_NUMBER_CAPTURE_DESIGNS
except Exception:  # allow standalone import in tooling
    LANDLORD_NUMBER_CAPTURE_DESIGNS = {
        "corpus_number_capture_v1",
        "corpus_number_capture_v2",
        "playbook_ab_v1",
    }

EXPERIMENT = "open21d-playbook-ab-v1"
SALT = "open21d-playbook-ab-v1"      # fixed; changing it re-randomises - do NOT change mid-run
PROPENSITY = 0.5
ARM_A_DESIGN_ID = None                 # current production path (no explicit design)
ARM_B_DESIGN_ID = "playbook_ab_v1"     # dedicated clone of corpus_number_capture_v2 + P5
_FALLBACK_DESIGN = "viewing_first_v1"  # what prompts.py uses when design id is None

def arm_for_lead(lead_id: str) -> str:
    h = hashlib.sha256(f"{SALT}:{lead_id}".encode()).digest()
    return "A" if (h[0] & 1) == 0 else "B"

def design_id_for_arm(arm: str):
    if arm == "A":
        return ARM_A_DESIGN_ID
    if arm == "B":
        return ARM_B_DESIGN_ID
    raise ValueError(f"unknown arm {arm!r}")

def effective_config(arm: str) -> dict:
    """Mirrors prompts.py: design id None falls back to viewing_first_v1 rules; expose_mobile is
    False only for the corpus_* (LANDLORD_NUMBER_CAPTURE) designs."""
    design = design_id_for_arm(arm)
    effective = design or _FALLBACK_DESIGN
    return {
        "assigned_design_id": design,
        "effective_design_id": effective,
        "design_rules_applied": True,   # both arms render a rules block (None -> viewing_first_v1)
        "expose_mobile": design not in LANDLORD_NUMBER_CAPTURE_DESIGNS,
    }

def _operator_knobs(persona: dict | None) -> dict:
    p = persona or {}
    return {
        "phone_fetching_type": p.get("phone_fetching_type"),
        "conversation_style": p.get("conversation_style"),
        "persona_type": p.get("persona_type"),
        "mobile_present": bool(p.get("mobile_number")),
    }

def _load(log_path: str) -> dict:
    seen = {}
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    r = json.loads(ln)
                    seen[r["lead_id"]] = r
    return seen

def get_assignment(lead_id: str, log_path: str) -> dict | None:
    return _load(log_path).get(str(lead_id))


def enrollment_eligibility(state: dict | None) -> dict:
    """Only fresh first-reply threads may enter the experiment."""
    reasons = []
    state = state or {}
    outbound_count = int(state.get("outbound_count") or 0)
    message_contents = state.get("message_contents") or []

    if not state:
        reasons.append("conversation_not_found")
    if outbound_count > 1 or state.get("last_ai_reply"):
        reasons.append("prior_automated_reply")
    if (
        state.get("phone_found")
        or state.get("extracted_phone")
        or state.get("phone_found_at")
        or any(contains_phone(content) for content in message_contents)
    ):
        reasons.append("prior_phone_capture")
    if state.get("phone_requested_at"):
        reasons.append("prior_phone_request")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "outbound_count": outbound_count,
        "inbound_count": int(state.get("inbound_count") or 0),
    }


def log_exclusion(lead_id: str, exclusion_log: str, eligibility: dict) -> None:
    if str(lead_id) in _load(exclusion_log):
        return
    rec = {
        "lead_id": str(lead_id),
        "excluded_at": time.time(),
        **eligibility,
    }
    os.makedirs(os.path.dirname(exclusion_log) or ".", exist_ok=True)
    with open(exclusion_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def assign(
    lead_id: str,
    persona: dict | None,
    log_path: str,
    now: float | None = None,
    eligibility: dict | None = None,
) -> dict:
    """Idempotently assign a lead to an arm and LOG it BEFORE the first AI message. Returns a
    record carrying the design id the caller must pass to generate_reply (`assigned_design_id`)."""
    seen = _load(log_path)
    if lead_id in seen:
        return seen[lead_id]
    arm = arm_for_lead(lead_id)
    rec = {
        "experiment": EXPERIMENT,
        "lead_id": lead_id,
        "assigned_arm": arm,
        "propensity": PROPENSITY,
        "assigned_at": now if now is not None else time.time(),
        "eligibility": eligibility or {"eligible": True, "reasons": []},
        "operator_knobs": _operator_knobs(persona),     # what the operator had selected
        **effective_config(arm),                          # assigned/effective design, expose_mobile
        # Diagnostic outcome placeholders for later joins. The primary outcome
        # is produced by the frozen arm-blind grader, not by these heuristics.
        "landlord_number_requested": None,
        "landlord_phone_captured": None,
        "tenant_number_given_first": None,
        "conversation_progressed": None,
        "parked_or_dropped": None,
        "reply_received": None,
        "unsafe_or_pushy_detected": None,
        "qualified_landlord_phone_capture": None,
    }
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec

def log_outcome(lead_id: str, outcome_log: str, **fields) -> None:
    """Append HEURISTIC diagnostic outcome fields for a lead. These are diagnostics only - the
    PRIMARY outcome (qualified_landlord_phone_capture) is graded arm-blind by the frozen v2 grader,
    NOT from these logs. Append-only; kept separate from assignment; never alters reply behaviour."""
    rec = {"lead_id": lead_id, "logged_at": time.time(), **fields}
    os.makedirs(os.path.dirname(outcome_log) or ".", exist_ok=True)
    with open(outcome_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def summarize_database_captures(
    assignments: list[dict],
    database_outcomes: dict,
    *,
    include_legacy: bool = False,
) -> dict:
    """Summarize post-assignment captures using phone_found_at from the database."""
    arms = {
        "A": {"assigned": 0, "captured": 0},
        "B": {"assigned": 0, "captured": 0},
    }
    exclusions = []

    for assignment in assignments:
        lead_id = str(assignment["lead_id"])
        eligibility = assignment.get("eligibility")
        if not include_legacy and not eligibility:
            exclusions.append({"lead_id": lead_id, "reason": "legacy_missing_eligibility"})
            continue
        if eligibility and not eligibility.get("eligible", False):
            exclusions.append({"lead_id": lead_id, "reason": "ineligible_assignment"})
            continue

        arm = assignment["assigned_arm"]
        arms[arm]["assigned"] += 1
        outcome = database_outcomes.get(lead_id) or {}
        captured_at = outcome.get("phone_found_at")
        if not outcome.get("phone_found") or not captured_at:
            continue

        assigned_at = datetime.fromtimestamp(
            float(assignment["assigned_at"]),
            tz=timezone.utc,
        )
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        if captured_at >= assigned_at:
            arms[arm]["captured"] += 1

    for arm in arms.values():
        arm["capture_rate"] = (
            arm["captured"] / arm["assigned"] if arm["assigned"] else None
        )

    return {
        "source_of_truth": "database.conversations.phone_found_at",
        "arms": arms,
        "excluded": exclusions,
    }

# --- light heuristics for the outcome hook (diagnostics only) ---
_PHONE_RE = re.compile(r"(?:\(Number Removed\)|(?:\+?44|0)\s?7\d(?:[\s-]?\d){6,}|(?:\d[\s-]?){9,})")

def contains_phone(text: str) -> bool:
    return bool(_PHONE_RE.search(text or ""))

def asks_for_landlord_number(reply: str) -> bool:
    t = (reply or "").lower()
    return ("your number" in t or "your whatsapp" in t or "could i get your" in t
            or ("share your" in t and ("number" in t or "contact" in t)))
