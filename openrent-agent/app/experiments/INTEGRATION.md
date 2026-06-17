# OPEN-21D playbook A/B — production wiring (drop-in)

The A/B is implemented as `app/experiments/playbook_ab.py` (assignment + arm→design_id +
logging + outcome diagnostics). The only behavioural switch is which `conversation_design_id`
is passed to `generate_reply`.

Production code changes:
1. `app/ai/prompts.py` — added a DEDICATED design **`playbook_ab_v1`** = a clone of
   `corpus_number_capture_v2` + rule **P5 (drop/park dead leads)**, added to
   `LANDLORD_NUMBER_CAPTURE_DESIGNS` + `CORPUS_V2_STYLE_DESIGNS`. `corpus_number_capture_v2` is
   left UNTOUCHED so it is safe for any other use.
2. `app/ai/replies.py` — the phone-share shortcut now skips on `LANDLORD_NUMBER_CAPTURE_DESIGNS`
   (so `playbook_ab_v1` is covered) instead of a hard-coded corpus set.
3. `scripts/process_replies.py` — assign-before-first-message + `conversation_design_id=ab_design`;
   the **mobile-injection safeguard is gated on the arm** (`ab_expose_mobile`) so arm B cannot
   re-inject our number; append-only outcome-diagnostics hook after the reply is sent.

- **Arm A (control)** = current production AI path: `conversation_design_id=None`
  (→ `viewing_first_v1` rules via the existing fallback; mobile EXPOSED; operator knobs kept).
- **Arm B (playbook)** = `conversation_design_id="playbook_ab_v1"` (clone of
  `corpus_number_capture_v2` + P5; mobile WITHHELD because it is in
  `LANDLORD_NUMBER_CAPTURE_DESIGNS`, and the injection safeguard is arm-gated).
- Human-operated message history is REFERENCE/BASELINE only — NOT arm A. Both arms are AI.

## Status: APPLIED at the real call site

The live production reply path is **`scripts/process_replies.py`** (1111 lines); the
`generate_reply` call is at line ~950. The A/B wiring is **already applied there**:
- import block: `import os` + `from app.experiments import playbook_ab`;
- call site: the assign-before-first-message block + `conversation_design_id=ab_design`.

(The `app/jobs/process_replies.py` / `send_messages.py` / `sync_crm.py` files are empty
legacy stubs — NOT the production path. The legacy `old_codes/main.py:176` call is also not
the current path.) The applied edit is byte-for-byte the snippet below.

## The applied edit (for reference / re-apply on another checkout)

```python
import os
from app.experiments import playbook_ab

AB_ENABLED = os.getenv("PLAYBOOK_AB_ENABLED") == "1"      # feature flag: merging is a no-op until set
AB_LOG = os.getenv("PLAYBOOK_AB_LOG", "logs/playbook_ab_assignments.jsonl")

# Assign + LOG before the first AI message (idempotent per lead). lead_id = thread_id.
ab_design = None
if AB_ENABLED:
    a = playbook_ab.assign(thread_id, persona, AB_LOG)
    ab_design = a["assigned_design_id"]   # None (arm A) or "playbook_ab_v1" (arm B)

reply, error = generate_reply(
    messages,
    stage=stage,
    persona=persona,
    property_location=property_location,
    conversation=conversation,
    landlord_attitude=landlord_attitude,
    conversation_style=conversation_style,
    travel_city=travel_city,
    thread_id=thread_id,
    conversation_design_id=ab_design,   # <-- ONLY added arg; None == exact current behaviour
)
```

`generate_reply` (replies.py) already accepts and forwards `conversation_design_id`, so no
change is needed there. With `PLAYBOOK_AB_ENABLED` unset, behaviour is byte-for-byte current
production (ab_design stays None for everyone, same as today).

## Outcome logging (when the thread reaches a terminal state)

```python
from app.experiments import playbook_ab
playbook_ab.log_outcome(
    thread_id, os.getenv("PLAYBOOK_AB_OUTCOME_LOG", "logs/playbook_ab_outcomes.jsonl"),
    landlord_number_requested=<bool>,   # did the AI ask for the landlord's number
    landlord_number_captured=<bool>,    # did we obtain the landlord's number (use phone_extractor)
    parked_dropped=<bool>,              # was the lead parked/stopped (P5)
)
```
`qualified_landlord_phone_capture` is filled later by the ARM-BLIND v2 grader
(hippocampus: experiments/open21d-real-conversations/run1/GRADER_SPEC_OR_v2.md + abtest/grade_blind.py),
then joined on lead_id for analysis (abtest/analyze_ab.py applies the LOCKED falsifier:
B−A ≥ +10pp qualified, one-sided CI excludes 0, safety not worse, reply rate not down >5pp).

## Verify

```
cd openrent-agent && python -m app.experiments.ab_dryrun
```
Runs through the REAL `build_reply_prompt` and asserts: assignment-before-first-message; arm A
exposes mobile + viewing_first rules; arm B withholds mobile + corpus rule + appended P5; all
required log fields present. (Last run: ALL CHECKS PASS.)
```
