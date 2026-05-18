from app.ai.prompts import (
    build_initial_enquiry_prompt,
    build_phone_request_prompt,
    build_reply_prompt,
)
from app.ai.replies import _normalize_place_name, generate_distant_location


PERSONA = {
    "persona_name": "James",
    "persona_partner_name": "Sophie",
    "persona_job": "Software Engineer",
    "persona_partner_job": "Project Coordinator",
    "household_description": "professional couple",
    "message_tone": "friendly, direct, brief",
    "home_city": "Manchester",
}


def test_initial_enquiry_prompt_does_not_ask_for_phone():
    prompt = build_initial_enquiry_prompt(
        {"bedrooms": 2, "rent_pcm": 1600},
        PERSONA,
    )

    assert "ask for the landlord's phone number" not in prompt.lower()
    assert "viewing appointment" in prompt.lower()


def test_non_booked_reply_prompt_does_not_ask_for_phone():
    prompt = build_reply_prompt(
        "LANDLORD: When would you like to view it?",
        stage="VIEWING_DISCUSSION",
        persona=PERSONA,
    )

    assert "ask for the landlord's phone number" not in prompt.lower()
    assert "arrange or confirm a viewing naturally" in prompt.lower()


def test_booked_reply_prompt_uses_dynamic_place():
    prompt = build_reply_prompt(
        "LANDLORD: Tomorrow at 7pm works.",
        stage="VIEWING_BOOKED",
        persona=PERSONA,
        place="Leicester",
    )

    assert "Leicester" in prompt
    assert "phone number" in prompt


def test_phone_request_prompt_mentions_coordination():
    prompt = build_phone_request_prompt(
        "LANDLORD: See you tomorrow.",
        place="Nottingham",
        viewing_location="the viewing",
    )

    assert "Nottingham" in prompt
    assert "coordinate" in prompt.lower()


def test_normalize_place_name_keeps_single_location():
    assert _normalize_place_name("  derby  ") == "Derby"
    assert _normalize_place_name("Leicester, UK") == "Leicester UK"


def test_generate_distant_location_uses_fallback_on_empty_response(monkeypatch):
    class DummyMessage:
        content = "   "

    class DummyChoice:
        message = DummyMessage()

    class DummyResponse:
        choices = [DummyChoice()]

    class DummyCompletions:
        @staticmethod
        def create(**kwargs):
            return DummyResponse()

    class DummyChat:
        completions = DummyCompletions()

    class DummyClient:
        chat = DummyChat()

    monkeypatch.setattr("app.ai.replies.client", DummyClient())

    place = generate_distant_location("Leeds")
    assert place
