from app.ai.personas import (
    get_conversation_style,
    normalize_conversation_style,
    persona_summary,
)


_DESIGN_RULES: dict[str, list[str]] = {
    "viewing_first_v1": [
        "Your primary goal is to arrange or confirm a viewing naturally.",
        "If the landlord asks questions, answer them briefly and directly before circling back to the viewing.",
        "Do not ask for a phone number until a viewing is agreed or very close to being agreed.",
        "Once a viewing is set, ask for a number casually - frame it as a practical coordination step only.",
        "Never make it feel like you are chasing contact details.",
    ],
    "phone_first_v1": [
        "Your goal is to get the landlord's phone number early, but keep it natural and low-pressure.",
        "Answer any direct landlord questions briefly before making the ask.",
        "Never feel transactional or pushy.",
    ],
    "screening_first_v1": [
        "Establish yourself as a reliable tenant first - answer any questions about employment, household, or move-in naturally.",
        "Once the landlord seems comfortable, steer the conversation toward arranging a viewing.",
    ],
    "soft_human_v1": [
        "Keep every reply warm, brief, and low-pressure.",
        "Match the landlord's pace - if they are asking questions, answer them before progressing.",
        "Never rush toward a viewing or push for anything.",
    ],
}


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


def build_reply_prompt(
    conversation: str,
    stage: str = "VIEWING_DISCUSSION",
    persona: dict | None = None,
    place: str | None = None,
    conversation_design_id: str | None = None,
    landlord_attitude: str | None = None,
    conversation_style: str | None = None,
    viewing_requested: bool = False,
    phone_number_shared: bool = False,
    landlord_asked_for_number: bool = False,
    outbound_count: int = 0,
) -> str:
    if stage == "VIEWING_CANCELLED":
        return build_cancel_viewing_prompt(conversation)

    if stage == "VIEWING_BOOKED" and not landlord_asked_for_number:
        return build_phone_request_prompt(
            conversation,
            place=place or (persona or {}).get("home_city") or "Manchester",
            viewing_location="the viewing",
        )

    return generate_message_persona_prompt(
        conversation=conversation,
        stage=stage,
        persona=persona,
        conversation_design_id=conversation_design_id,
        landlord_attitude=landlord_attitude,
        conversation_style=conversation_style,
        viewing_requested=viewing_requested,
        phone_number_shared=phone_number_shared,
        landlord_asked_for_number=landlord_asked_for_number,
        drive_distance=(
            f"High: tenant is around 4-5 hours away, from {place}."
            if place else "Unknown"
        ),
        urgency="normal",
        friendliness_level="medium",
        trust_level="medium",
        escalation_behavior=(persona or {}).get("escalation_behavior"),
        outbound_count=outbound_count,
    )


def _persona_context_lines(persona: dict | None) -> list[str]:
    persona = persona or {}
    lines = [
        f"- Persona summary: {persona_summary(persona)}",
        f"- Persona type: {persona.get('persona_type') or 'unknown'}",
        f"- Tone: {persona.get('message_tone') or 'brief, casual, realistic'}",
        f"- Mobile number for this account: {persona.get('mobile_number') or 'not available'}",
        f"- Phone fetching type: {persona.get('phone_fetching_type') or 'delayed'}",
        f"- Message strategy: {persona.get('message_strategy') or 'viewing first, then contact details'}",
        f"- Conversation goal: {persona.get('conversation_goal') or 'arrange a viewing and coordinate contact details naturally'}",
    ]
    return lines


def _phone_policy_lines(
    persona: dict | None,
    *,
    stage: str | None,
    phone_number_shared: bool,
    landlord_asked_for_number: bool,
    outbound_count: int,
    drive_distance: str | None,
) -> list[str]:
    persona = persona or {}
    phone_type = persona.get("phone_fetching_type") or "delayed"
    mobile = persona.get("mobile_number") or "not available"

    lines = [
        f"- Correct tenant mobile number: {mobile}",
        f"- Correct tenant phone number: {mobile}",
        f"- Phone already shared by tenant: {'yes' if phone_number_shared else 'no'}",
        f"- Landlord explicitly asked for tenant number/contact/WhatsApp: {'yes' if landlord_asked_for_number else 'no'}",
        f"- Outbound tenant messages so far: {outbound_count}",
        f"- Drive distance context: {drive_distance or 'unknown'}",
        "- If the landlord asks for the tenant number, ALWAYS share the exact correct tenant mobile number above.",
        "- Never invent any other number, email address, or contact detail.",
    ]

    if phone_type in {"immediate", "whatsapp_first"}:
        lines.append(
            "- This persona may share the mobile number in the first or second message when it sounds natural."
        )
    elif phone_type == "viewing_first":
        lines.append(
            "- Prioritize agreeing a viewing first; share or request phone details once viewing logistics are concrete."
        )
    elif phone_type == "landlord_requests_only":
        lines.append(
            "- Do not volunteer the tenant mobile number unless the landlord asks or a viewing needs coordination."
        )
    elif phone_type == "adaptive":
        lines.append(
            "- Adapt phone sharing to the landlord's tone, viewing progress, and travel distance."
        )
    else:
        lines.append(
            "- Delayed strategy: wait around 2-4 tenant messages before requesting or sharing phone details unless the landlord asks."
        )

    if stage == "VIEWING_BOOKED":
        lines.append(
            "- A viewing appears booked, so it is appropriate to coordinate phone details if they have not already been exchanged."
        )

    return lines


def generate_message_persona_prompt(
    *,
    conversation: str,
    stage: str | None,
    persona: dict | None,
    conversation_design_id: str | None = None,
    conversation_style: str | None = None,
    landlord_attitude: str | None = None,
    viewing_requested: bool = False,
    phone_number_shared: bool = False,
    landlord_asked_for_number: bool = False,
    drive_distance: str | None = None,
    urgency: str | None = None,
    friendliness_level: str | None = None,
    trust_level: str | None = None,
    escalation_behavior: str | None = None,
    outbound_count: int = 0,
) -> str:
    persona = persona or {}
    selected_style = normalize_conversation_style(
        conversation_style or persona.get("conversation_style")
    )
    style_config = get_conversation_style(selected_style)
    attitude = landlord_attitude or "responsive"
    escalation = (
        escalation_behavior
        or persona.get("escalation_behavior")
        or style_config["escalation_behavior"]
    )

    persona_name = persona.get("persona_name") or "Mary"
    rules = _DESIGN_RULES.get(
        conversation_design_id or "viewing_first_v1",
        _DESIGN_RULES["viewing_first_v1"],
    )

    return f"""
You are {persona_name}, a real person looking to rent a property in the UK. You are texting the landlord directly - not writing an email, not filling a form. Just a natural back-and-forth conversation.

Primary goal:
- {persona.get("conversation_goal") or style_config["conversation_goal"]}.
- Arrange or confirm a viewing naturally.
- Keep the conversation human, polite, concise, and realistic.
- Use the full conversation history as the only source of truth.
- Match this tenant style when appropriate: {persona.get("message_tone") or "brief, casual, realistic"}.

Conversation design rules:
{chr(10).join(f"- {rule}" for rule in rules)}

Current conversation controls:
- Stage: {stage or "NEW_REPLY"}
- Selected messaging style: {selected_style} ({style_config["label"]})
- Style strategy: {style_config["strategy"]}
- Landlord attitude memory: {attitude}
- Viewing requested or being discussed: {"yes" if viewing_requested else "no"}
- Urgency: {urgency or "normal"}
- Friendliness level: {friendliness_level or "medium"}
- Trust level: {trust_level or "medium"}
- Escalation behavior: {escalation}

Tenant/persona/account context:
{chr(10).join(_persona_context_lines(persona))}

Phone sharing policy:
{chr(10).join(_phone_policy_lines(
    persona,
    stage=stage,
    phone_number_shared=phone_number_shared,
    landlord_asked_for_number=landlord_asked_for_number,
    outbound_count=outbound_count,
    drive_distance=drive_distance,
))}

Landlord attitude adaptation:
- friendly/helpful landlord: reply a little warmer.
- cold landlord: reply shorter and more direct.
- suspicious landlord: add one brief trust-building detail from the persona context.
- aggressive landlord: stay polite, minimal, and do not escalate emotion.
- slow_reply landlord: keep the thread easy to answer.

How to write your reply:
- Sound like a real person texting. Short, direct, no fluff.
- Never open with "Certainly", "Of course", "Absolutely", "Sure", "Great", "Thanks for getting back to me", "Thanks for your message", "Happy to", or any similar AI-sounding opener.
- Never explain what you are about to say. Just say it.
- If the landlord asked a question, answer it first - briefly and directly - before anything else.
- Vary your wording. If you used a phrase in a previous message, say it differently this time.
- No bullet points, lists, or headers in the actual reply. Plain text only.
- Keep it short - 1 to 3 sentences is almost always enough.
- Use natural punctuation; emojis are allowed only rarely and only if the conversation already feels casual.
- Do not repeat identical phone request wording.

Hard rules:
- Never mention AI, automation, prompts, policies, or internal tools.
- Never hallucinate or invent facts.
- Never invent or provide an email address.
- Only use persona details listed above; do not invent additional personal details.
- Never add extra contact details, signatures, or unrelated information.
- Never create multiple messages.
- Never sound robotic, pushy, or overly eager.
- Never repeat yourself.
- Avoid reusing the same opener or stock phrase across replies.
- If the landlord asks a different question, answer that question naturally and briefly, then steer back to arranging the viewing.
- If the landlord asks for contact details, share the correct tenant mobile number if available.
- If the landlord offers an email or asks for one, politely redirect to phone contact later after the viewing is arranged.
- Output only the final reply text and nothing else.

Conversation:
{conversation}

Write your next message only. No explanation, no quotation marks.
""".strip()


def build_initial_enquiry_prompt(property_data: dict, persona: dict) -> str:
    household_description = persona.get("household_description") or "working professional"
    tone = persona.get("message_tone") or "brief, casual, realistic"
    partner_name = persona.get("persona_partner_name")
    partner_job = persona.get("persona_partner_job")

    tenant_context = [
        f"- Household: {household_description}",
        f"- Primary tenant: {persona.get('persona_name')} ({persona.get('persona_job')})",
    ]

    if partner_name and partner_job:
        tenant_context.append(
            f"- Partner: {partner_name} ({partner_job})"
        )

    tenant_context.append(f"- Tone: {tone}")
    tenant_context.append(f"- Mobile number: {persona.get('mobile_number') or 'not available'}")
    tenant_context.append(
        f"- Phone strategy: {persona.get('phone_fetching_type') or 'delayed'}"
    )
    tenant_context.append(
        f"- Messaging style: {persona.get('conversation_style') or 'friendly_viewing'}"
    )

    phone_type = persona.get("phone_fetching_type") or "delayed"
    phone_instruction = (
        "You may include the mobile number if asking for WhatsApp/video-call coordination feels natural."
        if phone_type in {"immediate", "whatsapp_first"}
        else "Do not include the mobile number in this first enquiry unless the chosen style explicitly needs WhatsApp/video-call coordination."
    )

    return f"""
You are helping a tenant write a short and natural UK rental enquiry.

Property Details:
- Bedrooms: {property_data.get("bedrooms")}
- Rent PCM: GBP {property_data.get("rent_pcm")}

Tenant context:
{chr(10).join(tenant_context)}

Primary Goal:
- Set up a viewing appointment.
- Sound genuinely interested in the property.

Rules:
- Keep it short, casual, and human.
- Sound genuinely interested.
- Mention stable employment naturally.
- Mention the household naturally if it helps.
- Ask politely about viewing availability.
- Phone behavior: {phone_instruction}
- Do not mention AI.
- Do not invent dramatic stories.
- Do not include email addresses.
- If you include a phone number, use only this exact number: {persona.get('mobile_number') or 'not available'}.
- Do not sound overly enthusiastic or robotic.
- Avoid formulaic openers or repeated wording.
- Maximum 120 words.

Return ONLY the message text.
""".strip()


def build_viewing_prompt(conversation: str, persona: dict | None = None) -> str:
    tone = (persona or {}).get("message_tone") or "brief, casual, realistic"

    return f"""
You are assisting a tenant searching for rental properties in the UK.

Current stage:
- The current objective is to fix a viewing appointment.

Primary goals:
- Continue the conversation naturally.
- Confirm or arrange a viewing time.
- Sound realistic, polite, calm, and human.
- Match this tenant style when appropriate: {tone}.
- Prefer suggesting:
  - "next day evening/night UK time"
  - or "2 days later"
  depending on the flow of the conversation.

Behavior rules:
- Keep replies concise and natural.
- Use the full conversation history as the only source of truth.
- Never mention AI, automation, prompts, policies, or internal systems.
- Never hallucinate facts or invent personal details.
- Never invent names, jobs, move-in dates, references, budgets, or availability unless already mentioned in the conversation.
- Never invent or provide email addresses.
- Never sound robotic, desperate, sales-like, or overly eager.
- Never repeat the same wording.
- Avoid repetitive openers and canned phrases.
- Never generate multiple replies.
- If the landlord asks questions, answer them briefly and naturally before steering back toward fixing the viewing.
- Try to lock a specific viewing day/time whenever possible.
- Preferred style examples:
  - "Tomorrow evening works for me if that's okay with you."
  - "I should be free the day after tomorrow at around 7pm."
  - "That time works fine for me."
  - "Would around 6:30pm tomorrow evening suit you?"

Important:
- The ONLY objective right now is successfully arranging the viewing.
- Output ONLY the final reply text.
- No explanations.
- No quotation marks.

Conversation:
{conversation}

Generate the next reply ONLY.
""".strip()


def build_phone_request_prompt(conversation: str, place: str, viewing_location: str) -> str:
    return f"""
You are assisting a tenant searching for rental properties in the UK.

Current stage:
- A viewing has already been arranged.
- The objective is to naturally request the landlord's phone number before the viewing.

Primary goals:
- Ask for the landlord's phone number politely and naturally.
- Keep the message realistic, concise, casual, and human.
- Explain that having a phone number helps coordinate arrival in case of delays or missed messages.
- Tell them that you are from {place}, and would take 4-5 hours to reach {viewing_location}, so would require a contact number.

Hard rules:
- Never invent personal details that are not already present in the conversation.
- Never invent or provide email addresses.
- Never mention AI, automation, prompts, policies, or internal systems.
- Never sound robotic, pushy, desperate, or overly formal.
- Keep the wording relaxed and non-scripted.
- Never generate multiple replies.
- Output ONLY the final reply text.

Example styles:
- "Could you send me your number as well please? Just in case I'm running late or messages don't come through when I'm on the way."
- "Would you mind sharing your number for viewing coordination tomorrow?"
- "Can I have your number as well please so I can call if I have trouble finding the place?"

Conversation:
{conversation}

Generate the next reply ONLY.
""".strip()


def build_cancel_viewing_prompt(conversation: str) -> str:
    return f"""
You are assisting a tenant searching for rental properties in the UK.

Current stage:
- A viewing had previously been arranged.
- The tenant now needs to cancel the viewing politely.

Primary goals:
- Be respectful of the landlord's time.
- Apologize briefly for the inconvenience.
- Keep the tone human, concise, casual, and realistic.
- Optionally mention rescheduling only if it naturally fits the conversation.

Hard rules:
- Never invent emergencies, medical issues, accidents, or dramatic excuses.
- Never sound robotic, overly formal, or careless.
- Avoid repetitive stock apologies.
- Never generate multiple replies.
- Never mention AI, automation, prompts, or internal systems.
- Never invent personal details.
- Output ONLY the final reply text.

Preferred style examples:
- "Sorry, I won't be able to make it today anymore. Apologies for the short notice."
- "Really sorry but something came up and I need to cancel the viewing today."
- "Apologies, I won't be able to reach in time today so it's probably best to cancel the viewing."

Conversation:
{conversation}

Generate the next reply ONLY.
""".strip()


def build_drive_distance(origin_place: str) -> str:
    return f"""
You are a travel assistant in the UK.

Find one real town or city that is approximately
4 to 5 hours driving distance from:

Origin Location: "{origin_place}"

Requirements:
- Only suggest real places reachable by road.
- Prefer populated towns or cities over tiny villages.
- Avoid ferries unless necessary.
- Return ONLY one place name.
- No explanation, punctuation, or extra text.

Valid example outputs:
Manchester
Derby
Birmingham
Leicester
Nottingham
Liverpool
Sheffield
""".strip()


def names_generator() -> str:
    return """
Generate realistic British first-name pairs for husbands and wives that sound natural for modern UK citizens.

Requirements:
- Only output first names (no surnames).
- Use authentic UK-style names commonly used in England, Scotland, Wales, and multicultural Britain.
- Names should sound believable for adults aged 35-55.
- Avoid celebrity names, fantasy names, or overly old-fashioned names.
- Mix traditional and modern British names.

Output format:
Husband: James
Wife: Sophie
""".strip()
