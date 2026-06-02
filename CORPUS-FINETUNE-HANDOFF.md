# Handoff — Using the OpenRent Conversation Corpus to Make the Agent Better (Fine-Tuning)

Date: 2026-05-28
Author: prior session (handoff for next agent / engineer)
Status: **Plan only. No fine-tuning has been run.** This file is the
entry point for the fine-tuning track. It assumes the reader has not
seen the prior Hippocampus work.

---

## 0. TL;DR

We want the tenant-outreach agent to get landlords to share a phone
number (safely, after a viewing is on the table) more often. The
agent today is `gpt-4.1-mini` with a hand-written prompt. We have
**288 real OpenRent tenant↔landlord conversations** sitting in
`full-conversations.md`. The plan: **filter to the conversations that
succeeded, turn the tenant's messages into supervised training
examples, fine-tune `gpt-4.1-mini` on them, and measure the
fine-tuned model against the base model on the existing simulation
matrix.**

This is "behaviour cloning on positive outcomes": teach the model the
message patterns that actually worked, in real landlord conversations,
instead of relying only on prompt instructions.

**Why fine-tuning and not memory (Hippocampus):** the Hippocampus
episodic-memory approach was tested exhaustively on this exact task
and closed as a dead-end — see §1. Fine-tuning is a different,
better-suited tool for a short-horizon, policy-shaped task like this.

---

## 1. Why we're here (the short version of the Hippocampus closure)

The OpenRent + Hippocampus arc is **CLOSED** as of 2026-05-27. Six
pilots × five apparatus configurations, ~$0.82 spend, **zero clean
GREEN**. The hypothesis "episodic memory helps the agent capture
phone numbers" was falsified. Two structural reasons:

1. The memory mechanism barely fires at this scale (~15 schemas per
   1000 cells, validated at corpus scale).
2. Phone capture is a **short-horizon, policy-shaped task** — the
   right next message is determined mostly by the prompt + safety
   rules + the immediate conversation, not by recalling a past
   episode. Even when the full corpus was pre-loaded into memory, the
   corpus content never surfaced in the agent's prompt.

Full detail lives in the hippocampus-1 repo on branch
`docs/project-guide`:
- `docs/OPENRENT-PILOT-ARC-CLOSED.md` (canonical closure)
- `docs/OPENRENT-POSTCLOSURE-CORPUS-PROBE.md` (corpus-scale retest + the
  a7 corpus-preload run)
- `PROJECT-GUIDE.md` §7.25.10–§7.25.19

**The corpus is a real asset that the memory track never actually
used for learning.** Fine-tuning is the first approach that puts the
corpus content directly into the model's weights. The closure docs
explicitly name fine-tuning / RAG / few-shot as untested and
higher-leverage. This handoff picks fine-tuning.

---

## 2. What the agent actually does (the fine-tuning target)

The production agent plays the **tenant**. It messages landlords on
OpenRent and tries to (a) get a viewing arranged and (b) get the
landlord's phone number — but **only after** a viewing is being
discussed, never as a cold ask, and it must never emit an unapproved
phone number.

Key files (all branches; paths relative to `openrent-agent/`):

| File | Role |
| --- | --- |
| `app/ai/replies.py` | `generate_reply(...)` — calls `gpt-4.1-mini` via OpenAI, returns `ReplyGenerationResult`. **This is what fine-tuning replaces the model in.** |
| `app/ai/prompts.py` | `build_reply_prompt(...)` → `generate_message_persona_prompt(...)` — the hand-written system prompt (persona, stage, drive-distance, etc.). |
| `app/ai/validators.py` | `is_valid_reply()` (no "as an AI", length bounds) and `remove_unapproved_phone_numbers()` (strips any number that isn't the approved one). **Hard safety net — keep it on regardless of fine-tuning.** |
| `app/ai/stages.py` | `detect_stage()`, `extract_viewing_datetime()` — conversation-stage state machine. |
| `scripts/process_replies.py` | The live loop that pulls threads, generates a reply, validates, sends. |

The model is referenced as the literal string `"gpt-4.1-mini"` in
`app/ai/replies.py` (and `prompts.py` helpers). After fine-tuning,
the model id becomes `ft:gpt-4.1-mini:<org>:<suffix>:<id>`. Plan for a
**config-driven model id** (e.g. `settings.REPLY_MODEL`) so you can
swap base ↔ fine-tuned without code edits and A/B test.

---

## 3. The corpus

- **Location:** `full-conversations.md` (repo root). Present on
  branches `main` and `corpus-probe`. **Not** on
  `hippo-memory-integration`.
- **Size:** 7473 lines, **288 conversations**, ~822 landlord turns +
  ~789 tenant turns.
- **Format** (stable, machine-parseable):
  ```
  ## Conversation 1
  Source: https://www.openrent.co.uk/messages/41684412

  Tenant: "..."

  Landlord: "..."

  Tenant: "..."
  ```
  One `## Conversation N` header per conversation, a `Source:` URL
  line, then `Tenant:`/`Landlord:` turns wrapped in straight double
  quotes.

- **Parser already exists:** `openrent-agent/scripts/ingest_corpus.py`
  has `parse_corpus(path) -> list[{id, source, turns:[{speaker,text}]}]`.
  Reuse it; don't write a new parser.

### 3.1 CRITICAL — phone redaction before any external API

The corpus contains **152 literal phone strings** (real UK mobile
numbers landlords shared). These MUST be redacted before the text
touches OpenAI (fine-tuning upload, eval, anything). Redaction logic
is already written and tested in `scripts/ingest_corpus.py`:

- `redact_phones(text)` — replaces every phone-shaped string and every
  legacy `(Number Removed)` marker with the stable token
  `[PHONE_REDACTED]`. Idempotent.
- `contains_phone_literal(text)` — returns True if any raw phone
  survives. Use as a **hard gate**: assert False over the entire
  training set before upload.

The redaction test passes end-to-end on the full corpus
(`tests/scripts/test_ingest_corpus_redaction.py` on `corpus-probe`).

> **Ordering trap (read this twice):** redaction destroys the
> landlord-shared-phone signal, which is exactly the signal you need
> to *label* a conversation as a success (§4.1). So **label first,
> redact second.** Detect the success on the raw text (via
> `contains_phone_literal` on landlord turns, or the `(Number
> Removed)` marker), record the label, THEN redact the text you put
> into training examples.

---

## 4. The fine-tuning plan

### 4.1 Label each conversation by outcome (the supervised signal)

There is **no explicit success label** in the corpus. Deriving one is
the first real work item. Proposed labels, computed on the **raw**
(pre-redaction) text:

- **PHONE_OBTAINED** — a *Landlord* turn contains a phone literal
  (`contains_phone_literal`) or the `(Number Removed)` marker. This is
  the strongest success signal and the headline objective.
- **VIEWING_ARRANGED** — a viewing time is agreed (reuse
  `app/ai/stages.py::extract_viewing_datetime` against the turns, or a
  date/time + agreement heuristic). Secondary success.
- **DEAD** — landlord declines / "now rented" / no useful progression.
  Negative.

Spot-check the heuristic against ~20 hand-read conversations before
trusting it (Conv 1 = PHONE_OBTAINED, Conv 3 "flat is now rented" =
DEAD, Conv 4 = VIEWING_ARRANGED are good anchors). Write the labels to
a JSON sidecar so the step is reproducible.

> **Verify before building:** confirm whether the `Tenant:` turns are
> real human tenants or the agent's OWN past production outputs (the
> recurring "Mary / my husband and I" persona suggests the latter).
> It changes the framing: if they're the agent's outputs, training on
> *successful* ones is positive-outcome behaviour cloning (good); if
> human, it's imitation of real successful tenants (also good, but
> different distribution). Either way, filter to successes — but know
> which one you have.

### 4.2 Build (prompt → completion) training examples

The agent generates **tenant** turns, so **tenant turns are the
training targets.** For each tenant turn in a **successful**
conversation, build one example:

- **System/user message:** the conversation history up to (but not
  including) that tenant turn, formatted the way production formats it
  (`replies.py::format_conversation` → `"SENDER: message"` lines), 
  ideally wrapped by the real `build_reply_prompt(...)` so the
  fine-tuned model sees the same prompt shape it'll see in production.
- **Assistant message (completion):** the actual tenant turn that was
  sent (redacted).

Use OpenAI chat fine-tuning JSONL format:
```jsonl
{"messages":[{"role":"system","content":"<build_reply_prompt output>"},{"role":"user","content":"<conversation so far>"},{"role":"assistant","content":"<tenant reply, redacted>"}]}
```

Decisions to make (see §6): include only the last-N turns of context
vs the full thread; one example per tenant turn vs only the
phone-securing turn; whether to include VIEWING_ARRANGED successes or
only PHONE_OBTAINED.

### 4.3 Preserve the safety policy

Fine-tuning must not teach the model to break safety. Mitigations:

1. **Redaction** means no real phone number is ever a training target,
   so the model can't learn to emit one. `remove_unapproved_phone_
   numbers()` stays on at inference as the hard net.
2. **Don't train tenant turns that ask for a phone before a viewing is
   on the table.** When labelling, drop (or down-weight) any tenant
   turn that requests contact details before viewing discussion —
   otherwise you teach the premature-ask behaviour the safety rubric
   penalises. (In the Hippocampus arc this exact pattern,
   `phone_requested_too_early`, was the safety metric.)
3. Keep `is_valid_reply()` and the validators in the production path
   unchanged.

### 4.4 Train

OpenAI fine-tuning API on `gpt-4.1-mini`. Start small: a few hundred
examples, 1–3 epochs, default hyperparameters. Hold out ~10–15% of
successful conversations for eval. Budget is trivial (the whole corpus
is tiny by fine-tuning standards).

---

## 5. How to know it's actually better (evaluation)

**Do not ship on training loss.** Use the existing simulation matrix —
the same harness the Hippocampus arc used — to compare base vs
fine-tuned on real behaviour.

- The **LLM-landlord matrix runner + persona actors** (Cooperative /
  Suspicious / Brusque) live on branch **`hippo-memory-integration`**
  under `openrent-agent/simulation/`. That harness already produces
  `phone_captured_rate`, the `ASKED_PHONE_BEFORE_VIEWING` safety
  count, and per-persona breakdowns.
- Run the matrix twice: `REPLY_MODEL=gpt-4.1-mini` (baseline) vs
  `REPLY_MODEL=ft:...` (fine-tuned), same seeds, same fixtures.
- **Primary metric:** `phone_captured_rate(ft) − phone_captured_rate(base)`.
- **Safety gate (hard):** `ASKED_PHONE_BEFORE_VIEWING` must stay at 0
  for the fine-tuned arm. A lift that breaks safety is a failure.
- **Pre-commit a bar before you run** (the Hippocampus arc used +0.20;
  pick your own and write it down first — don't move it after seeing
  the result). This §S3 discipline is the project norm; honour it.

Baselines for reference (from the closed arc, same fixtures):
pooled `phone_captured_rate` ≈ 0.63 memory-off. That's the number to
beat.

---

## 6. Open decisions (resolve before building, none are committed)

1. **Context window per example:** full thread vs last-N turns.
2. **Examples per conversation:** every tenant turn vs only the turn
   that secured the phone/viewing.
3. **Success definition for training:** PHONE_OBTAINED only, or
   PHONE_OBTAINED + VIEWING_ARRANGED.
4. **Negative examples:** pure positive-only behaviour cloning, or also
   include DEAD conversations as contrastive signal (DPO-style — more
   work, possibly more lift).
5. **Prompt coupling:** train with the full `build_reply_prompt`
   system prompt (so prod is drop-in) vs a slimmer prompt (cheaper
   tokens, but prod prompt must then change too).
6. **Where this work should live:** a new branch off `main` (e.g.
   `feat/corpus-finetune`) is cleanest — `main` has the corpus,
   `corpus-probe` has the redaction script + test. You'll also need
   the eval harness from `hippo-memory-integration`. Consider merging
   the redaction script + corpus into the new branch first.

---

## 7. Concrete first steps

1. Branch off `main`: `git switch -c feat/corpus-finetune main`.
2. Bring over the redaction + parser: cherry-pick or copy
   `scripts/ingest_corpus.py` + `tests/scripts/test_ingest_corpus_redaction.py`
   from `corpus-probe`. Run the redaction test; confirm green.
3. Write `scripts/label_corpus.py`: parse → label (raw) → emit
   `corpus_labels.json`. Hand-verify ~20 against the anchors in §4.1.
4. Write `scripts/build_finetune_dataset.py`: for successful
   conversations, emit redacted (prompt → tenant-turn) JSONL.
   **Assert `contains_phone_literal` is False over the whole file
   before writing.**
5. Upload + fine-tune `gpt-4.1-mini` (small run first).
6. Wire `settings.REPLY_MODEL` into `app/ai/replies.py` so the model
   id is config-driven.
7. Pull the eval matrix from `hippo-memory-integration`, pre-commit a
   bar, run base vs fine-tuned, compare on `phone_captured_rate` +
   safety.
8. Record the result (and the pre-committed bar) honestly — green or
   red. If it's a finding, it also belongs in the hippocampus-1
   `PROJECT-GUIDE.md` per that repo's findings-discipline rule.

---

## 8. File index

| Path | Branch(es) | What |
| --- | --- | --- |
| `full-conversations.md` | main, corpus-probe | the 288-conversation corpus |
| `openrent-agent/scripts/ingest_corpus.py` | corpus-probe | `parse_corpus`, `redact_phones`, `contains_phone_literal` |
| `openrent-agent/tests/scripts/test_ingest_corpus_redaction.py` | corpus-probe | redaction test (passes on full corpus) |
| `openrent-agent/app/ai/replies.py` | all | `generate_reply`, `gpt-4.1-mini`, `format_conversation` |
| `openrent-agent/app/ai/prompts.py` | all | `build_reply_prompt` (the prod system prompt) |
| `openrent-agent/app/ai/validators.py` | all | safety net — keep on |
| `openrent-agent/app/ai/stages.py` | all | stage detection, `extract_viewing_datetime` |
| `openrent-agent/simulation/` | hippo-memory-integration | LLM-landlord matrix eval harness |
| hippocampus-1 `docs/OPENRENT-PILOT-ARC-CLOSED.md` | docs/project-guide | why memory was a dead-end (context) |
