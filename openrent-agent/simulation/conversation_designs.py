from dataclasses import dataclass, field

from app.ai.personas import get_persona_template


VIEWING_FIRST_V1 = "viewing_first_v1"
SCREENING_FIRST_V1 = "screening_first_v1"
CONFIRMATION_CLOSE_V1 = "confirmation_close_v1"
TENANT_SHARES_FIRST_V1 = "tenant_shares_first_v1"
LANDLORD_PREFERENCE_V1 = "landlord_preference_v1"
CORPUS_NUMBER_CAPTURE_V1 = "corpus_number_capture_v1"


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

    def render_opening_message(
        self,
        persona: dict | None = None,
        property: dict | None = None,
    ) -> str:
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
            "property_phrase": _property_phrase(property),
        }
        return self.opening_message.format_map(tokens)


def _property_phrase(property: dict | None) -> str:
    if not property:
        return "the property"
    bedrooms = property.get("bedrooms")
    location = property.get("location")
    if bedrooms and location:
        short_location = location.split(",")[0].strip()
        return f"the {bedrooms}-bed in {short_location}"
    title = property.get("title")
    if title:
        return f"the {title.lower()}"
    return "the property"


CONVERSATION_DESIGNS = {
    VIEWING_FIRST_V1: ConversationDesign(
        design_id=VIEWING_FIRST_V1,
        name="Viewing first",
        description=(
            "Progress naturally toward a viewing before asking for a phone "
            "number for coordination."
        ),
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in {property_phrase}. "
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
    SCREENING_FIRST_V1: ConversationDesign(
        design_id=SCREENING_FIRST_V1,
        name="Screening first",
        description="Build tenant credibility before progressing to viewing and contact.",
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in {property_phrase}. "
            "{credentials_intro} and wanted to check if viewings are available."
        ),
        reply_prompt_rules=[
            "Primary goal: build landlord confidence before asking for contact details.",
            "Answer screening questions about work, household, move date, and affordability directly.",
            "Use only persona details already available; do not invent extra credentials.",
            "Once the landlord seems comfortable, steer toward arranging a viewing.",
            "Ask for a number only after screening concerns are satisfied and viewing coordination is relevant.",
        ],
        success_criteria=[
            "Answered screening naturally.",
            "Built credibility without over-explaining.",
            "Progressed toward a viewing.",
            "Delayed phone request until trust or viewing progress existed.",
        ],
        failure_criteria=[
            "Skipped screening questions.",
            "Invented personal details.",
            "Asked for phone before credibility was established.",
            "Failed to progress toward viewing.",
        ],
    ),
    CONFIRMATION_CLOSE_V1: ConversationDesign(
        design_id=CONFIRMATION_CLOSE_V1,
        name="Confirmation close",
        description="Use a strict gate: ask for a number only after a viewing time is agreed.",
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in {property_phrase}. "
            "Would it be possible to arrange a viewing sometime this week?"
        ),
        reply_prompt_rules=[
            "Primary goal: reach a specific viewing date or time before any phone request.",
            "Do not ask for a number while the viewing is still vague or only generally discussed.",
            "After a date or time is agreed, ask for the best number as a logistics fallback.",
            "Use practical reasons only: delays, finding the entrance, directions, or last-minute changes.",
            "If no time is agreed yet, keep narrowing availability instead of asking for contact details.",
        ],
        success_criteria=[
            "Reached or confirmed a concrete viewing time.",
            "Asked for phone only after the viewing was agreed or nearly agreed.",
            "Framed phone as day-of-viewing logistics.",
            "Avoided sounding like contact capture was the main goal.",
        ],
        failure_criteria=[
            "Asked for phone before a viewing time was agreed.",
            "Used a vague or generic reason for requesting the number.",
            "Failed to narrow toward a concrete viewing time.",
            "Pushed after landlord hesitation.",
        ],
    ),
    TENANT_SHARES_FIRST_V1: ConversationDesign(
        design_id=TENANT_SHARES_FIRST_V1,
        name="Tenant shares first",
        description="Use reciprocity by sharing the tenant number first after viewing progress.",
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in {property_phrase}. "
            "Would it be possible to arrange a viewing sometime this week?"
        ),
        reply_prompt_rules=[
            "Primary goal: make contact exchange feel reciprocal, not extractive.",
            "Do not share the tenant mobile until viewing progress exists.",
            "Once a viewing is agreed or close, share the tenant mobile as optional coordination help.",
            "Invite the landlord to use whichever channel is easiest rather than demanding their number.",
            "Only ask for the landlord's best number after sharing yours if it is needed for viewing logistics.",
        ],
        success_criteria=[
            "Shared tenant number only after viewing progress.",
            "Made phone coordination optional and natural.",
            "Created a reasonable opportunity for landlord reciprocity.",
            "Kept the conversation focused on the viewing.",
        ],
        failure_criteria=[
            "Shared tenant number before viewing progress.",
            "Asked for landlord number immediately after sharing yours.",
            "Made the exchange feel transactional.",
            "Failed to progress toward viewing.",
        ],
    ),
    LANDLORD_PREFERENCE_V1: ConversationDesign(
        design_id=LANDLORD_PREFERENCE_V1,
        name="Landlord preference",
        description="Let the landlord choose whether to coordinate in OpenRent or by phone.",
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in {property_phrase}. "
            "Would it be possible to arrange a viewing sometime this week?"
        ),
        reply_prompt_rules=[
            "Primary goal: keep the landlord in control of the coordination channel.",
            "Do not directly ask 'what is your number' unless the landlord has chosen phone coordination.",
            "When viewing coordination is relevant, ask whether they prefer to arrange it here or by phone.",
            "If the landlord prefers OpenRent messages, continue there without pushing.",
            "If the landlord prefers phone, ask for the best number or share the tenant mobile naturally.",
        ],
        success_criteria=[
            "Asked for the landlord's preferred coordination channel.",
            "Respected OpenRent messaging if the landlord preferred it.",
            "Moved toward viewing without pressure.",
            "Captured or shared phone only when the landlord opted into phone coordination.",
        ],
        failure_criteria=[
            "Asked for phone directly before offering channel choice.",
            "Ignored the landlord's preferred channel.",
            "Pushed off-platform too early.",
            "Failed to progress toward viewing.",
        ],
    ),
    CORPUS_NUMBER_CAPTURE_V1: ConversationDesign(
        design_id=CORPUS_NUMBER_CAPTURE_V1,
        name="Corpus number capture",
        description=(
            "Use successful corpus patterns to capture landlord numbers through "
            "natural viewing and logistics coordination."
        ),
        opening_message=(
            "Hi, I'm {persona_name}. {my_partner_and_i_are} interested in {property_phrase}. "
            "Would it be possible to arrange a viewing?"
        ),
        reply_prompt_rules=[
            "Primary goal: get a landlord contact number naturally, without making it look like the number is the main goal.",
            "Use viewing progress as the gate: viewing, video viewing, timing, travel, directions, delays, or day-of-viewing logistics must be in play before asking.",
            "Before that gate exists, answer screening questions and keep moving toward a viewing or video viewing.",
            "If the landlord asks screening questions before sharing contact details, answer them first, then ask about viewing and include a soft request for the landlord's best number for coordination.",
            "If you have just answered screening and proposed or narrowed a viewing time/window, do not skip the number ask; include it as a low-pressure logistics fallback.",
            "Do not volunteer or share the tenant mobile number; this design is for getting the landlord's number.",
            "Write like a real tenant texting: brief, casual, practical, and a little imperfect rather than polished.",
            "When asking for contact details, use one concrete logistics reason such as driving down, confirming timing, finding the entrance, directions, delays, or video-viewing coordination.",
            "Avoid eager or scripted phrases like 'kindly share your contact details', repeated WhatsApp pushes, long reassurance, or generic empathy.",
            "If the landlord resists phone or WhatsApp, continue on OpenRent and do not push again immediately.",
        ],
        success_criteria=[
            "Captured landlord number or created a natural opening for the landlord to share one.",
            "Asked only after viewing or logistics progress existed.",
            "Answered screening before steering back to coordination.",
            "Sounded like a casual tenant message rather than assistant prose.",
        ],
        failure_criteria=[
            "Asked for phone, WhatsApp, or contact details before viewing/logistics progress.",
            "Made the number request feel like the main goal.",
            "Used formal, repetitive, or AI-like phrasing.",
            "Ignored landlord screening questions.",
            "Pushed again after the landlord resisted off-platform contact.",
        ],
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


_PERSONA_MOBILES = {
    "young_professional_couple": 7743722832,
    "nhs_medical_worker": 7700900456,
    "engineer_consultant_couple": 7700900789,
    "quiet_it_worker": 7700900112,
    "academic_researcher": 7700900223,
}


def build_simulation_persona(
    persona_type: str | None = None,
    property: dict | None = None,
) -> dict:
    template = (
        get_persona_template(persona_type or "young_professional_couple")
        or get_persona_template("young_professional_couple")
        or {}
    )
    names = template.get("names") or {}
    jobs = template.get("jobs") or {}
    partner_names = names.get("partner") or []
    partner_jobs = jobs.get("partner") or []
    rent_pcm = (property or {}).get("rent_pcm") or 1450
    resolved_type = template.get("persona_type", "young_professional_couple")
    return {
        "persona_type": resolved_type,
        "persona_name": (names.get("primary") or ["Mary"])[0],
        "persona_partner_name": partner_names[0] if partner_names else None,
        "persona_job": (jobs.get("primary") or ["Professional"])[0],
        "persona_partner_job": partner_jobs[0] if partner_jobs else None,
        "household_description": template.get("household_description", "tenant"),
        "mobile_number": _PERSONA_MOBILES.get(resolved_type, 7743722832),
        "message_tone": template.get("message_tone", "friendly, direct, brief"),
        "home_city": template.get("home_city", "Manchester"),
        "display_name": template.get("display_name", "Tenant"),
        "bedrooms": (property or {}).get("bedrooms") or 2,
        "rent_pcm": rent_pcm,
        "salary": (rent_pcm * 30) + 20000,
        "property_location": (property or {}).get("location") or "London",
    }


def default_simulation_persona() -> dict:
    return build_simulation_persona("young_professional_couple", None)
