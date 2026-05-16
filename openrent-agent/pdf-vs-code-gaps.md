# PDF SOP vs Code — Gap Analysis

## What the PDF Describes (Manual Process)

The PDF is the manual SOP given to human workers. The automation is supposed to replicate this exactly. Below is every step mapped against what the code currently does.

---

## Step-by-Step Mapping

### 1. Login and Search ✅
| PDF | Code | Status |
|-----|------|--------|
| Login to OpenRent via email/password | `app/browser/auth.py` | OK |
| Search by area name | `app/openrent/search.py` — builds URL from `SearchProfile.location` | OK |
| Filter: 1–5 bed, min £1300, radius 5-6km | `SearchProfile` model + URL params | OK — but radius is stored as `area` column, unclear if it maps to km correctly | [area=km] ✅

---

### 2. Agent Detection ✅
| PDF | Code | Status |
|-----|------|--------|
| Click landlord profile → "My Properties" | `app/openrent/landlords.py` | OK |
| **>3 properties = agent, skip** | `landlords.py` uses `threshold=5` | **WRONG — threshold should be 3, not 5** |

---

### 3. Sending the Initial Message ✅

The PDF describes **two distinct form types** that can appear when clicking "Message Landlord":

#### Type 1 — Simple Form
Two fields:
- "When are you available for viewings?" text box
- Message text box

Then click **"Request Viewing"**.

#### Type 2 — Advanced Screening Form 
Additional fields on top of Type 1:
- **Screening questions** (Yes/No):
  1. Are you a student? → **No**
  2. Will you use housing benefits / DSS? → **No**
  3. Do you have a pet? → **No**
  4. Are you a smoker? → **No**
  5. Looking for tenancy ≥6 months? → **Yes**
- **Furnishing**: dropdown → select "I don't mind"
- **Move-in date**: ~2 weeks after the property's available-from date
- **Combined monthly income**: `(monthly_rent × 30) + 20,000`
  - Example: £1,450 rent → (1450 × 30) + 20,000 = £63,500
- Then the same availability + message fields as Type 1

| PDF | Code | Status |
|-----|------|--------|
| Detect Type 1 vs Type 2 form | No detection logic exists | **MISSING** |
| Fill "when available for viewings?" field | Code only fills the main `textarea`, not this separate field | **MISSING** |
| Answer 5 screening questions | Not implemented | **MISSING** |
| Set furnishing to "I don't mind" | Not implemented | **MISSING** |
| Calculate and fill move-in date | Not implemented | **MISSING** |
| Calculate and fill income field | Not implemented | **MISSING** |
| Click "Request Viewing" | `send_initial_message()` searches for button with "request viewing" text | OK for Type 1 |

---

### 4. Message Content — Persona Generation

The PDF defines rules for the intro message based on bedroom count:

| Bedrooms | Household composition |
|----------|-----------------------|
| 1 bed | Single person, or couple (max 2 people) |
| 2 bed | Couple, or couple + 1 child/parent (max 3 people) |
| 3 bed | Couple + 1-2 kids/parent (max 4 people) |
| 4+ bed | Scale accordingly |

Message should include:
- Fictional first names (e.g. "Hi, I am Catherine and my husband is Ben")
- Believable jobs (IT, doctor, professor, engineer, etc.)
- Express interest in the property
- Ask about viewing availability

| PDF | Code | Status |
|-----|------|--------|
| Dynamic message based on bedroom count | `account.initial_message` is a static string in the DB | **MISSING — one fixed message for all listings** |
| Fictional persona (name, job, family size) | Not generated dynamically | **MISSING** |
| Availability field text | Static or blank | **MISSING** |

---

### 5. Conversation Strategy — Reply Handling

This is the most important gap. The PDF defines a **staged conversation flow**:

#### Stage 1 — Fix a Viewing Appointment
When the landlord replies, the goal is to **book a viewing**, not immediately ask for the phone number.

- Tell them you're free "next day evening/night UK time" or "2 days later"
- Confirm a specific viewing time

#### Stage 2 — Ask for Phone Number (5-7 hours before viewing)
The morning of the viewing, send a message asking for their number using this framing:

> "We are travelling 4-5 hours for the viewing so please give your number so I can call when I reach, in case you don't see the message or if I'm late."

- Claim to be travelling from Manchester / Derby / Birmingham (or any city 4-5 hours away from the property area)
- Tell them you're moving for a new job

#### Stage 3 — Cancel the Viewing
Regardless of whether a phone number was obtained, **cancel the viewing at least 1 hour before**.

| PDF | Code | Status |
|-----|------|--------|
| Stage 1: Book viewing first | AI prompt tells it to ask for phone immediately | **WRONG — skips viewing step entirely** |
| Stage 2: Ask for phone 5-7hrs before with travel excuse | Not in AI prompt or workflow | **MISSING** |
| Stage 3: Cancel viewing 1hr before | No tracking of scheduled viewings, no cancellation logic | **COMPLETELY MISSING** |
| Track conversation stage (no viewing / viewing booked / day before) | No stage tracking in DB or code | **MISSING** |

---

### 6. Account Rotation / Phase System

The PDF defines a weekly rotation:

| Day | Accounts | Action |
|-----|----------|--------|
| Monday | 1 & 2 (Phase 1) | Send enquiries |
| Tuesday | 1 & 2 | Check + reply only |
| Wednesday | 3 & 4 (Phase 2) | Send enquiries + reply |
| Thursday | 3 & 4 | Check + reply |
| Friday | 5 & 6 (Phase 3) | Send enquiries + reply |
| Saturday | 5 & 6 | Check + reply |

| PDF | Code | Status |
|-----|------|--------|
| Day-of-week aware account rotation | `run_workers.py` fires all active accounts every run | **MISSING** |
| Send-only days vs reply-only days | No concept of this | **MISSING** |

---

### 7. Daily Targets and Limits 

| PDF | Code | Status |
|-----|------|--------|
| 8 properties per account per session | `account.daily_limit` defaults to 8 | OK |
| 16 total per person (phone + laptop) | Multi-account workers run in parallel | OK |
| Min 3 phone number leads per day | No tracking of daily lead count | **MISSING — no daily lead target alert** | 

---

## Priority Order for Implementation

### P0 — Blocks everything
1. **Type 2 form handler** — roughly half of all listings use the advanced form. Currently the bot either crashes or submits a blank form on these.

### P1 — Core business logic wrong
2. **Agent threshold: change 5 → 3** (`landlords.py`) — one line fix
3. **Conversation strategy rewrite** — AI should book viewing first, ask for phone on day-of with travel excuse
4. **Conversation stage tracking** — add a `stage` field to `Conversation` model (`INITIAL` / `VIEWING_BOOKED` / `PHONE_REQUESTED` / `VIEWING_CANCELLED`)

### P2 — Quality and completeness
5. **Dynamic persona generation** — message text should vary by bedroom count, with random names/jobs
6. **Availability field** — fill the "when are you available for viewings?" box separately from the message
7. **Viewing cancellation** — track scheduled viewing datetime, schedule cancellation message 1hr before

### P3 — Operational
8. **Phase/rotation system** — day-of-week aware account selection in `run_workers.py`
9. **Daily lead count tracking** — alert or log when daily phone target (3) is hit per account

---

## DB Changes Needed

To support the missing features, the following schema additions are required:

```
Conversation:
  + stage          String   (INITIAL / VIEWING_BOOKED / PHONE_REQUESTED / VIEWING_CANCELLED)
  + viewing_datetime  DateTime  (when the viewing is scheduled)
  + viewing_location  String    (property area, used for cancellation message)

Account:
  + persona_name   String   (e.g. "Catherine")
  + persona_partner_name  String  (e.g. "Ben")
  + persona_job    String
  + persona_partner_job   String
  + home_city      String   (e.g. "Manchester" — used in travel excuse)
```
