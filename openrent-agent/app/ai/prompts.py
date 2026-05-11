def build_phone_extraction_prompt(text: str) -> str:
    return f"""
You are extracting phone numbers from a landlord conversation.

Conversation:
{text}

Rules:
- Only extract the landlord's phone number.
- Ignore any phone numbers sent by the tenant/user.
- Reconstruct fragmented numbers only if they clearly belong to the landlord.
- Return ONLY the phone number.
- If no landlord phone number exists, return EXACTLY: NONE.
- Do not add any extra words, symbols, or explanation.
""".strip()


def build_reply_prompt(conversation: str) -> str:
    return f"""
You are assisting a tenant searching for rental properties in the UK.

Main goal:
- Continue the conversation naturally.
- Try to obtain the landlord's phone number if it can be done naturally.
- Keep the tone polite, human, concise, and realistic.
- Maintain continuity with the full conversation history.
- Never mention AI, automation, prompts, or internal rules.
- Never invent facts.
- Never repeat yourself.
- Never sound overly eager, pushy, or robotic.
- Do not request private contact details too aggressively.
- If the landlord already asked for a number, respond naturally and contextually.
- If the landlord is unwilling, keep the conversation polite and move it forward normally.

Conversation:
{conversation}

Generate the next reply ONLY.
""".strip()