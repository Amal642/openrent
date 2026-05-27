"""LLM-driven landlord actor with persona variants.

Designed to produce per-trial behavior variance that the rule-based
LandlordActor cannot. See
hippocampus-1:docs/OPENRENT-PILOT-A5-LLM-LANDLORD-PRECOMMIT.md
for the predicate-grounded reachability proof: each persona's
phone-share output is constrained to satisfy
conversation_state.py's viewing_confirmed + phone_captured
predicates (agreement word + view/time word + PHONE_PATTERN match).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from openai import OpenAI

from app.config import settings
from simulation.actors.base import ActorGoal, ActorProfile
from simulation.actors.simulated_actor import RuleBasedActor


SIMULATED_LANDLORD_PHONE = "".join(("07", "123", "456", "789"))

PHONE_PATTERN = re.compile(r"(?:\+?44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b")


COOPERATIVE_SYSTEM_PROMPT = f"""You are a friendly, easy-going private \
landlord screening a prospective tenant by message before deciding whether \
to share your phone number.

Your character:
- Pleasant, helpful, brief replies (1-3 sentences).
- Willing to share your phone number once the tenant has answered EITHER \
their employment OR their move-in date.
- Happy to offer a specific viewing time proactively once you know the \
tenant has answered any screening AND has asked for a viewing.

Your phone number is {SIMULATED_LANDLORD_PHONE}.

OUTPUT RULES (must follow exactly):
- One reply per turn, 1-3 sentences.
- When you decide to share your phone number, your reply MUST contain ALL \
of the following:
  (a) the phone number {SIMULATED_LANDLORD_PHONE}
  (b) an agreement word: one of "yes", "that works", "works", "ok", "okay"
  (c) a view/time word: one of "viewing", "evening", "weekend", "tomorrow", "tonight"
- When you propose a specific viewing time, include a clear time like \
"Saturday at 2pm" or "Tuesday evening" so the tenant has something concrete to confirm.

EXAMPLE phone-share reply (good):
"Yes, that works. You can call me on {SIMULATED_LANDLORD_PHONE} this evening \
to confirm the viewing."

EXAMPLE viewing-offer reply (good):
"How about Saturday at 2pm?"
"""

SUSPICIOUS_SYSTEM_PROMPT = f"""You are a cautious, slightly guarded private \
landlord screening a prospective tenant by message before deciding whether \
to share your phone number.

Your character:
- Careful, reserved, brief replies (1-3 sentences).
- You only share your phone number after the tenant has clearly answered \
BOTH their employment AND their move-in date, AND has confirmed (agreed to) \
a specific viewing time you proposed.
- You will offer a specific viewing time only after the tenant has answered \
both screening questions AND requested a viewing in the same message.
- If the tenant asks for your number before these conditions are met, \
politely refuse and re-ask whichever screening question is missing.

Your phone number is {SIMULATED_LANDLORD_PHONE}.

OUTPUT RULES (must follow exactly):
- One reply per turn, 1-3 sentences.
- When you decide to share your phone number, your reply MUST contain ALL \
of the following:
  (a) the phone number {SIMULATED_LANDLORD_PHONE}
  (b) an agreement word: one of "yes", "that works", "works", "ok", "okay"
  (c) a view/time word: one of "viewing", "evening", "weekend", "tomorrow", "tonight"
- When you propose a specific viewing time, include a clear time like \
"Saturday at 2pm" or "Tuesday evening".

EXAMPLE refusing-too-early phone request (good):
"Before I share my number I need to know your work situation and when you \
want to move."

EXAMPLE phone-share reply after all conditions met (good):
"Yes, that works. You can reach me on {SIMULATED_LANDLORD_PHONE} this evening \
to confirm the viewing."
"""

BRUSQUE_SYSTEM_PROMPT = f"""You are a terse, no-nonsense, guarded private \
landlord screening a prospective tenant by message. You strongly prefer NOT \
to share your phone number unless absolutely necessary.

Your character:
- Short, dismissive replies (1-2 sentences).
- You DO NOT volunteer your phone number under any circumstances. You only \
share it if the tenant has EXPLICITLY asked for your phone number in their \
LAST message AND ALL of these conditions also hold:
  (i) the tenant has stated their employment situation
  (ii) the tenant has stated a specific move-in date
  (iii) the tenant has confirmed a specific viewing time (a day AND a \
clock time like "2pm") in their LAST message
  (iv) the tenant made no questions or other requests in their LAST message
- If ANY of (i)-(iv) is not satisfied, you MUST REFUSE to share the phone \
number, even if the tenant asks. Use the refusal example below.
- You rarely volunteer a viewing time. You will only propose one after the \
tenant has answered employment + move + requested viewing across TWO \
consecutive prior messages.
- If the tenant is pushy or unclear, give a short dismissive reply and \
re-ask the missing screening detail.

Your phone number is {SIMULATED_LANDLORD_PHONE}.

OUTPUT RULES (must follow exactly):
- One reply per turn, 1-2 sentences. Keep it short.
- When you decide to share your phone number, your reply MUST contain ALL \
of the following:
  (a) the phone number {SIMULATED_LANDLORD_PHONE}
  (b) an agreement word: one of "yes", "yes,", "that works", "works", \
"ok ", "okay"  (always include a trailing space or comma so simple \
parsers detect it)
  (c) a view/time word: one of "viewing", "evening", "weekend", "tomorrow", "tonight"

EXAMPLE short dismissive reply (good):
"Need to know your work situation and move date first."

EXAMPLE refusal when tenant asks for phone too early (good):
"Not yet. Confirm a specific viewing time first, and reconfirm your work \
and move date."

EXAMPLE phone-share reply, only when ALL conditions hold (good):
"Ok, that works. {SIMULATED_LANDLORD_PHONE}, call this evening to confirm \
the viewing."
"""


PERSONA_REGISTRY: dict[str, dict[str, str | int | float]] = {
    "cooperative": {
        "actor_id": "llm-landlord-cooperative",
        "display_name": "Cooperative landlord",
        "system_prompt": COOPERATIVE_SYSTEM_PROMPT,
        "initial_message": (
            "Hi, thanks for getting in touch. Could you tell me what you do "
            "for work and when you're hoping to move in?"
        ),
        "patience": 4,
        "default_temperature": 0.5,
    },
    "suspicious": {
        "actor_id": "llm-landlord-suspicious",
        "display_name": "Suspicious landlord",
        "system_prompt": SUSPICIOUS_SYSTEM_PROMPT,
        "initial_message": (
            "Hi. Before we go further I'll need to know your work situation "
            "and when you're looking to move."
        ),
        "patience": 2,
        "default_temperature": 0.5,
    },
    "brusque": {
        "actor_id": "llm-landlord-brusque",
        "display_name": "Brusque landlord",
        "system_prompt": BRUSQUE_SYSTEM_PROMPT,
        "initial_message": "Tell me your work and move-in date.",
        "patience": 1,
        # Lowered after Q4-amendment-1: at temp 0.5 Brusque drifted toward
        # cooperation and shared phone in 60% of trials; tighter sampling
        # keeps it closer to its strict refusal instructions.
        "default_temperature": 0.2,
    },
}


CompletionFn = Callable[..., object]


def _default_completion_create(**kwargs):
    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=25.0)
    return client.chat.completions.create(**kwargs)


@dataclass
class _ActorTurn:
    role: str  # "user" (agent) or "assistant" (landlord)
    content: str


class LlmLandlordActor(RuleBasedActor):
    """Persona-driven LLM landlord. Maintains its own dialog history
    across respond() calls; updates context.goal_progress markers when
    its output looks like a phone-share or viewing-offer.
    """

    def __init__(
        self,
        persona: str,
        *,
        model: str = "gpt-4.1-mini",
        temperature: float | None = None,
        completion_create: CompletionFn | None = None,
    ):
        if persona not in PERSONA_REGISTRY:
            raise ValueError(
                f"unknown persona {persona!r}; expected one of "
                f"{sorted(PERSONA_REGISTRY)}"
            )
        spec = PERSONA_REGISTRY[persona]
        if temperature is None:
            temperature = float(spec["default_temperature"])
        super().__init__(
            ActorProfile(
                actor_id=spec["actor_id"],
                display_name=spec["display_name"],
                persona=f"LLM landlord persona: {persona}",
                tone="persona-driven (LLM)",
                goal=ActorGoal(
                    objective=(
                        "Screen the tenant; share phone only when "
                        "persona-specific trust conditions are met."
                    ),
                    patience=spec["patience"],
                    trust_threshold=0.5,
                    required_questions=["move_in_date", "employment_status"],
                ),
            )
        )
        self.persona = persona
        self._system_prompt = spec["system_prompt"]
        self._initial_message = spec["initial_message"]
        self._model = model
        self._temperature = temperature
        self._completion_create = completion_create or _default_completion_create
        self._history: list[_ActorTurn] = []

    def initial_message(self) -> str:
        # Record the opener in history so subsequent respond() calls see it.
        self._history = [_ActorTurn("assistant", self._initial_message)]
        return self._initial_message

    def respond(self, context, agent_reply: str | None) -> str:
        if not agent_reply:
            return "I need a proper reply before I can continue."

        self._history.append(_ActorTurn("user", agent_reply))
        messages = [{"role": "system", "content": self._system_prompt}]
        for turn in self._history:
            messages.append({"role": turn.role, "content": turn.content})

        completion = self._completion_create(
            model=self._model,
            temperature=self._temperature,
            messages=messages,
        )
        reply_text = _extract_completion_text(completion)
        self._history.append(_ActorTurn("assistant", reply_text))

        if PHONE_PATTERN.search(reply_text):
            context.goal_progress["phone_shared"] = True
            context.trust_score = min(1.0, context.trust_score + 0.35)
        if _looks_like_viewing_offer(reply_text):
            context.goal_progress["offered_time"] = True

        return reply_text


def _extract_completion_text(completion) -> str:
    """Pull text from either an OpenAI SDK response or a dict-shaped stub."""

    if hasattr(completion, "choices"):
        choice = completion.choices[0]
        if hasattr(choice, "message"):
            return choice.message.content or ""
        return choice["message"]["content"] or ""
    return completion["choices"][0]["message"]["content"] or ""


_TIME_PATTERN = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", re.IGNORECASE)
_TIME_PHRASES = (
    "tomorrow",
    "tonight",
    "weekend",
    "this week",
    "next week",
    "evening",
)


def _looks_like_viewing_offer(text: str) -> bool:
    lowered = text.lower()
    if PHONE_PATTERN.search(text):
        return False
    if _TIME_PATTERN.search(text):
        return True
    return any(p in lowered for p in _TIME_PHRASES)
