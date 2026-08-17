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


def test_booked_reply_routes_to_reframe_when_human_prompt_enabled(monkeypatch):
    """A booked viewing must go through the human reframe (which asks once,
    accepts refusal, never claims to be travelling, and withdraws cleanly), NOT
    the single-purpose phone-request prompt that spams asks + seeds fake-travel
    no-show spirals. Regression guard for the Claude Road / E10 audit."""
    monkeypatch.setenv("HUMAN_REPLY_PROMPT", "all")
    prompt = build_reply_prompt(
        "LANDLORD: Are you coming? You're late, it's 4pm. Where are you?",
        stage="VIEWING_BOOKED",
        persona=PERSONA,
        place="Leicester",
        landlord_asked_for_number=False,
    )

    assert "real person who wants to rent" in prompt  # reframe marker
    assert "A viewing has already been arranged" not in prompt  # phone-request marker


def test_booked_reply_falls_back_to_phone_request_when_reframe_disabled(monkeypatch):
    """Flag off -> the old phone-request prompt is preserved (fully reversible)."""
    monkeypatch.setenv("HUMAN_REPLY_PROMPT", "0")
    prompt = build_reply_prompt(
        "LANDLORD: Tomorrow at 7pm works.",
        stage="VIEWING_BOOKED",
        persona=PERSONA,
        place="Leicester",
        landlord_asked_for_number=False,
    )

    assert "A viewing has already been arranged" in prompt
    assert "Leicester" in prompt


def test_reframe_uses_single_plausible_origin_when_place_given(monkeypatch):
    """Geography reconciliation: with a travel origin, the reframe states ONE
    consistent place (relocating from it) instead of "claim a local area", so it
    no longer contradicts the pre-cancel ask's "travelling in from {place}"."""
    from app.ai.prompts import build_human_renter_reply_prompt

    p = build_human_renter_reply_prompt(
        conversation="Landlord: Where do you live?", persona=PERSONA, place="Oxford"
    )
    assert "relocating to this area from Oxford" in p
    assert "give a nearby local area" not in p
    # The anti-presence rule must survive (origin is not a licence to narrate a journey).
    assert "Never claim to be on your way" in p


def test_reframe_falls_back_to_local_without_place():
    from app.ai.prompts import build_human_renter_reply_prompt

    p = build_human_renter_reply_prompt(conversation="x", persona=PERSONA)
    assert "give a nearby local area" in p


def test_drive_distance_targets_short_journey_not_far_city():
    from app.ai.prompts import build_drive_distance

    prompt = build_drive_distance("Bourne End SL8")
    assert "1 to 2 hour" in prompt
    assert "4 to 5 hours" not in prompt


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
