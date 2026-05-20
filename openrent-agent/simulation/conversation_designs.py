from dataclasses import dataclass, field

from app.ai.personas import get_persona_template


VIEWING_FIRST_V1 = "viewing_first_v1"
PHONE_FIRST_V1 = "phone_first_v1"
SCREENING_FIRST_V1 = "screening_first_v1"
SOFT_HUMAN_V1 = "soft_human_v1"


@dataclass(frozen=True)
class ConversationDesign:
    design_id: str
    name: str
    description: str
    opening_message: str
    reply_prompt_rules: list[str]
    success_criteria: list[str]
    failure_criteria: list[str]
    metadata: dict = field(default_factory=dict)

    def render_opening_message(self, persona: dict | None = None) -> str:
        p = persona or {}
        name = p.get("persona_name") or "Mary"
        has_partner = bool(p.get("persona_partner_name"))
        tokens = {
            "persona_name": name,
            "my_partner_and_i_are": "My partner and I are" if has_partner else "I'm",
            "credentials_intro": (
                "We're both working professionals"
                if has_partner
                else "I'm a working professional"
            ),
        }
        return self.opening_message.format_map(tokens)


CONVERSATION_DESIGNS = {
    VIEWING_FIRST_V1: ConversationDesign(
        design_id=VIEWING_FIRST_V1,
        name="Viewing first",
        description=(
            "Progress naturally toward a viewing before asking for a phone "
            "number for coordination."
        ),
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in the property. "
            "Would it be possible to arrange a viewing sometime this week?"
        ),
        reply_prompt_rules=[
            "Primary goal: progress toward arranging or confirming a viewing.",
            "Answer landlord screening questions naturally and briefly.",
            "Do not ask for a phone number before a viewing is agreed or clearly close to agreed.",
            "After a viewing is agreed, ask for the phone number naturally for coordination.",
            "Avoid sounding scripted, pushy, or like you are harvesting contact details.",
        ],
        success_criteria=[
            "Progressed toward a viewing.",
            "Answered landlord questions naturally.",
            "Delayed phone request until coordination became reasonable.",
            "Asked for phone only after viewing progress justified it.",
        ],
        failure_criteria=[
            "Asked for phone before viewing progress.",
            "Ignored screening questions.",
            "Sounded overly scripted.",
            "Failed to move toward viewing.",
            "Pushed off-platform too early.",
        ],
    ),
    PHONE_FIRST_V1: ConversationDesign(
        design_id=PHONE_FIRST_V1,
        name="Phone first",
        description="Early phone-capture strategy retained for comparison.",
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in the property. "
            "Would you be able to share your number so we can have a quick chat?"
        ),
        reply_prompt_rules=[
            "Primary goal: request the landlord's phone number early but politely.",
            "Answer direct landlord questions briefly before asking for the phone number.",
            "Do not invent personal details or create pressure.",
        ],
        success_criteria=["Phone number captured.", "Tone remained natural."],
        failure_criteria=["Ignored landlord questions.", "Sounded pushy."],
    ),
    SCREENING_FIRST_V1: ConversationDesign(
        design_id=SCREENING_FIRST_V1,
        name="Screening first",
        description="Lead with tenant credibility before progressing to viewing.",
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in the property. "
            "{credentials_intro} and wanted to check if viewings are available."
        ),
        reply_prompt_rules=[
            "Primary goal: answer screening concerns and build credibility.",
            "Move toward a viewing once the landlord seems satisfied.",
        ],
        success_criteria=["Answered screening naturally.", "Progressed toward viewing."],
        failure_criteria=["Skipped screening questions.", "Failed to progress."],
    ),
    SOFT_HUMAN_V1: ConversationDesign(
        design_id=SOFT_HUMAN_V1,
        name="Soft human",
        description="Low-pressure conversational strategy with softer wording.",
        opening_message=(
            "Hi, I'm {persona_name}. I saw your property and it looks like it could be a good fit. "
            "Would it be possible to arrange a viewing?"
        ),
        reply_prompt_rules=[
            "Primary goal: keep the conversation warm, brief, and low-pressure.",
            "Avoid repeated asks and keep each reply natural.",
        ],
        success_criteria=["Sounded natural.", "Kept viewing progress alive."],
        failure_criteria=["Sounded scripted.", "Repeated the same ask."],
    ),
}


def get_conversation_design(design_id: str | None) -> ConversationDesign:
    return CONVERSATION_DESIGNS.get(
        design_id or VIEWING_FIRST_V1,
        CONVERSATION_DESIGNS[VIEWING_FIRST_V1],
    )


def list_conversation_designs() -> list[dict]:
    return [
        {
            "id": design.design_id,
            "name": design.name,
            "description": design.description,
            "success_criteria": design.success_criteria,
            "failure_criteria": design.failure_criteria,
        }
        for design in CONVERSATION_DESIGNS.values()
    ]


def default_simulation_persona() -> dict:
    template = get_persona_template("young_professional_couple") or {}
    names = template.get("names") or {}
    jobs = template.get("jobs") or {}
    return {
        "persona_type": template.get("persona_type", "young_professional_couple"),
        "persona_name": (names.get("primary") or ["Mary"])[0],
        "persona_partner_name": (names.get("partner") or ["Sophie"])[0],
        "persona_job": (jobs.get("primary") or ["Software Engineer"])[0],
        "persona_partner_job": (jobs.get("partner") or ["Project Coordinator"])[0],
        "household_description": template.get(
            "household_description",
            "young professional couple",
        ),
        "message_tone": template.get("message_tone", "friendly, direct, brief"),
        "home_city": template.get("home_city", "Manchester"),
        "display_name": template.get("display_name", "Young professional couple"),
    }
