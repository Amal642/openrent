import random


PERSONA_TEMPLATES = {
    "young_professional_couple": {
        "persona_type": "young_professional_couple",
        "display_name": "Young professional couple",
        "household_description": "young professional couple",
        "message_tone": "friendly, direct, brief",
        "home_city": "Manchester",
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
        "names": {
            "primary": ["Michael", "Ethan", "Charlotte", "Rebecca"],
            "partner": ["Emma", "Lucy", "Alex", "Chris"],
        },
        "jobs": {
            "primary": ["Mechanical Engineer", "Management Consultant", "Solutions Architect"],
            "partner": ["Financial Consultant", "Account Manager", "Civil Engineer"],
        },
    },
}


def get_persona_template(persona_type):
    return PERSONA_TEMPLATES.get(persona_type)


def materialize_persona(template):
    primary_name = random.choice(template["names"]["primary"])
    partner_names = template["names"]["partner"]
    partner_name = random.choice(partner_names) if partner_names else None
    primary_job = random.choice(template["jobs"]["primary"])
    partner_jobs = template["jobs"]["partner"]
    partner_job = random.choice(partner_jobs) if partner_jobs else None

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
    }


def select_persona():
    return materialize_persona(
        random.choice(list(PERSONA_TEMPLATES.values()))
    )
