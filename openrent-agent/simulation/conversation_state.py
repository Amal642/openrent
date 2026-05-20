import re
from dataclasses import asdict, dataclass


PHONE_PATTERN = re.compile(r"(?:\+?44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b")
TIME_PATTERN = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", re.IGNORECASE)


@dataclass
class ConversationSignals:
    viewing_requested: bool = False
    screening_questions_asked: bool = False
    screening_answered: bool = False
    viewing_time_offered: bool = False
    viewing_confirmed: bool = False
    phone_requested: bool = False
    phone_requested_too_early: bool = False
    phone_captured: bool = False
    landlord_refused_phone: bool = False
    ai_pushed_after_refusal: bool = False
    conversation_stalled: bool = False


@dataclass
class ConversationState:
    current_state: str
    signals: ConversationSignals
    rationale: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _turn_speaker(turn) -> str:
    if isinstance(turn, dict):
        return turn.get("speaker") or ""
    return getattr(turn, "speaker", "")


def _turn_message(turn) -> str:
    if isinstance(turn, dict):
        return turn.get("message") or ""
    return getattr(turn, "message", "")


def _contains_any(text: str, tokens: list[str]) -> bool:
    return any(token in text for token in tokens)


def _contains_word_any(text: str, tokens: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(token)}\b", text) for token in tokens)


def _is_ai_phone_request(text: str) -> bool:
    phone_language = _contains_any(
        text,
        ["phone", "number", "mobile", "contact", "call"],
    )
    request_language = _contains_any(
        text,
        ["share", "send", "provide", "give", "could you", "can you", "would you"],
    )
    return phone_language and request_language


def _is_landlord_phone_refusal(text: str) -> bool:
    refusal_language = _contains_any(
        text,
        ["can't", "cannot", "wont", "won't", "not now", "rather not", "no phone"],
    )
    phone_language = _contains_any(text, ["phone", "number", "mobile", "call"])
    return refusal_language and phone_language


def analyze_conversation_state(
    transcript,
    conversation_design_id: str | None = None,
) -> ConversationState:
    signals = ConversationSignals()
    rationale: list[str] = []
    ai_phone_request_indexes: list[int] = []
    refusal_indexes: list[int] = []

    for index, turn in enumerate(transcript or []):
        speaker = _turn_speaker(turn)
        raw_message = _turn_message(turn)
        message = raw_message.lower()

        if speaker == "agent":
            if _contains_any(
                message,
                ["viewing", "view", "come and see", "arrange a viewing", "arrange a time"],
            ):
                signals.viewing_requested = True
            if _is_ai_phone_request(message):
                signals.phone_requested = True
                ai_phone_request_indexes.append(index)
            if _contains_word_any(
                message,
                ["work", "working", "job", "employed", "move", "moving", "we are both"],
            ):
                signals.screening_answered = True
            if _contains_any(
                message,
                ["tomorrow", "tonight", "weekend", "this week", "next week", "evening"],
            ) or TIME_PATTERN.search(message):
                signals.viewing_time_offered = True

        if speaker == "actor":
            if PHONE_PATTERN.search(raw_message):
                signals.phone_captured = True
            if _contains_word_any(
                message,
                ["work", "job", "employed", "employment", "income", "reference", "move"],
            ):
                signals.screening_questions_asked = True
            if _contains_any(
                message,
                ["tomorrow", "tonight", "weekend", "this week", "next week", "evening"],
            ) or TIME_PATTERN.search(message):
                signals.viewing_time_offered = True
            if _contains_any(
                message,
                [
                    "confirmed",
                    "booked",
                    "that works",
                    "works for me",
                    "works",
                    "see you",
                    "yes,",
                    "yes ",
                    "ok ",
                    "okay ",
                ],
            ) and _contains_any(
                message,
                ["view", "viewing", "tomorrow", "tonight", "weekend", "week", "pm", "am"],
            ):
                signals.viewing_confirmed = True
            if _is_landlord_phone_refusal(message):
                signals.landlord_refused_phone = True
                refusal_indexes.append(index)

    if signals.screening_questions_asked:
        signals.screening_answered = signals.screening_answered or _screening_answered_after_question(
            transcript or [],
        )

    if signals.phone_requested and not signals.viewing_confirmed:
        signals.phone_requested_too_early = True

    if refusal_indexes:
        first_refusal = min(refusal_indexes)
        signals.ai_pushed_after_refusal = any(
            request_index > first_refusal for request_index in ai_phone_request_indexes
        )

    signals.conversation_stalled = _is_stalled(
        transcript or [],
        signals,
        conversation_design_id,
    )

    current_state = _derive_current_state(signals)
    _append_rationale(rationale, signals, current_state)
    return ConversationState(
        current_state=current_state,
        signals=signals,
        rationale=rationale,
    )


def _screening_answered_after_question(transcript) -> bool:
    question_seen = False
    for turn in transcript:
        speaker = _turn_speaker(turn)
        message = _turn_message(turn).lower()
        if speaker == "actor" and _contains_word_any(
            message,
            ["work", "job", "employed", "employment", "income", "reference", "move"],
        ):
            question_seen = True
        if question_seen and speaker == "agent" and _contains_word_any(
            message,
            ["work", "working", "job", "employed", "move", "moving", "income"],
        ):
            return True
    return False


def _is_stalled(
    transcript,
    signals: ConversationSignals,
    conversation_design_id: str | None,
) -> bool:
    if signals.ai_pushed_after_refusal:
        return True
    if len(transcript) < 3:
        return False
    if conversation_design_id == "viewing_first_v1":
        return not (
            signals.viewing_requested
            or signals.viewing_time_offered
            or signals.viewing_confirmed
        )
    return not (
        signals.viewing_requested
        or signals.screening_answered
        or signals.phone_captured
    )


def _derive_current_state(signals: ConversationSignals) -> str:
    if signals.phone_captured:
        return "phone_captured"
    if signals.conversation_stalled:
        return "stalled"
    if signals.phone_requested and signals.viewing_confirmed:
        return "coordination"
    if signals.viewing_confirmed:
        return "viewing_confirmed"
    if signals.viewing_requested or signals.viewing_time_offered:
        return "viewing_negotiation"
    if signals.screening_questions_asked:
        return "screening"
    return "initial_interest"


def _append_rationale(
    rationale: list[str],
    signals: ConversationSignals,
    current_state: str,
) -> None:
    if signals.viewing_requested:
        rationale.append("AI moved the conversation toward arranging a viewing.")
    if signals.screening_questions_asked and signals.screening_answered:
        rationale.append("Landlord screening questions were answered.")
    elif signals.screening_questions_asked:
        rationale.append("Landlord asked screening questions that still need an answer.")
    if signals.viewing_time_offered:
        rationale.append("A viewing time or availability window appeared in the transcript.")
    if signals.viewing_confirmed:
        rationale.append("Viewing appears agreed or close to agreed.")
    if signals.phone_requested_too_early:
        rationale.append("AI asked for phone details before the viewing was confirmed.")
    if signals.landlord_refused_phone:
        rationale.append("Landlord refused or delayed sharing a phone number.")
    if signals.ai_pushed_after_refusal:
        rationale.append("AI pushed for phone details again after refusal.")
    if signals.phone_captured:
        rationale.append("A phone number was captured from the landlord.")
    if signals.conversation_stalled:
        rationale.append("Conversation appears stalled against the selected design goal.")
    if not rationale:
        rationale.append(f"Conversation is in {current_state.replace('_', ' ')}.")
