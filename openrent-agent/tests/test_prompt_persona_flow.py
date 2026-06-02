from app.ai.prompts import (
    build_initial_enquiry_prompt,
    build_phone_request_prompt,
    build_reply_prompt,
    generate_message_persona_prompt,
)
from app.ai.replies import generate_reply
from app.ai.replies import _normalize_place_name, generate_distant_location


ASSIGNED_MOBILE = "+" + "".join(("44", "7900", "111", "222"))

PERSONA = {
    "persona_name": "James",
    "persona_partner_name": "Sophie",
    "persona_job": "Software Engineer",
    "persona_partner_job": "Project Coordinator",
    "household_description": "professional couple",
    "message_tone": "friendly, direct, brief",
    "home_city": "Manchester",
    "mobile_number": ASSIGNED_MOBILE,
    "phone_fetching_type": "delayed",
    "message_strategy": "friendly viewing first",
    "escalation_behavior": "wait until logistics are specific",
    "conversation_goal": "arrange a viewing and coordinate contact details",
    "conversation_style": "friendly_viewing",
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


def test_dynamic_prompt_includes_phone_policy_and_landlord_attitude():
    prompt = generate_message_persona_prompt(
        conversation="LANDLORD: What is your WhatsApp?",
        stage="VIEWING_DISCUSSION",
        persona=PERSONA,
        landlord_attitude="friendly",
        conversation_style="whatsapp_coordination",
        landlord_asked_for_number=True,
        phone_number_shared=False,
        outbound_count=1,
    )

    assert ASSIGNED_MOBILE in prompt
    assert "Landlord attitude memory: friendly" in prompt
    assert "ALWAYS share the exact correct tenant mobile number" in prompt


def test_corpus_number_capture_prompt_hides_tenant_mobile_and_targets_landlord_number():
    prompt = generate_message_persona_prompt(
        conversation="LANDLORD: Tomorrow at 6 could work.",
        stage="VIEWING_DISCUSSION",
        persona=PERSONA,
        conversation_design_id="corpus_number_capture_v1",
        viewing_requested=True,
        landlord_asked_for_number=True,
    )

    assert ASSIGNED_MOBILE not in prompt
    assert "obtain the landlord's number" in prompt
    assert "do not share the tenant mobile number" in prompt
    assert "do not skip the number ask" in prompt
    assert "landlord's best number" in prompt
    assert "follow the phone sharing policy for this conversation design" in prompt


def test_corpus_number_capture_v2_uses_boundary_and_refusal_rules():
    prompt = generate_message_persona_prompt(
        conversation=(
            "LANDLORD: I don't share my number before a viewing is booked.\n"
            "TENANT: No worries, we can keep it here for now. Would Saturday work?\n"
            "LANDLORD: Saturday at 2pm is booked."
        ),
        stage="VIEWING_BOOKED",
        persona={
            **PERSONA,
            "screening_posture": "both applicants are working professionals",
            "phone_boundary": "prefer not to share the tenant mobile before meeting",
        },
        conversation_design_id="corpus_number_capture_v2",
        viewing_requested=True,
        landlord_asked_for_number=True,
    )

    assert ASSIGNED_MOBILE not in prompt
    assert "past bad experiences" in prompt
    assert "do not share the tenant mobile number" in prompt
    assert "do not ask again in the next tenant reply" in prompt
    assert "do not instantly ask for the number" in prompt
    assert "Screening posture: both applicants are working professionals" in prompt


def test_generate_reply_shares_correct_number_when_landlord_asks():
    reply, error = generate_reply(
        [{"sender": "landlord", "message": "Can you share your WhatsApp number?"}],
        stage="VIEWING_DISCUSSION",
        persona=PERSONA,
        landlord_attitude="friendly",
    )

    assert error is None
    assert ASSIGNED_MOBILE in reply


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
