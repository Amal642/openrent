from simulation.scenarios.base import Scenario


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
    )


def get_default_scenario(
    *,
    max_turns: int = 1,
    start_mode: str = "agent_starts",
) -> Scenario:
    return get_outreach_screening_before_phone_scenario(
        max_turns=max_turns,
        start_mode=start_mode,
    )
