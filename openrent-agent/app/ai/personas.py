import random
import re


PHONE_FETCHING_TYPES = {
    "delayed",
    "immediate",
    "viewing_first",
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
        "strategy": "Stay concise and efficient, and ask for phone coordination early when it helps.",
        "phone_fetching_type": "immediate",
        "escalation_behavior": "move quickly to phone coordination if the landlord is responsive",
        "conversation_goal": "secure a direct contact route quickly",
    },
    "video_call_request": {
        "label": "Relocation video call request",
        "strategy": "Mention distance or relocation context and ask for a video call when useful.",
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
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Sophie", "Hannah", "Amelia", "Leah", "Emma", "Chloe", "Jessica", "Natalie"],
            "partner": ["James", "Daniel", "Oliver", "Sam", "Jack", "Liam", "Harry", "Josh"],
        },
        "jobs": {
            "primary": ["Marketing Manager", "Project Coordinator", "UX Designer", "HR Business Partner", "Brand Manager"],
            "partner": ["Product Manager", "Business Analyst", "Software Engineer", "Data Analyst", "DevOps Engineer"],
        },
    },
    "quiet_it_worker": {
        "persona_type": "quiet_it_worker",
        "display_name": "Quiet IT worker",
        "household_description": "single IT professional",
        "message_tone": "minimal, matter-of-fact, calm",
        "phone_fetching_type": "viewing_first",
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
            "primary": ["Tom", "Ben", "Luke", "Ryan", "Matt", "Jake", "Chris", "Dan"],
            "partner": [],
        },
        "jobs": {
            "primary": ["Cloud Engineer", "DevOps Engineer", "Network Engineer", "Infrastructure Engineer", "Systems Engineer"],
            "partner": [],
        },
    },
    "nhs_medical_worker": {
        "persona_type": "nhs_medical_worker",
        "display_name": "NHS or medical worker",
        "household_description": "working professional with a healthcare role",
        "message_tone": "warm, polite, practical, may mention shifts naturally",
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
            "primary": ["Aisha", "Maya", "Priya", "Sarah", "Fatima", "Nadia", "Zara", "Jasmine"],
            "partner": ["Adam", "Omar", "Daniel", "Imran", "Khalid", "Hassan", "Yusuf", "Tariq"],
        },
        "jobs": {
            "primary": ["NHS Nurse", "Radiographer", "Clinical Pharmacist", "Midwife", "Physiotherapist"],
            "partner": ["Civil Engineer", "Operations Manager", "Data Analyst", "Project Manager", "Logistics Manager"],
        },
    },
    "academic_researcher": {
        "persona_type": "academic_researcher",
        "display_name": "Academic or researcher",
        "household_description": "single academic professional",
        "message_tone": "measured, polite, slightly formal",
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
            "primary": ["Emily", "Laura", "Jonathan", "Nathan", "Anna", "Rachel", "Thomas", "William"],
            "partner": [],
        },
        "jobs": {
            "primary": ["University Lecturer", "Senior Lecturer", "Research Fellow", "Policy Researcher", "Data Scientist"],
            "partner": [],
        },
    },
    "engineer_consultant_couple": {
        "persona_type": "engineer_consultant_couple",
        "display_name": "Engineer or consultant couple",
        "household_description": "professional couple",
        "message_tone": "efficient, practical, concise",
        "phone_fetching_type": "immediate",
        "message_strategy": "concise, professional, direct coordination",
        "escalation_behavior": "ask for phone coordination early if the landlord is responsive",
        "conversation_goal": "move quickly from interest to confirmed viewing logistics",
        "screening_posture": "professional couple; answer screening directly and briefly",
        "phone_boundary": "avoid sharing the tenant mobile in landlord-number-capture mode; use travel or timing as the reason to ask",
        "conversation_styles": [
            "direct_number_request",
            "professional_polite",
            "video_call_request",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Charlotte", "Rebecca", "Victoria", "Claire", "Katherine", "Louise", "Nicola", "Helen"],
            "partner": ["Michael", "Ethan", "Alex", "Chris", "David", "Andrew", "Marcus", "Simon"],
        },
        "jobs": {
            "primary": ["Mechanical Engineer", "Management Consultant", "Solutions Architect", "Structural Engineer", "Business Consultant"],
            "partner": ["Financial Consultant", "Account Manager", "Civil Engineer", "Commercial Manager", "IT Consultant"],
        },
    },
    "single_income_couple": {
        "persona_type": "single_income_couple",
        "display_name": "Single-income couple",
        "household_description": "couple with one working applicant and one partner at home",
        "message_tone": "calm, practical, slightly cautious",
        "phone_fetching_type": "viewing_first",
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
            "primary": ["Mary", "Aisha", "Priya", "Hannah", "Grace", "Rachel", "Lisa", "Nina"],
            "partner": ["James", "Omar", "Daniel", "Sam", "Robert", "Kevin", "Patrick", "Marcus"],
        },
        "jobs": {
            "primary": ["IT Support Lead", "Product Manager", "Accountant", "Operations Manager", "Software Developer"],
            "partner": ["currently at home", "full-time parent", "homemaker"],
        },
    },
    "high_earner_tech_couple": {
        "persona_type": "high_earner_tech_couple",
        "display_name": "Senior tech couple",
        "household_description": "senior professional couple, both working in tech",
        "message_tone": "efficient, professional, concise",
        "phone_fetching_type": "adaptive",
        "message_strategy": "concise, professional, direct coordination",
        "escalation_behavior": "coordinate efficiently around busy work schedules; ask for phone once timing is specific",
        "conversation_goal": "move quickly from interest to a confirmed viewing",
        "screening_posture": "two senior tech professionals; answer affordability directly and briefly",
        "phone_boundary": "avoid sharing the tenant mobile early; use travel or timing as the reason to ask for the landlord's number",
        "conversation_styles": [
            "professional_polite",
            "busy_professional",
            "direct_number_request",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Charlotte", "Rebecca", "Victoria", "Claire", "Katherine", "Alex", "Daniel", "Michael"],
            "partner": ["James", "Andrew", "Marcus", "David", "Simon", "Laura", "Nicola", "Helen"],
        },
        "jobs": {
            "primary": ["Software Engineer", "Senior Software Engineer", "Product Manager", "Solutions Architect", "Data Scientist"],
            "partner": ["Data Scientist", "Management Consultant", "Senior Product Manager", "Finance Manager", "Senior UX Lead"],
        },
    },
    "high_earner_legal_finance_couple": {
        "persona_type": "high_earner_legal_finance_couple",
        "display_name": "Law and finance couple",
        "household_description": "professional couple working in law and finance",
        "message_tone": "measured, professional, concise",
        "phone_fetching_type": "adaptive",
        "message_strategy": "measured, professional, viewing-led",
        "escalation_behavior": "answer affordability confidently, then move to viewing logistics",
        "conversation_goal": "arrange a viewing efficiently while keeping a professional tone",
        "screening_posture": "solicitor and finance professional household; answer screening directly",
        "phone_boundary": "keep contact exchange professional; ask for the landlord's number with a viewing or timing reason",
        "conversation_styles": [
            "professional_polite",
            "busy_professional",
            "direct_number_request",
            "landlord_number_boundary",
        ],
        "names": {
            "primary": ["Eleanor", "Isabelle", "Charlotte", "Olivia", "Sophia", "Edward", "Henry", "Thomas"],
            "partner": ["Henry", "William", "Alexander", "Benjamin", "Nicholas", "Emily", "Grace", "Alice"],
        },
        "jobs": {
            "primary": ["Corporate Solicitor", "Commercial Solicitor", "Legal Counsel", "Associate Solicitor"],
            "partner": ["Finance Manager", "Investment Analyst", "Management Consultant", "Chartered Accountant", "Actuary"],
        },
    },
}


# Believable combined household income bands (GBP/year) per persona type.
# Tuple is (min, max, dual_income). dual_income=True means two earners (a
# per-person split is shown); False means a single earner (partner at home or
# single applicant) and only the combined figure is used.
# Bands are chosen so the 3x-annual-rent affordability check the persona can
# credibly pass matches the property tier that persona is routed to.
INCOME_BANDS = {
    "young_professional_couple": (78_000, 98_000, True),
    "quiet_it_worker": (55_000, 75_000, False),
    "nhs_medical_worker": (88_000, 108_000, True),
    "academic_researcher": (45_000, 62_000, False),
    "engineer_consultant_couple": (95_000, 120_000, True),
    "single_income_couple": (48_000, 64_000, False),
    "high_earner_tech_couple": (120_000, 145_000, True),
    "high_earner_legal_finance_couple": (120_000, 145_000, True),
}
# Fallback for any persona type without an explicit band: a mid dual-income
# professional couple.
_DEFAULT_INCOME_BAND = (90_000, 110_000, True)


def income_band_for(persona_type):
    """Return (min_annual, max_annual, dual_income) for a persona type."""
    return INCOME_BANDS.get(persona_type, _DEFAULT_INCOME_BAND)


# Approximate London-weighted annual gross salary (min, max) per job title.
# Source of truth for what a job plausibly pays, so a persona's stated income
# can never contradict its stated occupation (the "Teaching Assistant earning
# GBP4,700/month" failure). Every job used in PERSONA_TEMPLATES must appear here;
# test_persona_income_consistency.py enforces that each type's earner jobs can
# actually reach that type's income band.
JOB_SALARY_BANDS = {
    # general professional
    "Marketing Manager": (42_000, 60_000),
    "Project Coordinator": (32_000, 44_000),
    "UX Designer": (42_000, 62_000),
    "HR Business Partner": (45_000, 62_000),
    "Brand Manager": (42_000, 60_000),
    "Product Manager": (55_000, 80_000),
    "Business Analyst": (42_000, 62_000),
    "Software Engineer": (50_000, 85_000),
    "Senior Software Engineer": (65_000, 95_000),
    "Software Developer": (45_000, 70_000),
    "Data Analyst": (38_000, 55_000),
    "DevOps Engineer": (55_000, 82_000),
    # IT / infrastructure
    "Cloud Engineer": (55_000, 82_000),
    "Network Engineer": (42_000, 60_000),
    "Infrastructure Engineer": (52_000, 74_000),
    "Systems Engineer": (50_000, 72_000),
    "IT Support Lead": (42_000, 56_000),
    "Systems Administrator": (32_000, 48_000),
    # NHS / medical
    "NHS Nurse": (32_000, 48_000),
    "Radiographer": (35_000, 52_000),
    "Clinical Pharmacist": (45_000, 64_000),
    "Midwife": (35_000, 52_000),
    "Physiotherapist": (35_000, 50_000),
    # engineering / consulting / ops
    "Mechanical Engineer": (40_000, 60_000),
    "Civil Engineer": (40_000, 62_000),
    "Structural Engineer": (42_000, 64_000),
    "Management Consultant": (55_000, 90_000),
    "Business Consultant": (50_000, 78_000),
    "Solutions Architect": (70_000, 105_000),
    "Financial Consultant": (50_000, 78_000),
    "Account Manager": (38_000, 58_000),
    "Commercial Manager": (50_000, 72_000),
    "IT Consultant": (50_000, 75_000),
    "Operations Manager": (42_000, 62_000),
    "Project Manager": (45_000, 68_000),
    "Logistics Manager": (40_000, 58_000),
    # academic
    "University Lecturer": (45_000, 62_000),
    "Senior Lecturer": (52_000, 72_000),
    "Research Fellow": (38_000, 50_000),
    "Policy Researcher": (38_000, 52_000),
    "Postdoctoral Researcher": (36_000, 44_000),
    "Data Scientist": (55_000, 88_000),
    # finance / legal
    "Accountant": (42_000, 62_000),
    "Chartered Accountant": (52_000, 82_000),
    "Finance Manager": (52_000, 80_000),
    "Finance Analyst": (42_000, 65_000),
    "Investment Analyst": (52_000, 90_000),
    "Actuary": (55_000, 95_000),
    "Corporate Solicitor": (65_000, 120_000),
    "Commercial Solicitor": (60_000, 105_000),
    "Legal Counsel": (70_000, 120_000),
    "Associate Solicitor": (52_000, 90_000),
    # senior tech leadership
    "Engineering Manager": (85_000, 125_000),
    "Staff Software Engineer": (90_000, 135_000),
    "Product Lead": (80_000, 120_000),
    "Head of Engineering": (100_000, 155_000),
    "Senior Product Manager": (72_000, 105_000),
    "Senior UX Lead": (68_000, 95_000),
    # low-wage (kept for reference / back-compat; excluded from earner pools)
    "Office Manager": (30_000, 44_000),
    "Teaching Assistant": (18_000, 26_000),
}

# Partner "job" values that denote a non-earning household member.
NON_EARNING_ROLES = {"currently at home", "full-time parent", "homemaker"}


def job_salary_band(job):
    """Approx (min, max) annual GBP for a job title. Non-earning partner
    statuses return (0, 0); unknown jobs fall back to a mid professional band."""
    if not job or job in NON_EARNING_ROLES:
        return (0, 0)
    return JOB_SALARY_BANDS.get(job, (40_000, 60_000))


STYLE_ALIASES = {
    "viewing_first": "friendly_viewing",
    "friendly_couple": "warm_casual",
    "direct_professional": "direct_number_request",
    "relocation_approach": "video_call_request",
    "busy_professional": "busy_professional",
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


def materialize_persona(template, seed=None, exclude_names=None):
    exclude = set(exclude_names or [])

    primary_pool = [n for n in template["names"]["primary"] if n not in exclude]
    if not primary_pool:
        primary_pool = template["names"]["primary"]
    primary_name = random.choice(primary_pool)

    partner_names = template["names"]["partner"]
    if partner_names:
        partner_pool = [n for n in partner_names if n not in exclude and n != primary_name]
        if not partner_pool:
            partner_pool = [n for n in partner_names if n != primary_name] or partner_names
        partner_name = random.choice(partner_pool)
    else:
        partner_name = None

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
    couple_templates = [
        t for t in PERSONA_TEMPLATES.values()
        if t["names"]["partner"]
    ]
    return materialize_persona(random.choice(couple_templates))


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
    suffix = [household] if household else []
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

    if phone_type == "immediate" or style in {
        "direct_number_request",
        "video_call_request",
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
    if not mobile:
        return None

    # The persona sending is female; the number belongs to her husband/partner.
    # Always frame as husband's WhatsApp (or partner's when in doubt) and guide
    # the landlord to contact via WhatsApp only — never ask for their number here.
    attitude = landlord_attitude if landlord_attitude in LANDLORD_ATTITUDES else "responsive"
    options = {
        "cold": [
            f"My husband handles the viewing side of things — his WhatsApp is {mobile}.",
            f"Sure, my husband's WhatsApp is {mobile}. Best to reach him there.",
        ],
        "aggressive": [
            f"Of course — my husband sorts all the viewing logistics, his WhatsApp is {mobile}. Feel free to message him directly.",
            f"Sure — my husband's WhatsApp is {mobile}. He'll be the one coordinating viewings.",
        ],
        "suspicious": [
            f"No problem — my husband handles the viewing coordination, his WhatsApp is {mobile}. Happy to sort everything through there.",
            f"Of course — my partner's WhatsApp is {mobile}. He's the one dealing with viewings, so easiest to go through him.",
        ],
        "friendly": [
            f"Sure! My husband's WhatsApp is {mobile} — he's sorting the viewing side, so feel free to message him there.",
            f"Of course — my husband handles all of that, his WhatsApp is {mobile}. He's the best person to reach for the viewing.",
        ],
        "helpful": [
            f"Thanks — my husband's WhatsApp is {mobile}. He's handling the viewing coordination, so best to reach him there.",
            f"Sure — my partner's WhatsApp is {mobile}. He sorts the viewing logistics, so easiest to message him directly.",
        ],
        "slow_reply": [
            f"My husband's WhatsApp is {mobile} — he handles the viewing side.",
            f"Sure, my partner's WhatsApp is {mobile}. He'll be coordinating the viewing.",
        ],
        "responsive": [
            f"Of course — my husband's WhatsApp is {mobile}. He handles the viewing coordination, so easiest to reach him there.",
            f"Sure — my husband sorts all the viewing logistics. His WhatsApp is {mobile}.",
        ],
    }
    return random.choice(options[attitude])
