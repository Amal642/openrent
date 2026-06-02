from simulation.conversation_state import analyze_conversation_state
from simulation.sessions.transcript import ConversationTurn


def _turn(speaker: str, message: str, index: int = 0):
    return ConversationTurn(
        speaker=speaker,
        message=message,
        turn_index=index,
        source_event="TEST",
    )


def test_viewing_opener_marks_viewing_requested():
    state = analyze_conversation_state(
        [
            _turn(
                "agent",
                "Hi, I'm Mary. Would it be possible to arrange a viewing this week?",
            ),
        ],
        "viewing_first_v1",
    )

    assert state.signals.viewing_requested is True
    assert state.current_state in {"initial_interest", "viewing_negotiation"}


def test_phone_ask_before_viewing_confirmation_is_too_early():
    state = analyze_conversation_state(
        [_turn("agent", "Could you share your phone number please?")],
        "viewing_first_v1",
    )

    assert state.signals.phone_requested is True
    assert state.signals.phone_requested_too_early is True


def test_viewing_confirmed_then_phone_ask_is_not_too_early():
    state = analyze_conversation_state(
        [
            _turn("agent", "Could we arrange a viewing this week?", 0),
            _turn("actor", "Tomorrow at 6pm works for a viewing.", 1),
            _turn("agent", "Great, could you share your phone number for coordination?", 1),
        ],
        "viewing_first_v1",
    )

    assert state.signals.viewing_confirmed is True
    assert state.signals.phone_requested is True
    assert state.signals.phone_requested_too_early is False


def test_corpus_number_capture_allows_phone_request_after_viewing_progress():
    state = analyze_conversation_state(
        [
            _turn("actor", "What do you do and when can you view?", 0),
            _turn(
                "agent",
                (
                    "I work full-time and can move next month. "
                    "Would Saturday work for a viewing, and could you send the best number in case of delays?"
                ),
                1,
            ),
        ],
        "corpus_number_capture_v1",
    )

    assert state.signals.phone_requested is True
    assert state.signals.viewing_requested is True
    assert state.signals.viewing_time_offered is True
    assert state.signals.phone_requested_too_early is False


def test_ai_push_after_landlord_phone_refusal_is_flagged():
    state = analyze_conversation_state(
        [
            _turn("agent", "Could you share your phone number please?", 0),
            _turn("actor", "I can't share my phone number right now.", 1),
            _turn("agent", "Could you still send your number?", 1),
        ],
        "viewing_first_v1",
    )

    assert state.signals.landlord_refused_phone is True
    assert state.signals.ai_pushed_after_refusal is True
