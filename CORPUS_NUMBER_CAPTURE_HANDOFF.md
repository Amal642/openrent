# Corpus Number Capture Handoff

Date: 2026-06-02

## Summary

This branch introduces corpus-derived landlord-number capture strategies for the OpenRent reply agent. The goal is to get the landlord's phone number naturally, without sounding eager, scripted, or AI-like, and without sharing the tenant account's own phone number.

The important new mode is:

```text
corpus_number_capture_v2
```

`corpus_number_capture_v1` also exists, but treat it as an earlier prototype. Use v2 for review and testing.

Do not enable this in live autosend until it has been reviewed in manual mode.

## New Modes and Persona Changes

### `corpus_number_capture_v1`

Prototype strategy. It improved number capture in simulation but could ask too mechanically after viewing progress. Keep it for comparison only.

### `corpus_number_capture_v2`

Preferred strategy.

Behavior:

- Do not share the tenant mobile number.
- Ask for the landlord's number only after viewing/logistics progress.
- Answer landlord screening first using persona facts.
- If landlord refuses phone sharing before booking, do not ask again in the next tenant reply.
- If a viewing is booked immediately after a refusal, do not instantly ask for the number.
- If landlord asks for the tenant number, show mild discomfort and keep OpenRent as fallback.
- Avoid polished/call-centre wording.

Preferred wording:

```text
Could I get your number just in case we're delayed?
Could I get your number in case we're running late on the day?
We can keep it here for now if you prefer.
I'd rather not share mine just yet, we've had a bad experience before.
```

Avoid:

```text
best number
coordinate
contact details
sort timing
kindly share
happy to share mine
```

### Persona Additions

Added:

```text
landlord_number_boundary
single_income_couple
```

`single_income_couple` supports cases where one applicant works and the partner is currently at home/full-time parent/homemaker. The prompt is now told not to invent a second income or partner job.

New persona metadata:

```text
screening_posture
phone_boundary
```

These are derived from persona templates. No database migration was added.

## Main Files Changed

```text
openrent-agent/app/ai/personas.py
openrent-agent/app/ai/prompts.py
openrent-agent/app/ai/replies.py
openrent-agent/app/db/repository.py
openrent-agent/simulation/conversation_designs.py
openrent-agent/simulation/conversation_state.py
openrent-agent/simulation/evaluators/heuristic.py
openrent-agent/scripts/analyze_corpus_number_capture.py
openrent-agent/scripts/ingest_corpus.py
openrent-agent/CORPUS_NUMBER_CAPTURE_EXAMPLES.md
```

## Important Live Workflow Warning

`app/ai/prompts.py` is shared by simulation and live reply generation.

Simulation path:

```text
simulation/policies/production_policy.py
-> app/ai/prompts.py
```

Live automation reply path:

```text
app/ai/replies.py
-> app/ai/prompts.py
```

The v2 behavior is gated by:

```text
conversation_design_id == "corpus_number_capture_v2"
```

If the live automation path does not pass this design ID, it should continue using the default design behavior. Verify this before rollout.

Do not run live sending while testing:

```text
python scripts/run_workers.py
python scripts/process_replies.py
python app/main.py
```

Keep:

```env
AI_AUTOSEND=false
```

## Verification Commands

Run from:

```powershell
cd D:\openrent\openrent\openrent-agent
```

### Full test suite

```powershell
python -m pytest
```

Expected latest result:

```text
68 passed
```

### Corpus analyzer

```powershell
python scripts/analyze_corpus_number_capture.py
```

Expected latest summary:

```text
total_conversations: 288
successful_conversations: 78
examples: 80
```

The analyzer output must not contain raw phone numbers.

## Simulation Check

Use these designs:

```text
viewing_first_v1
corpus_number_capture_v2
```

Use these scenarios:

```text
outreach-screening-before-phone
outreach-phone-request
reply-after-landlord-question
```

Latest deterministic matrix result:

```text
viewing_first_v1:
phone: 0/9
early phone: 0
viewing progress: 1.0

corpus_number_capture_v2:
phone: 9/9
early phone: 0
pushed after refusal: 0
viewing progress: 1.0
```

Treat this as a local simulation signal, not permission to autosend.

## Manual Review Checklist

Before live use, generate replies in manual-review mode and inspect at least 20-50 real landlord threads.

Accept replies that:

- Answer landlord screening first.
- Use persona facts only.
- Ask for landlord number only with viewing/logistics context.
- Sound like a normal tenant text.
- Keep OpenRent as fallback if landlord is cautious.

Reject replies that:

- Share tenant mobile number.
- Ask for phone before viewing/logistics progress.
- Ask again immediately after landlord refused phone sharing.
- Ask immediately after booking when the landlord just refused pre-booking phone sharing.
- Use `best number`, `coordinate`, `contact details`, `kindly share`, or similar.
- Invent jobs, income, household facts, or move dates.

## Rollout Recommendation

1. Keep `AI_AUTOSEND=false`.
2. Select `corpus_number_capture_v2` only in simulation/manual-review flows.
3. Review generated replies on real threads without sending.
4. If manual review passes, send a small supervised batch manually.
5. Monitor landlord responses, number capture rate, refusals, and suspicious replies.
6. Only consider autosend after a clean supervised batch.

Do not switch the live workflow to v2 without confirming where `conversation_design_id` is set for production replies.
