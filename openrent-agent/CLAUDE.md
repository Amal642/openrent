# CLAUDE.md

This file gives coding agents the project-specific context needed to work safely in this repository.

## Working Directory

Most commands should run from:

```powershell
openrent-agent/
```

The parent repository may contain unrelated files. Avoid changing files outside `openrent-agent/` unless explicitly asked.

## Current Product Direction

The simulation lab is separate from the main OpenRent command center.

Primary simulation goal:

- Let trusted testers act as landlords.
- Let the AI act as the renter.
- Start with an AI initial message in most client-facing tests.
- Check whether the AI progresses toward booking a viewing.
- Capture or exchange phone numbers only when viewing coordination makes it reasonable.
- Compare multiple message styles against the same landlord scenario.

Client-facing UI language:

- Use `Test` mode for the simple client-facing experience.
- Use `Advanced` mode for raw prompts, completions, runtime context, event logs, and replay.
- Use human-facing labels: `Tenant` and `Landlord`, not `agent` and `actor`.
- Avoid raw event codes in Test mode.

## Active Conversation Designs

Current active design IDs:

```text
viewing_first_v1
screening_first_v1
confirmation_close_v1
tenant_shares_first_v1
landlord_preference_v1
```

Removed design IDs:

```text
phone_first_v1
soft_human_v1
```

Design intent:

- `viewing_first_v1`: baseline; move toward viewing first, then ask for contact only when coordination is reasonable.
- `screening_first_v1`: answer/offer credibility before pushing for viewing/contact.
- `confirmation_close_v1`: strict gate; ask for number only after a concrete viewing time is agreed or nearly agreed, with a logistics reason.
- `tenant_shares_first_v1`: reciprocity; tenant shares their own mobile first after viewing progress.
- `landlord_preference_v1`: channel choice; ask whether the landlord prefers OpenRent messages or phone coordination.

## Important Files

```text
app/ai/prompts.py                          Single source of truth for AI reply behavior rules
app/ai/personas.py                         Persona templates and materialisation logic
app/ai/replies.py
app/api/main.py
simulation/conversation_designs.py         Metadata, opening templates, property phrasing, simulation persona construction
simulation/scenario_library.py
simulation/scenarios/generators.py         Scenario property/persona data
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

All AI reply behavior rules for the simulation lab live in `app/ai/prompts.py` in the `_DESIGN_RULES` dict, keyed by conversation design ID:

```python
_DESIGN_RULES = {
    "viewing_first_v1": [...],
    "screening_first_v1": [...],
    "confirmation_close_v1": [...],
    "tenant_shares_first_v1": [...],
    "landlord_preference_v1": [...],
}
```

`build_reply_prompt` reads from this dict using `conversation_design_id`.

`simulation/conversation_designs.py` is not the turn-by-turn reply behavior source. It owns:

- display names and descriptions
- opening message templates
- property-aware `{property_phrase}` rendering
- simulation persona construction via `build_simulation_persona()`
- success/failure criteria shown to testers

To change how the AI replies for a given design, edit `_DESIGN_RULES` in `prompts.py`.

## Opening Message Architecture

Opening messages in `conversation_designs.py` are template strings, not hardcoded final text. They use tokens such as:

- `{persona_name}`
- `{my_partner_and_i_are}`
- `{credentials_intro}`
- `{property_phrase}`

These are resolved at session start through `ConversationDesign.render_opening_message(persona, property=property)`.

- To change the wording of an opening message, edit the template string in `conversation_designs.py`.
- To change who the AI presents as, change the scenario persona type or persona template.
- To change property wording, update scenario property data or `_property_phrase()`.
- Do not hardcode tenant names, household phrasing, or property strings directly into final messages.

## Simulation Concepts

Conversation state is deterministic and lightweight. Do not add LLM-based state classification unless explicitly requested.

Scenario library data is static Python for now. Do not add a database for scenarios unless explicitly requested.

Interactive sessions are persisted through `JSONSessionStore` under `simulation/datasets/runs`. The current lab treats testers as trusted users, so shared history is visible through `/simulation/sessions` and the Recent Tests panel.

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

If the local pytest environment loads broken external plugins, use:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\test_simulation_api.py
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
- Keep Test mode simple, readable, and client-facing.
- Put raw prompts, completions, runtime context, and event logs behind Advanced mode.
