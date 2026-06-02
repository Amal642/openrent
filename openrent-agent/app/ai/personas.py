import random
import re


PHONE_FETCHING_TYPES = {
    "delayed",
    "immediate",
    "viewing_first",
    "whatsapp_first",
    "landlord_requests_only",
    "adaptive",
}

LANDLORD_ATTITUDES = {
    "friendly",
    "cold",
    "aggressive",
    "responsive",
    "slow_reply",
    "suspicious",
    "helpful",
}

CONVERSATION_STYLES = {
    "friendly_viewing": {
        "label": "Friendly viewing first",
        "strategy": "Ask about viewing availability first, then coordinate contact details naturally.",
        "phone_fetching_type": "viewing_first",
        "escalation_behavior": "warmly nudge toward a fixed viewing time before exchanging phone numbers",
        "conversation_goal": "book a viewing and build enough trust for contact exchange",
    },
    "direct_number_request": {
        "label": "Direct professional number request",
        "strategy": "Stay concise and efficient, and ask for WhatsApp or phone coordination early when it helps.",
        "phone_fetching_type": "immediate",
        "escalation_behavior": "move quickly to phone coordination if the landlord is responsive",
        "conversation_goal": "secure a direct contact route quickly",
    },
    "video_call_request": {
        "label": "Relocation video call request",
        "strategy": "Mention distance or relocation context and ask for a WhatsApp video call when useful.",
        "phone_fetching_type": "immediate",
        "escalation_behavior": "use distance as a natural reason for a video call before travelling",
        "conversation_goal": "arrange a video call or viewing without sounding pushy",
    },
    "warm_casual": {
        "label": "Warm casual couple",
        "strategy": "Use friendly, human language and build trust before asking for contact details.",
        "phone_fetching_type": "delayed",
        "escalation_behavior": "soft follow-ups and trust-building before requesting a number",
        "conversation_goal": "keep the landlord comfortable while moving toward a viewing",
    },
    "professional_polite": {
        "label": "Professional polite",
        "strategy": "Keep replies measured, practical, and polite with minimal extra detail.",
        "phone_fetching_type": "adaptive",
        "escalation_behavior": "adapt to the landlord's pace while keeping the thread practical",
        "conversation_goal": "arrange a viewing and collect contact details when appropriate",
    },
    "busy_professional": {
        "label": "Busy professional",
        "strategy": "Mention work schedules lightly and prefer phone coordination once timing is being discussed.",
        "phone_fetching_type": "adaptive",
        "escalation_behavior": "ask for a direct contact route when schedules become specific",
        "conversation_goal": "coordinate efficiently around work availability",
    },
    "whatsapp_coordination": {
        "label": "WhatsApp coordination",
        "strategy": "Use WhatsApp as the preferred coordination channel in a casual but not forceful way.",
        "phone_fetching_type": "whatsapp_first",
        "escalation_behavior": "share or request WhatsApp details early when it feels natural",
        "conversation_goal": "move the conversation to WhatsApp for viewing coordination",
    },
    "landlord_number_boundary": {
        "label": "Landlord number with boundaries",
        "strategy": "Avoid sharing the tenant number, keep OpenRent as fallback, and ask for the landlord number only when viewing logistics make it reasonable.",
        "phone_fetching_type": "landlord_requests_only",
        "escalation_behavior": "respect refusals, show mild discomfort about sharing tenant contact details, and wait before re-asking",
        "conversation_goal": "get the landlord's number without making contact capture feel like the main goal",
    },
}


PERSONA_TEMPLATES = {
    "young_professional_couple": {
        "persona_type": "young_professional_couple",
        "display_name": "Young professional couple",
        "household_description": "young professional couple",
        "message_tone": "friendly, direct, brief",
        "home_city": "Manchester",
        "phone_fetching_type": "delayed",
        "message_strategy": "friendly, viewing-led, trust-building",
        "escalation_behavior": "ask for phone details after a viewing time is mostly agreed",
        "conversation_goal": "arrange a viewing and exchange contact details naturally",
        "screening_posture": "both applicants are working professionals",
        "phone_boundary": "prefer not to share the tenant mobile before meeting; ask for the landlord number only with a viewing/logistics reason",
        "conversation_styles": [
            "friendly_viewing",
            "warm_casual",
            "professional_polite",
            "whatsapp_coordination",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["James", "Daniel", "Oliver", "Sam"],
            "partner": ["Sophie", "Hannah", "Amelia", "Leah"],
        },
        "jobs": {
            "primary": ["Product Manager", "Business Analyst", "Software Engineer"],
            "partner": ["Marketing Manager", "Project Coordinator", "UX Designer"],
        },
    },
    "quiet_it_worker": {
        "persona_type": "quiet_it_worker",
        "display_name": "Quiet IT worker",
        "household_description": "single IT professional",
        "message_tone": "minimal, matter-of-fact, calm",
        "home_city": "Derby",
        "phone_fetching_type": "landlord_requests_only",
        "message_strategy": "quiet, practical, viewing-first",
        "escalation_behavior": "share phone only when the landlord asks or a viewing is fixed",
        "conversation_goal": "arrange a practical viewing without unnecessary chatter",
        "screening_posture": "single applicant, working in IT",
        "phone_boundary": "keep contact exchange cautious and practical; OpenRent messaging is fine if the landlord prefers it",
        "conversation_styles": [
            "professional_polite",
            "viewing_first",
            "busy_professional",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Tom", "Ben", "Luke", "Ryan"],
            "partner": [],
        },
        "jobs": {
            "primary": ["Systems Administrator", "Cloud Engineer", "IT Support Lead"],
            "partner": [],
        },
    },
    "nhs_medical_worker": {
        "persona_type": "nhs_medical_worker",
        "display_name": "NHS or medical worker",
        "household_description": "working professional with a healthcare role",
        "message_tone": "warm, polite, practical, may mention shifts naturally",
        "home_city": "Birmingham",
        "phone_fetching_type": "adaptive",
        "message_strategy": "warm, practical, schedule-aware",
        "escalation_behavior": "use shift patterns as a natural reason for direct coordination",
        "conversation_goal": "find a viewing time that works around shifts",
        "screening_posture": "healthcare professional household; mention shifts only if relevant",
        "phone_boundary": "use viewing schedules or shifts as the reason for landlord contact details, not a cold ask",
        "conversation_styles": [
            "friendly_viewing",
            "busy_professional",
            "professional_polite",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Aisha", "Maya", "Priya", "Sarah"],
            "partner": ["Adam", "Omar", "Daniel", "Imran"],
        },
        "jobs": {
            "primary": ["NHS Nurse", "Radiographer", "Clinical Pharmacist"],
            "partner": ["Civil Engineer", "Operations Manager", "Data Analyst"],
        },
    },
    "academic_researcher": {
        "persona_type": "academic_researcher",
        "display_name": "Academic or researcher",
        "household_description": "single academic professional",
        "message_tone": "measured, polite, slightly formal",
        "home_city": "Nottingham",
        "phone_fetching_type": "viewing_first",
        "message_strategy": "measured, viewing-led, polite",
        "escalation_behavior": "only move to phone once the landlord is engaged",
        "conversation_goal": "confirm viewing details with a calm professional tone",
        "screening_posture": "single academic professional",
        "phone_boundary": "avoid pushing for contact details; keep the request tied to a viewing or video viewing",
        "conversation_styles": [
            "professional_polite",
            "friendly_viewing",
            "relocation_approach",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Emily", "Laura", "Jonathan", "Nathan"],
            "partner": [],
        },
        "jobs": {
            "primary": ["University Lecturer", "Research Fellow", "Policy Researcher"],
            "partner": [],
        },
    },
    "engineer_consultant_couple": {
        "persona_type": "engineer_consultant_couple",
        "display_name": "Engineer or consultant couple",
        "household_description": "professional couple",
        "message_tone": "efficient, practical, concise",
        "home_city": "Leicester",
        "phone_fetching_type": "immediate",
        "message_strategy": "concise, professional, direct coordination",
        "escalation_behavior": "ask for WhatsApp or phone coordination early if the landlord is responsive",
        "conversation_goal": "move quickly from interest to confirmed viewing logistics",
        "screening_posture": "professional couple; answer screening directly and briefly",
        "phone_boundary": "avoid sharing the tenant mobile in landlord-number-capture mode; use travel or timing as the reason to ask",
        "conversation_styles": [
            "direct_number_request",
            "professional_polite",
            "video_call_request",
            "whatsapp_coordination",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Michael", "Ethan", "Charlotte", "Rebecca"],
            "partner": ["Emma", "Lucy", "Alex", "Chris"],
        },
        "jobs": {
            "primary": ["Mechanical Engineer", "Management Consultant", "Solutions Architect"],
            "partner": ["Financial Consultant", "Account Manager", "Civil Engineer"],
        },
    },
    "single_income_couple": {
        "persona_type": "single_income_couple",
        "display_name": "Single-income couple",
        "household_description": "couple with one working applicant and one partner at home",
        "message_tone": "calm, practical, slightly cautious",
        "home_city": "Manchester",
        "phone_fetching_type": "landlord_requests_only",
        "message_strategy": "screening-first, careful with contact details, viewing-led",
        "escalation_behavior": "answer affordability and household questions clearly before asking for viewing logistics",
        "conversation_goal": "arrange a viewing while keeping contact sharing cautious",
        "screening_posture": "one applicant is working full-time; partner is currently at home",
        "phone_boundary": "do not share the tenant mobile early; if pressed, mention past bad experiences and offer to keep OpenRent as fallback",
        "conversation_styles": [
            "friendly_viewing",
            "professional_polite",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Mary", "Aisha", "Priya", "Hannah"],
            "partner": ["James", "Omar", "Daniel", "Sam"],
        },
        "jobs": {
            "primary": ["IT Support Lead", "Product Manager", "Accountant"],
            "partner": ["currently at home", "full-time parent", "homemaker"],
        },
    },
}


STYLE_ALIASES = {
    "viewing_first": "friendly_viewing",
    "friendly_couple": "warm_casual",
    "direct_professional": "direct_number_request",
    "relocation_approach": "video_call_request",
    "busy_professional": "busy_professional",
    "whatsapp_first": "whatsapp_coordination",
}


def normalize_conversation_style(style):
    style = (style or "").strip()
    if style in CONVERSATION_STYLES:
        return style
    return STYLE_ALIASES.get(style, "friendly_viewing")


def get_conversation_style(style):
    return CONVERSATION_STYLES[normalize_conversation_style(style)]


def get_persona_template(persona_type):
    return PERSONA_TEMPLATES.get(persona_type)


def materialize_persona(template, seed=None):
    primary_name = random.choice(template["names"]["primary"])
    partner_names = template["names"]["partner"]
    partner_name = random.choice(partner_names) if partner_names else None
    primary_job = random.choice(template["jobs"]["primary"])
    partner_jobs = template["jobs"]["partner"]
    partner_job = random.choice(partner_jobs) if partner_jobs else None

    available_styles = template.get("conversation_styles") or ["friendly_viewing"]
    selected_style = normalize_conversation_style(random.choice(available_styles))
    style_config = get_conversation_style(selected_style)

    return {
        "persona_type": template["persona_type"],
        "persona_name": primary_name,
        "persona_partner_name": partner_name,
        "persona_job": primary_job,
        "persona_partner_job": partner_job,
        "household_description": template["household_description"],
        "message_tone": template["message_tone"],
        "home_city": template["home_city"],
        "display_name": template["display_name"],
        "mobile_number": template.get("mobile_number"),
        "phone_fetching_type": template.get("phone_fetching_type") or style_config["phone_fetching_type"],
        "message_strategy": template.get("message_strategy") or style_config["strategy"],
        "escalation_behavior": template.get("escalation_behavior") or style_config["escalation_behavior"],
        "conversation_goal": template.get("conversation_goal") or style_config["conversation_goal"],
        "conversation_style": selected_style,
        "conversation_styles": available_styles,
        "screening_posture": template.get("screening_posture"),
        "phone_boundary": template.get("phone_boundary"),
    }


def select_persona():
    return materialize_persona(
        random.choice(list(PERSONA_TEMPLATES.values()))
    )


def persona_summary(persona):
    if not persona:
        return "Unknown working professional tenant."

    parts = [
        f"{persona.get('persona_name') or 'Tenant'}",
        persona.get("persona_job"),
    ]
    partner = persona.get("persona_partner_name")
    partner_job = persona.get("persona_partner_job")
    if partner:
        parts.append(f"partner {partner}" + (f" ({partner_job})" if partner_job else ""))
    household = persona.get("household_description")
    home_city = persona.get("home_city")
    suffix = []
    if household:
        suffix.append(household)
    if home_city:
        suffix.append(f"based in {home_city}")
    return "; ".join([", ".join(filter(None, parts)), ", ".join(suffix)])


def landlord_asked_for_phone(text):
    return bool(
        re.search(
            r"\b(phone|mobile|number|contact|whatsapp|whats\s*app|call|text)\b",
            str(text or ""),
            re.I,
        )
        and re.search(
            r"\b(send|share|give|provide|what'?s|your|contact|whatsapp|number)\b",
            str(text or ""),
            re.I,
        )
    )


def tenant_shared_phone(messages, mobile_number):
    if not mobile_number:
        return False
    compact_number = re.sub(r"\D", "", mobile_number)
    local_number = "0" + compact_number[2:] if compact_number.startswith("44") else compact_number
    for message in messages or []:
        sender = str(message.get("sender") or message.get("direction") or "").lower()
        if sender not in {"user", "tenant", "outbound", "ai"}:
            continue
        content_digits = re.sub(r"\D", "", str(message.get("message") or message.get("content") or ""))
        if compact_number and compact_number in content_digits:
            return True
        if local_number and local_number in content_digits:
            return True
    return False


def should_share_phone_now(
    persona,
    *,
    landlord_asked=False,
    phone_shared=False,
    outbound_count=0,
    stage=None,
    drive_distance_high=False,
):
    if phone_shared:
        return False
    if not (persona or {}).get("mobile_number"):
        return False
    if landlord_asked:
        return True

    phone_type = (persona or {}).get("phone_fetching_type") or "delayed"
    style = normalize_conversation_style((persona or {}).get("conversation_style"))

    if phone_type in {"immediate", "whatsapp_first"} or style in {
        "direct_number_request",
        "video_call_request",
        "whatsapp_coordination",
    }:
        return outbound_count <= 1

    if phone_type == "delayed":
        return outbound_count >= 2 and stage == "VIEWING_BOOKED"

    if phone_type == "viewing_first":
        return stage == "VIEWING_BOOKED"

    if phone_type == "adaptive":
        return stage == "VIEWING_BOOKED" or (drive_distance_high and outbound_count >= 1)

    return False


def generate_phone_share_reply(persona, landlord_attitude="responsive"):
    mobile = (persona or {}).get("mobile_number")
    # mobile = "+447743722832"
    if not mobile:
        return None

    attitude = landlord_attitude if landlord_attitude in LANDLORD_ATTITUDES else "responsive"
    options = {
        "cold": [
            f"Sure, my number is {mobile}.",
            f"Yes, it's {mobile}.",
        ],
        "aggressive": [
            f"Of course, my number is {mobile}.",
            f"Sure, you can reach me on {mobile}.",
        ],
        "suspicious": [
            f"Of course, my number is {mobile}. Happy to coordinate the viewing there.",
            f"Sure, it's {mobile}. I'm happy to use that for viewing coordination.",
        ],
        "friendly": [
            f"Sure, my number is {mobile}. WhatsApp is fine too.",
            f"Of course, it's {mobile}. Feel free to message me on WhatsApp.",
        ],
        "helpful": [
            f"Thanks, my number is {mobile}. WhatsApp works well for me.",
            f"Sure, it's {mobile}. Happy to coordinate there.",
        ],
        "slow_reply": [
            f"Sure, my number is {mobile}.",
            f"Yes, it's {mobile}. WhatsApp is fine.",
        ],
        "responsive": [
            f"Sure, my number is {mobile}. WhatsApp is fine too.",
            f"Of course, it's {mobile}.",
        ],
    }
    return random.choice(options[attitude])
