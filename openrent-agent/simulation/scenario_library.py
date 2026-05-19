from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ConversationScenario:
    scenario_id: str
    name: str
    description: str
    landlord_initial_message: str
    expected_state_direction: str
    tags: list[str]


SCENARIOS = [
    ConversationScenario(
        scenario_id="normal_viewing_offer",
        name="Normal viewing offer",
        description="Landlord is open to a viewing and offers a near-term time.",
        landlord_initial_message=(
            "Hi Mary, yes viewing is possible. Are you free tomorrow evening?"
        ),
        expected_state_direction="viewing_negotiation",
        tags=["viewing", "cooperative"],
    ),
    ConversationScenario(
        scenario_id="screening_before_viewing",
        name="Screening before viewing",
        description="Landlord asks qualification questions before arranging a viewing.",
        landlord_initial_message=(
            "Before arranging a viewing, can you tell me your job, income, "
            "and when you want to move in?"
        ),
        expected_state_direction="screening",
        tags=["screening", "viewing"],
    ),
    ConversationScenario(
        scenario_id="phone_refusal_before_viewing",
        name="Phone refusal before viewing",
        description="Landlord refuses phone sharing until a viewing is booked.",
        landlord_initial_message=(
            "I don't share my phone number before a viewing is booked. "
            "Please suggest a viewing time here."
        ),
        expected_state_direction="viewing_negotiation",
        tags=["phone-refusal", "viewing"],
    ),
    ConversationScenario(
        scenario_id="asks_for_tenant_phone_early",
        name="Asks for tenant phone early",
        description="Landlord asks the AI tenant to provide a phone number first.",
        landlord_initial_message="Can you send me your phone number first?",
        expected_state_direction="coordination",
        tags=["phone", "early-phone"],
    ),
    ConversationScenario(
        scenario_id="vague_landlord_reply",
        name="Vague landlord reply",
        description="Landlord gives a low-information reply that needs steering.",
        landlord_initial_message="Yes, maybe. What do you want to know?",
        expected_state_direction="initial_interest",
        tags=["vague", "steering"],
    ),
    ConversationScenario(
        scenario_id="viewing_confirmed_then_coordination",
        name="Viewing confirmed then coordination",
        description="Landlord confirms a viewing time, making coordination reasonable.",
        landlord_initial_message="Okay, tomorrow at 6pm works for the viewing.",
        expected_state_direction="viewing_confirmed",
        tags=["viewing-confirmed", "coordination"],
    ),
]


def list_conversation_scenarios() -> list[dict]:
    return [asdict(scenario) for scenario in SCENARIOS]


def get_conversation_scenario(scenario_id: str | None) -> ConversationScenario | None:
    if not scenario_id:
        return None
    for scenario in SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario
    return None
