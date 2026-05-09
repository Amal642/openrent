from openai import OpenAI
from app.config import settings

import re


client = OpenAI(
    api_key=settings.OPENAI_API_KEY
)


def regex_extract_phone(messages):

    combined = "\n".join(messages)

    patterns = [

        r"(\+44\d{10,12})",

        r"(07\d{9})",

        r"(447\d{9})"
    ]

    for pattern in patterns:

        match = re.search(pattern, combined)

        if match:
            return match.group(1)

    return None


def ai_extract_phone(messages):

    text = "\n".join(messages)

    prompt = f"""
You are extracting landlord phone numbers.

Conversation:
{text}

Rules:
- Only extract landlord phone number
- Ignore tenant/user numbers
- Reconstruct fragmented numbers
- Return ONLY the phone number
- If no number exists return: NONE
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",

        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],

        temperature=0
    )

    result = (
        response.choices[0]
        .message.content
        .strip()
    )

    if result.upper() == "NONE":
        return None

    return result