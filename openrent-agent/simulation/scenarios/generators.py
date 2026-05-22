from simulation.scenarios.base import Scenario


HACKNEY_2BED = {
    "title": "2 bed flat near Hackney Central",
    "bedrooms": 2,
    "rent_pcm": 1450,
    "location": "Hackney, East London",
    "furnished": True,
    "available_from": "next month",
}

SHOREDITCH_1BED = {
    "title": "1 bed flat in Shoreditch",
    "bedrooms": 1,
    "rent_pcm": 1200,
    "location": "Shoreditch, East London",
    "furnished": True,
    "available_from": "now",
}

PECKHAM_3BED = {
    "title": "3 bed terraced house in Peckham",
    "bedrooms": 3,
    "rent_pcm": 1900,
    "location": "Peckham, South London",
    "furnished": False,
    "available_from": "in two weeks",
}


SCREENING_LANDLORD_BRIEF = {
    "headline": "Cautious landlord — screens before sharing contact details",
    "disposition": (
        "You want to know who you are dealing with before sharing your phone number. "
        "Ask about jobs, household, and move-in date naturally before agreeing to a viewing."
    ),
    "phone_number": "07700 900123",
    "phone_rule": "Share only after a viewing is agreed or close to agreed.",
    "viewing_availability": "Weekday evenings after 6pm, or Saturday morning.",
}


COOPERATIVE_LANDLORD_BRIEF = {
    "headline": "Open landlord — happy to arrange a viewing",
    "disposition": (
        "You are friendly and direct. You are willing to suggest a viewing time early "
        "and ask only light screening questions."
    ),
    "phone_number": "07700 900234",
    "phone_rule": "Share once a specific viewing time is agreed.",
    "viewing_availability": "Tomorrow evening, or this Saturday afternoon.",
}


FOLLOWUP_LANDLORD_BRIEF = {
    "headline": "Busy landlord — already asked screening questions",
    "disposition": (
        "You messaged first asking about their job, household, and move-in date. "
        "Reply naturally based on how thorough their answer is. You are willing to "
        "suggest a viewing once basic screening is satisfied."
    ),
    "phone_number": "07700 900345",
    "phone_rule": "Share when a viewing time is agreed.",
    "viewing_availability": "Tomorrow evening or Saturday afternoon.",
}


def get_outreach_screening_before_phone_scenario(
    *,
    max_turns: int = 1,
    start_mode: str = "agent_starts",
) -> Scenario:
    return Scenario(
        scenario_id="outreach-screening-before-phone",
        title="Initial outreach before landlord screening",
        description=(
            "The tenant opens with the production-style outreach template, then "
            "the landlord screens employment and move timing before sharing a phone number."
        ),
        success_criteria=[
            "Send the production-like initial outreach template first.",
            "Answer the landlord's screening questions after they reply.",
            "Capture the phone number if shared.",
        ],
        stop_conditions=[
            "Phone number captured.",
            "Maximum turn count reached.",
        ],
        start_mode=start_mode,
        expected_signals=[
            "initial_template_sent",
            "phone_request",
            "employment_answer",
            "move_in_answer",
        ],
        max_turns=max_turns,
        property=HACKNEY_2BED,
        landlord_brief=SCREENING_LANDLORD_BRIEF,
        persona_type="young_professional_couple",
    )


def get_outreach_phone_request_scenario(
    *,
    max_turns: int = 1,
    start_mode: str = "agent_starts",
) -> Scenario:
    return Scenario(
        scenario_id="outreach-phone-request",
        title="Initial outreach asks for phone number",
        description=(
            "The tenant opens first with a template that asks for the landlord's "
            "phone number, and the landlord replies with screening questions."
        ),
        success_criteria=[
            "Send a realistic initial outreach opener.",
            "Keep the phone-request trajectory coherent after the landlord replies.",
            "Capture the phone number if shared.",
        ],
        stop_conditions=[
            "Phone number captured.",
            "Maximum turn count reached.",
        ],
        start_mode=start_mode,
        expected_signals=[
            "initial_template_sent",
            "phone_request",
            "followup_coherence",
        ],
        max_turns=max_turns,
        property=SHOREDITCH_1BED,
        landlord_brief=COOPERATIVE_LANDLORD_BRIEF,
        persona_type="academic_researcher",
    )


def get_reply_after_landlord_question_scenario(
    *,
    max_turns: int = 1,
    start_mode: str = "actor_starts",
) -> Scenario:
    return Scenario(
        scenario_id="reply-after-landlord-question",
        title="Landlord already asked a screening question",
        description=(
            "A landlord has already messaged first and the tenant must answer "
            "naturally while moving the conversation toward phone capture."
        ),
        success_criteria=[
            "Answer the landlord's screening questions.",
            "Ask for the landlord's phone number naturally.",
            "Capture the phone number if shared.",
        ],
        stop_conditions=[
            "Phone number captured.",
            "Maximum turn count reached.",
        ],
        start_mode=start_mode,
        expected_signals=["phone_request", "employment_answer", "move_in_answer"],
        max_turns=max_turns,
        property=PECKHAM_3BED,
        landlord_brief=FOLLOWUP_LANDLORD_BRIEF,
        persona_type="engineer_consultant_couple",
    )


def list_interactive_scenarios() -> list[dict]:
    scenarios = [
        get_outreach_screening_before_phone_scenario(),
        get_outreach_phone_request_scenario(),
        get_reply_after_landlord_question_scenario(),
    ]
    return [
        {
            "scenario_id": s.scenario_id,
            "title": s.title,
            "start_mode": s.start_mode,
            "property": s.property,
        }
        for s in scenarios
    ]


def get_default_scenario(
    *,
    max_turns: int = 1,
    start_mode: str = "agent_starts",
) -> Scenario:
    return get_outreach_screening_before_phone_scenario(
        max_turns=max_turns,
        start_mode=start_mode,
    )
