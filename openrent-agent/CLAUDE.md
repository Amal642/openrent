# CLAUDE.md

This file gives coding agents the project-specific context needed to work safely in this repository.

## Working Directory

Most commands should run from:

```powershell
openrent-agent/
```

The parent repository may contain unrelated files. Avoid changing files outside `openrent-agent/` unless explicitly asked.

## Current Product Direction

The simulation lab is a separate UI from the main OpenRent command center.

Primary simulation goal:

- Let trusted testers act as landlords.
- Let the AI act as the renter.
- Start with an AI initial message.
- Audit whether the AI progresses toward booking a viewing.
- Capture phone numbers only when viewing coordination makes it reasonable.
- Compare multiple conversation designs against the same landlord scenario.

Preferred current conversation design:

```text
viewing_first_v1
```

This design should:

- Move toward viewing first.
- Answer landlord screening questions naturally.
- Avoid early phone asks.
- Ask for phone only after viewing is confirmed or close to confirmed.
- Avoid lead-harvesting or scripted language.

## Important Files

```text
app/ai/prompts.py                          Single source of truth for all AI reply behavior
app/ai/personas.py                         Persona templates and materialisation logic
app/ai/replies.py
app/api/main.py
simulation/conversation_designs.py         Metadata only: names, opening message templates, success/failure criteria
simulation/scenario_library.py
simulation/conversation_state.py
simulation/compare.py
simulation/evaluators/heuristic.py
simulation/templates/initial_message_provider.py
frontend/simulation-lab/src/
tests/simulation/
tests/test_simulation_api.py
tests/test_prompt_persona_flow.py
```

## AI Behavior Architecture

All reply behavior rules for the simulation lab live in `app/ai/prompts.py` in the `_DESIGN_RULES` dict, keyed by conversation design ID:

```python
_DESIGN_RULES = {
    "viewing_first_v1": [...],
    "phone_first_v1": [...],
    "screening_first_v1": [...],
    "soft_human_v1": [...],
}
```

`build_reply_prompt` reads from this dict using `conversation_design_id`. Do not source reply rules from `conversation_designs.py` — that file is metadata only.

`ProductionPolicy.build_prompt` passes `conversation_design_id=self.conversation_design_id` to `build_reply_prompt`. It does not pass the full conversation design dict.

To change how the AI replies for a given design, edit `_DESIGN_RULES` in `prompts.py` only.

## Opening Message Architecture

Opening messages in `conversation_designs.py` are template strings, not hardcoded text. They use tokens such as `{persona_name}`, `{my_partner_and_i_are}`, and `{credentials_intro}` that are resolved at session start via `ConversationDesign.render_opening_message(persona)`.

- To change the wording of an opening message, edit the template string in `conversation_designs.py`.
- To change who the AI presents as, change the persona passed to the session.
- Do not hardcode names or household phrasing directly into `opening_message` strings.

## Simulation Concepts

Use human-facing labels in audit mode:

- `AI`, not `agent`.
- `Landlord`, not `actor`.
- Avoid raw event codes in client-facing UI.

Internal event/source names may still use existing code terms where changing them would create unnecessary churn.

Conversation state is deterministic and lightweight. Do not add LLM-based state classification unless explicitly requested.

Scenario library is static Python for now. Do not add a database for scenarios yet.

## Run Commands

Backend API:

```powershell
uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

Simulation lab:

```powershell
cd frontend\simulation-lab
npm run dev
```

Backend verification:

```powershell
pytest tests\simulation tests\test_simulation_api.py tests\test_prompt_persona_flow.py
```

Frontend verification:

```powershell
cd frontend\simulation-lab
npm run build
```

## Git and Generated Files

Do not commit:

- `node_modules/`
- `frontend/*/dist/`
- generated simulation run JSONs unless explicitly promoted to fixtures
- runtime logs
- `.env`
- `openrent.db`

Before editing, check status:

```powershell
git status --short
```

The worktree may already contain user or prior-agent changes. Do not revert unrelated changes.

## Implementation Style

- Keep simulation changes vertical and small.
- Prefer deterministic tests around policy, state, scenarios, and API contracts.
- Avoid broad refactors while the simulation integration is still being stabilized.
- Keep audit UI simple and readable.
- Put raw prompts, completions, runtime context, and event logs behind dev mode.
