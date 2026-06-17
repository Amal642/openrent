"""OPEN-21D Part 1 — playbook A/B routing + assignment + logging (production).

Locked 2-arm A/B (see the hippocampus repo: experiments/open21d-real-conversations/PLAYBOOK-AB-SPEC.md):

  Arm A (control)  = baseline capture AI on the CURRENT production path:
      conversation_design_id = None  -> _DESIGN_RULES falls back to viewing_first_v1,
      mobile EXPOSED, operator's selected knobs (phone_fetching_type / conversation_style) kept.
  Arm B (playbook) = capture AI using the EXISTING corpus_number_capture_v2 design AS-IS
      (+ the single appended P5 'drop/park dead leads' rule in prompts.py):
      mobile WITHHELD (expose_mobile=False, since corpus_* is in LANDLORD_NUMBER_CAPTURE_DESIGNS),
      landlord-number-first policy, answer-screening-first, respect-refusal.

Note: the shared human-operated message history is REFERENCE/BASELINE only — it is NOT arm A.
Both arms are AI. This module does NOT change message generation; it only (1) assigns the arm
per lead before the first AI message, (2) tells the caller which conversation_design_id to pass
to generate_reply, and (3) logs the decision + outcome fields. No ML, no triage.
"""
from __future__ import annotations
import hashlib, json, os, re, time

try:
    from app.ai.prompts import LANDLORD_NUMBER_CAPTURE_DESIGNS
except Exception:  # allow standalone import in tooling
    LANDLORD_NUMBER_CAPTURE_DESIGNS = {"corpus_number_capture_v1", "corpus_number_capture_v2"}

EXPERIMENT = "open21d-playbook-ab-v1"
SALT = "open21d-playbook-ab-v1"      # fixed; changing it re-randomises — do NOT change mid-run
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

def assign(lead_id: str, persona: dict | None, log_path: str, now: float | None = None) -> dict:
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
        "operator_knobs": _operator_knobs(persona),     # what the operator had selected
        **effective_config(arm),                          # assigned/effective design, expose_mobile
        # outcome fields (filled later by log_outcome / arm-blind grading):
        "landlord_number_requested": None,
        "landlord_number_captured": None,
        "parked_dropped": None,
        "qualified_landlord_phone_capture": None,
    }
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec

def log_outcome(lead_id: str, outcome_log: str, **fields) -> None:
    """Append HEURISTIC diagnostic outcome fields for a lead. These are diagnostics only — the
    PRIMARY outcome (qualified_landlord_phone_capture) is graded arm-blind by the frozen v2 grader,
    NOT from these logs. Append-only; kept separate from assignment; never alters reply behaviour."""
    rec = {"lead_id": lead_id, "logged_at": time.time(), **fields}
    os.makedirs(os.path.dirname(outcome_log) or ".", exist_ok=True)
    with open(outcome_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")

# --- light heuristics for the outcome hook (diagnostics only) ---
_PHONE_RE = re.compile(r"(?:\(Number Removed\)|(?:\+?44|0)\s?7\d(?:[\s-]?\d){6,}|(?:\d[\s-]?){9,})")

def contains_phone(text: str) -> bool:
    return bool(_PHONE_RE.search(text or ""))

def asks_for_landlord_number(reply: str) -> bool:
    t = (reply or "").lower()
    return ("your number" in t or "your whatsapp" in t or "could i get your" in t
            or ("share your" in t and ("number" in t or "contact" in t)))
