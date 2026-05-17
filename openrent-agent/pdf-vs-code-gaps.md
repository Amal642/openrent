# PDF SOP vs Code — Gap Analysis (Updated 2026-05-14)

## What the PDF Describes (Manual Process)

The PDF is the manual SOP given to human workers. The automation is supposed to replicate this exactly. Below is every step mapped against what the code currently does.

---

## Step-by-Step Mapping

### 1. Login and Search
| PDF | Code | Status |
|-----|------|--------|
| Login to OpenRent via email/password | `app/browser/auth.py` | OK |
| Search by area name | `app/openrent/search.py` — builds URL from `SearchProfile.location` | OK |
| Filter: 1–5 bed, min £1300, radius 5-6km | `SearchProfile` model + URL params — `area` column maps to km | OK |

---

### 2. Agent Detection
| PDF | Code | Status |
|-----|------|--------|
| Click landlord profile → "My Properties" | `app/openrent/landlords.py` | OK |
| **>3 properties = agent, skip** | `landlords.py:156` default is `threshold=3` | **FIXED** |
| Agent detection called in process loop | `scripts/process_listings.py` calls `landlord_is_agent()` before sending | DONE |

---

### 3. Sending the Initial Message

#### Type 1 / Type 2 Form Detection
| PDF | Code | Status |
|-----|------|--------|
| Detect Type 1 vs Type 2 form | `detect_form_type()` checks for `#ScreeningInfo_FurnishedStateRequired` | **FIXED** |
| Fill "when available for viewings?" field | `#Availability` filled separately at `messaging.py:282-296` | **FIXED** |
| Click "Request Viewing" | `send_initial_message()` searches for button with "request viewing" text | OK |

#### Type 2 Screening Form
| PDF | Code | Status |
|-----|------|--------|
| Are you a student? → No | `ScreeningInfo.IsStudent = false` | **FIXED** |
| Will you use housing benefits / DSS? → No | `ScreeningInfo.OnBenefits = false` | **FIXED** |
| Do you have a pet? → No | `ScreeningInfo.HasPets = false` | **FIXED** |
| Are you a smoker? → No | `ScreeningInfo.IsSmoker = false` | **FIXED** |
| Looking for tenancy ≥6 months? → Yes | `ScreeningInfo.HasRightToRent = true` | **UNCERTAIN** — code fills an immigration right-to-rent field, which may be a different question than tenancy duration |
| Furnishing → "I don't mind" | Selects value `"2"` from `#ScreeningInfo_FurnishedStateRequired` | **UNCERTAIN** — whether `"2"` maps to "I don't mind" depends on OpenRent's dropdown ordering |
| Move-in date: ~2 weeks after available-from | `available_from + timedelta(days=14)` at `messaging.py:166` | **FIXED** |
| Income: `(monthly_rent × 30) + 20,000` | `(rent * 30) + 20000` at `messaging.py:186` | **FIXED** |

---

### 4. Message Content — Persona Generation
| PDF | Code | Status |
|-----|------|--------|
| Dynamic message based on bedroom count | `generate_household()` maps bedrooms → household at `replies.py:58` | **FIXED** |
| Fictional names (husband + wife) | `generate_names()` calls AI to generate a name pair | **FIXED** |
| Believable jobs | `get_random_job()` called once per account persona and reused in initial prompts | DONE |
| Persona fields stored on Account | `Account` model + schema update + migration | DONE — `persona_name`, `persona_partner_name`, `persona_job`, `persona_partner_job`, `home_city` are persisted and exposed through API |

---

### 5. Conversation Strategy — Reply Handling

#### DB / Stage Infrastructure
| PDF | Code | Status |
|-----|------|--------|
| Track conversation stage | `Conversation.conversation_stage` column | **FIXED** |
| Track viewing datetime | `Conversation.viewing_datetime` column | **FIXED** |
| Track viewing confirmed | `Conversation.viewing_confirmed` column | **FIXED** |
| Track viewing cancelled | `Conversation.viewing_cancelled` column | **FIXED** |
| Track when phone was requested | `Conversation.phone_requested_at` column | **FIXED** |
| Detect stage from conversation text | `stages.py` — detects `VIEWING_BOOKED` / `VIEWING_DISCUSSION` | **FIXED** |
| Pass stage into reply generator | `replies.py` passes stage and persona into `build_reply_prompt()` | DONE |

#### Stage 1 — Fix a Viewing Appointment
| PDF | Code | Status |
|-----|------|--------|
| Book viewing first, do not ask for phone immediately | Stage-aware prompt arranges viewing first and delays phone request until booked | DONE |

#### Stage 2 — Ask for Phone Number (5-7 hrs before viewing)
| PDF | Code | Status |
|-----|------|--------|
| Ask for phone the morning of the viewing | `VIEWING_BOOKED` prompt asks for phone before viewing | DONE |
| Use travel excuse (Manchester / Derby / Birmingham, 4-5 hrs away) | Prompt uses persisted `home_city` and 4-5 hour travel context | DONE |
| Claim moving for a new job | Initial persona includes persisted jobs for both people | DONE |

#### Stage 3 — Cancel the Viewing
| PDF | Code | Status |
|-----|------|--------|
| Cancel viewing at least 1 hr before | `process_viewing_reminders.py` is wired into account worker and sends cancellation around 5 hours before viewing | DONE |

---

### 6. Account Rotation / Phase System
| PDF | Code | Status |
|-----|------|--------|
| Day-of-week aware account rotation (Mon–Sat phases) | `account_worker.account_phase()` rotates accounts by weekday/parity | DONE |
| Send-only days vs reply-only days | Worker phases support `send_and_reply` vs `reply_only` | DONE |

---

### 7. Daily Targets and Limits
| PDF | Code | Status |
|-----|------|--------|
| 8 properties per account per session | `account.daily_limit` defaults to 8 | OK |
| 16 total per person (phone + laptop) | Multi-account workers run in parallel | OK |
| Min 3 phone number leads per day | Repository counts phones per account/day and logs when target is reached; dashboard exposes target progress | DONE |

---

### 8. AI Reply — Send Fix (from tofix.md)
| Issue | Code | Status |
|-------|------|--------|
| Reply typed but never submitted | `inbox.py` clicks `#send-message-button` when `AI_AUTOSEND` is enabled | DONE |

---

## Status Summary

### Fixed
- Agent threshold corrected to 3
- Type 2 form fully detected and handled (mostly)
- Availability field filled separately from message body
- All 4 confirmed screening questions answered
- Move-in date and income formula implemented
- Dynamic household generation by bedroom count
- AI name generation
- DB stage tracking fields (`conversation_stage`, `viewing_datetime`, `viewing_confirmed`, `viewing_cancelled`, `phone_requested_at`)
- Stage detection logic (`stages.py`)

### Broken / Crashes at Runtime
No remaining runtime crash items from this gap list.

### Not Yet Implemented
No remaining open items from this gap list.

---

## Priority Order for Next Implementation

### P0 — Runtime crashes (break existing functionality)
1. Fix `professions` set → dict bug in `replies.py:134`
2. Fix `build_reply_prompt` signature in `prompts.py:18` to accept `stage`
3. Uncomment `submit_button.click()` in `inbox.py:303

### P1 — Core business logic wrong
4. Rewrite `build_reply_prompt` to use stage-aware strategy:
   - No stage / `VIEWING_DISCUSSION`: book the viewing, do not ask for phone
   - `VIEWING_BOOKED`: ask for phone with travel excuse (4-5 hrs away, moving for new job)
   - `VIEWING_CANCELLED`: no further action
5. Add `home_city` / persona fields to `Account` model and use in travel excuse

### P2 — Quality and completeness
6. Verify furnishing dropdown value `"2"` maps to "I don't mind" on OpenRent
7. Verify `HasRightToRent` is the correct field name for the tenancy duration question
8. Stage 3: schedule auto-cancellation 1 hr before `viewing_datetime`
9. Add Account persona DB fields (`persona_name`, `persona_partner_name`, `home_city`, etc.)

### P3 — Operational
10. Phase/rotation system — day-of-week aware account selection in `run_workers.py`
11. Daily lead count tracking — alert or log when daily phone target (3) is hit per account
