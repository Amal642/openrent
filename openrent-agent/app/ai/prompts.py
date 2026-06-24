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
    "screening_first_v1": [
        "Build landlord confidence before asking for contact details.",
        "Answer questions about work, household, affordability, and move-in directly using only persona facts.",
        "Once the landlord seems comfortable, steer toward arranging a viewing.",
        "Ask for a number only after screening concerns are satisfied and viewing coordination is relevant.",
    ],
    "confirmation_close_v1": [
        "Do not ask for a phone number until a specific viewing date or time is agreed or nearly agreed.",
        "If no concrete time exists yet, keep narrowing availability instead of asking for contact details.",
        "After a time is agreed, ask for the best number only as a practical day-of-viewing fallback.",
        "Use logistics reasons such as delays, finding the entrance, directions, or last-minute changes.",
    ],
    "tenant_shares_first_v1": [
        "Use reciprocity: after viewing progress exists, share the tenant mobile first as optional coordination help.",
        "Do not share the tenant mobile before viewing progress.",
        "Invite the landlord to use whichever channel is easiest rather than demanding their number.",
        "Only ask for the landlord's best number after sharing yours if it is needed for viewing logistics.",
    ],
    "landlord_preference_v1": [
        "Let the landlord choose the coordination channel.",
        "When viewing coordination is relevant, ask whether they prefer to arrange it here or by phone.",
        "Do not directly ask for their number unless they opt into phone coordination.",
        "If they prefer OpenRent messages, continue there without pushing off-platform.",
    ],
    "corpus_number_capture_v1": [
        "Primary goal: get the landlord's contact number naturally, without making it look like the number is the main goal.",
        "Use viewing progress as the gate: viewing, video viewing, timing, travel, directions, delays, or day-of-viewing logistics must be in play before asking.",
        "Before that gate exists, answer screening questions and keep moving toward a viewing or video viewing.",
        "If the landlord asks screening questions before sharing contact details, answer them first, then ask about viewing and include a soft request for the landlord's best number for coordination.",
        "If you have just answered screening and proposed or narrowed a viewing time/window, do not skip the number ask; include it as a low-pressure logistics fallback.",
        "Do not volunteer or share the tenant mobile number in this design; the target is the landlord's number.",
        "Write like a real tenant texting: brief, casual, practical, and a little imperfect rather than polished.",
        "When asking for the landlord's number, use one concrete logistics reason such as driving down, confirming timing, finding the entrance, directions, delays, or video-viewing coordination.",
        "Avoid eager or scripted phrases like 'kindly share your contact details', repeated WhatsApp pushes, long reassurance, or generic empathy.",
        "If the landlord resists phone or WhatsApp, continue on OpenRent and do not push again immediately.",
    ],
    "corpus_number_capture_v2": [
        "Primary goal: get the landlord's number naturally, but never make the number look like the main goal.",
        "Do not share the tenant mobile number. If pressed for it, say you would rather not share yours just yet because of past bad experiences, and offer to keep it on OpenRent if they prefer.",
        "Answer landlord screening questions first using only persona facts, especially work, household, income/affordability, and move timing.",
        "When answering work screening, use explicit human wording like 'I work full-time as...' or 'my partner works as...' rather than only giving job titles.",
        "If one partner is at home or not working, say that plainly using persona facts; do not invent a second income.",
        "Before any phone ask, create a practical viewing reason: agreed or proposed viewing, video viewing, travel, delays, entrance, directions, or same-day updates.",
        "If the landlord is withholding contact details until screening is answered, answer screening and then use a direct but soft line like 'Could I get your number just in case we're delayed getting there?'",
        "Avoid polished phrases like 'best number', 'coordinate', 'contact details', 'sort timing', or 'kindly share'. Use normal wording like 'could I get your number' or 'just in case we're delayed'.",
        "If the landlord refuses to share a number before a viewing is booked, do not ask again in the next tenant reply. Accept it and keep arranging the viewing on OpenRent.",
        "After a phone refusal, only ask again later if there is a new practical reason, such as travel on the day, finding the entrance, or a video viewing setup.",
        "If the landlord seems suspicious, stop phone pressure, give one brief trust-building detail from the persona, and continue on OpenRent.",
        "If the viewing is confirmed immediately after a refusal, acknowledge the booking and keep it on OpenRent; do not instantly ask for the number.",
    ],
    # OPEN-21D A/B playbook design: a CLONE of corpus_number_capture_v2 + rule P5 (drop/park dead
    # leads). Separate id so corpus_number_capture_v2 is left untouched for any other use, and the
    # A/B logs truthfully show this design id as the effective design.
    "playbook_ab_v1": [
        "Primary goal: get the landlord's number naturally, but never make the number look like the main goal.",
        "Do not share the tenant mobile number. If pressed for it, say you would rather not share yours just yet because of past bad experiences, and offer to keep it on OpenRent if they prefer.",
        "Answer landlord screening questions first using only persona facts, especially work, household, income/affordability, and move timing.",
        "When answering work screening, use explicit human wording like 'I work full-time as...' or 'my partner works as...' rather than only giving job titles.",
        "If one partner is at home or not working, say that plainly using persona facts; do not invent a second income.",
        "Before any phone ask, create a practical viewing reason: agreed or proposed viewing, video viewing, travel, delays, entrance, directions, or same-day updates.",
        "If the landlord is withholding contact details until screening is answered, answer screening and then use a direct but soft line like 'Could I get your number just in case we're delayed getting there?'",
        "Avoid polished phrases like 'best number', 'coordinate', 'contact details', 'sort timing', or 'kindly share'. Use normal wording like 'could I get your number' or 'just in case we're delayed'.",
        "If the landlord refuses to share a number before a viewing is booked, do not ask again in the next tenant reply. Accept it and keep arranging the viewing on OpenRent.",
        "After a phone refusal, only ask again later if there is a new practical reason, such as travel on the day, finding the entrance, or a video viewing setup.",
        "If the landlord seems suspicious, stop phone pressure, give one brief trust-building detail from the persona, and continue on OpenRent.",
        "If the viewing is confirmed immediately after a refusal, acknowledge the booking and keep it on OpenRent; do not instantly ask for the number.",
        # OPEN-21D playbook rule P5 (drop/park dead leads):
        "If the property is unavailable or already let, park the lead politely and stop; do not keep pushing a dead lead.",
    ],
}


LANDLORD_NUMBER_CAPTURE_DESIGNS = {
    "corpus_number_capture_v1",
    "corpus_number_capture_v2",
    "playbook_ab_v1",   # OPEN-21D A/B (clone of v2 + P5); withholds tenant mobile like the corpus designs
}

# Designs that use the corpus_number_capture_v2-style phrasing + extra rules.
CORPUS_V2_STYLE_DESIGNS = {"corpus_number_capture_v2", "playbook_ab_v1"}


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
- IMPORTANT: If the landlord is ASKING FOR a phone number (e.g. "send me your number", "what is your number", "could you share your number", "please send your contact") without providing their own number, return EXACTLY: NONE. Asking for a number is not the same as sharing one.
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
    phone_ask_count: int = 0,
    property: dict | None = None,
) -> str:
    if stage == "VIEWING_CANCELLED":
        return build_cancel_viewing_prompt(conversation)

    if stage == "VIEWING_BOOKED" and not landlord_asked_for_number:
        return build_phone_request_prompt(
            conversation,
            place=place,
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
        origin_place=place,
        urgency="normal",
        friendliness_level="medium",
        trust_level="medium",
        escalation_behavior=(persona or {}).get("escalation_behavior"),
        outbound_count=outbound_count,
        phone_ask_count=phone_ask_count,
        property=property,
    )


def _persona_context_lines(
    persona: dict | None,
    *,
    expose_mobile: bool = True,
) -> list[str]:
    persona = persona or {}
    lines = [
        f"- Persona summary: {persona_summary(persona)}",
        f"- Persona type: {persona.get('persona_type') or 'unknown'}",
        f"- Tone: {persona.get('message_tone') or 'brief, casual, realistic'}",
        f"- Phone fetching type: {persona.get('phone_fetching_type') or 'delayed'}",
        f"- Message strategy: {persona.get('message_strategy') or 'viewing first, then contact details'}",
        f"- Conversation goal: {persona.get('conversation_goal') or 'arrange a viewing and coordinate contact details naturally'}",
    ]
    # Income estimates — derived from rent affordability formula even when
    # rent_pcm is not in the persona (replies don't have listing metadata).
    # Using a default of 1500 gives realistic Greater Manchester figures.
    rent_pcm = persona.get("rent_pcm") or 1500
    annual_income = (rent_pcm * 30) + 20000
    # Round to nearest £100 so answers sound human, not machine-generated.
    monthly_income = round(annual_income / 12 / 100) * 100
    lines.append(
        f"- Estimated combined monthly income: approximately GBP {monthly_income:,}/month "
        f"(annual proxy: GBP {annual_income:,})"
    )
    has_partner = bool(persona.get("persona_partner_name"))
    if has_partner:
        # Slightly unequal 48/52 split so per-person amounts feel realistic.
        primary_monthly = round(monthly_income * 0.48 / 100) * 100
        partner_monthly = monthly_income - primary_monthly
        lines.append(
            f"- Per-person income (approximate, rounded): "
            f"GBP {primary_monthly:,}/month (primary tenant), "
            f"GBP {partner_monthly:,}/month (partner)"
        )

    if persona.get("screening_posture"):
        lines.append(f"- Screening posture: {persona.get('screening_posture')}")
    if persona.get("phone_boundary"):
        lines.append(f"- Contact boundary: {persona.get('phone_boundary')}")
    if persona.get("persona_partner_name") and not persona.get("persona_partner_job"):
        lines.append(
            "- Partner job is not known; do not invent the partner's employment."
        )
    elif persona.get("persona_partner_name") and persona.get("persona_partner_job"):
        lines.append(
            f"- Partner status/job to use if asked: {persona.get('persona_partner_job')}"
        )
    if expose_mobile and persona.get("mobile_number"):
        lines.append(f"- Mobile number for this account: {persona.get('mobile_number')}")
    elif persona.get("mobile_number"):
        lines.append("- Mobile number for this account: intentionally withheld for this strategy")
    else:
        lines.append("- Mobile number for this account: none assigned")
    return lines


def _property_context_lines(property: dict | None) -> list[str]:
    if not property:
        return ["- No specific property details provided; refer to it generically as 'the property'."]
    lines = []
    title = property.get("title")
    if title:
        lines.append(f"- Listing: {title}")
    bedrooms = property.get("bedrooms")
    if bedrooms is not None:
        lines.append(f"- Bedrooms: {bedrooms}")
    rent_pcm = property.get("rent_pcm")
    if rent_pcm is not None:
        lines.append(f"- Rent: GBP {int(rent_pcm):,} pcm")
    location = property.get("location")
    if location:
        lines.append(f"- Location: {location}")
    furnished = property.get("furnished")
    if furnished is not None:
        lines.append(f"- Furnished: {'yes' if furnished else 'no'}")
    available_from = property.get("available_from")
    if available_from:
        lines.append(f"- Available from: {available_from}")
    if not lines:
        return ["- No specific property details provided; refer to it generically as 'the property'."]
    return lines


def _phone_policy_lines(
    persona: dict | None,
    *,
    stage: str | None,
    conversation_design_id: str | None,
    phone_number_shared: bool,
    landlord_asked_for_number: bool,
    outbound_count: int,
    drive_distance: str | None,
    phone_ask_count: int = 0,
) -> list[str]:
    persona = persona or {}
    phone_type = persona.get("phone_fetching_type") or "delayed"
    mobile = persona.get("mobile_number")

    if conversation_design_id in LANDLORD_NUMBER_CAPTURE_DESIGNS:
        number_phrase = (
            "the landlord's number"
            if conversation_design_id in CORPUS_V2_STYLE_DESIGNS
            else "the landlord's best number"
        )
        lines = [
            "- Strategy target: obtain the landlord's number; do not share the tenant mobile number.",
            f"- Phone already shared by tenant: {'yes' if phone_number_shared else 'no'}",
            f"- Landlord explicitly asked for tenant number/contact/WhatsApp: {'yes' if landlord_asked_for_number else 'no'}",
            f"- Outbound tenant messages so far: {outbound_count}",
            f"- Times you have already asked for the landlord's number in this conversation: {phone_ask_count}",
            f"- Drive distance context: {drive_distance or 'unknown'}",
            "- Never invent any number, email address, or contact detail.",
            "- If the landlord asks for YOUR (the tenant's) phone number or mobile, do NOT provide it. "
            "Redirect naturally: tell them your husband is handling the viewing coordination and ask for the landlord's number to pass on to him. "
            "Keep it brief and natural — e.g. 'My husband's actually sorting the viewing side of things, would you be able to share your number so I can pass it to him?'.",
            "- Do not ask for the landlord's number until viewing, video viewing, timing, travel, directions, delays, or day-of-viewing logistics are being discussed.",
            f"- If your reply answers screening and proposes or narrows a viewing time/window, include a soft request for {number_phrase} for viewing logistics.",
            f"- Good shape: answer screening in one short sentence, suggest or ask about viewing timing, then ask for {number_phrase} in case of delays.",
        ]
        if phone_ask_count >= 2:
            lines.append(
                f"- You have already asked for the landlord's number {phone_ask_count} time(s). "
                "Do NOT ask for it again in this reply. Wait until the viewing is confirmed or logistics genuinely need it."
            )
        if stage == "VIEWING_BOOKED":
            lines.append(
                f"- A viewing appears booked, so it can be appropriate to ask for {number_phrase} for practical viewing logistics unless the landlord has just refused phone sharing."
            )
        if conversation_design_id in CORPUS_V2_STYLE_DESIGNS:
            lines.extend(
                [
                    "- If the landlord has refused to share a number, respect that for the next tenant reply and keep arranging on OpenRent.",
                    "- If the landlord asks for YOUR phone number, do not provide it. Redirect: say your husband is handling the viewing logistics and ask for the landlord's number to pass to him.",
                    "- Do not ask for a number immediately after a booking if the previous landlord message refused phone sharing before booking.",
                    "- When answering screening, explicitly say 'work' or 'working full-time' if that is true from persona facts.",
                    "- Prefer 'Could I get your number just in case we're delayed?' over conditional wording like 'if we set a time, could I...'.",
                    "- Avoid these phrases in the final reply: best number, coordinate, contact details, sort timing, kindly share.",
                ]
            )
        return lines

    lines = [
        f"- Phone already shared by tenant: {'yes' if phone_number_shared else 'no'}",
        f"- Landlord explicitly asked for tenant number/contact/WhatsApp: {'yes' if landlord_asked_for_number else 'no'}",
        f"- Outbound tenant messages so far: {outbound_count}",
        f"- Times you have already asked for the landlord's number in this conversation: {phone_ask_count}",
        f"- Drive distance context: {drive_distance or 'unknown'}",
        "- Never invent any other number, email address, or contact detail.",
    ]
    if mobile:
        lines.insert(0, f"- Husband's/partner's WhatsApp number: {mobile}")
        lines.insert(
            5,
            f"- If the landlord asks for our number OR seems reluctant to share their own: share {mobile} as "
            "'my husband's WhatsApp' (or 'my partner's WhatsApp' if unsure). "
            "Tell them to reach out via WhatsApp only. Do NOT ask for their number in that same message.",
        )
    else:
        lines.insert(0, "- No mobile number is assigned for this account.")
        lines.insert(
            5,
            "- If the landlord asks for our number, do not provide any number; "
            "answer the rest of their message naturally and keep arranging the viewing in OpenRent.",
        )

    if not mobile:
        lines.append(
            "- Phone sharing is disabled until this account has an assigned mobile number."
        )
    elif phone_type in {"immediate", "whatsapp_first"}:
        lines.append(
            "- This persona may share the mobile number in the first or second message when it sounds natural."
        )
    elif phone_type == "viewing_first":
        lines.append(
            "- Prioritize getting a phone number early — ask for the landlord's number by the second or third reply at the latest, framing it as needing it for viewing day coordination."
        )
    elif phone_type == "landlord_requests_only":
        lines.append(
            "- Do not volunteer the tenant mobile number unless the landlord asks or a viewing needs coordination."
        )
    elif phone_type == "adaptive":
        lines.append(
            "- Adapt to the landlord's tone and viewing progress, but always aim to ask for their phone number by the third or fourth reply."
        )
    else:
        lines.append(
            "- Delayed strategy: build a small amount of rapport first, but ask for the landlord's phone number by the fourth or fifth reply at the latest — do not wait longer."
        )

    if stage == "VIEWING_BOOKED":
        lines.append(
            "- A viewing appears booked, so it is appropriate to coordinate phone details if they have not already been exchanged."
        )
    elif stage == "VIEWING_DISCUSSION":
        lines.append(
            "- Viewing details are still being discussed; keep replying naturally to availability, scheduling, and follow-up questions."
        )

    # Hard count-based enforcement: fires only if we haven't asked twice already.
    # Once phone_ask_count >= 2, suppress MANDATORY lines to avoid being pushy.
    if not phone_number_shared and not landlord_asked_for_number:
        if phone_ask_count >= 2:
            lines.append(
                f"- You have already asked for the landlord's number {phone_ask_count} time(s) in this conversation. "
                "Do NOT ask for it again in this reply. Only ask again naturally when a viewing time is being confirmed or you are coordinating day-of logistics."
            )
        else:
            if phone_type in {"viewing_first"} and outbound_count >= 1:
                lines.append(
                    f"- MANDATORY: {outbound_count} message(s) sent so far with no phone number obtained. "
                    "This reply MUST include a brief, natural ask for the landlord's phone number — "
                    "e.g. 'Could I grab your number for the viewing?' Do not skip this."
                )
            elif phone_type in {"delayed", "adaptive"} and outbound_count >= 3:
                lines.append(
                    f"- MANDATORY: {outbound_count} messages sent with no phone number obtained. "
                    "This reply MUST include a natural ask for the landlord's phone number."
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
    origin_place: str | None = None,
    urgency: str | None = None,
    friendliness_level: str | None = None,
    trust_level: str | None = None,
    escalation_behavior: str | None = None,
    outbound_count: int = 0,
    phone_ask_count: int = 0,
    property: dict | None = None,
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

Property context (the listing being discussed):
{chr(10).join(_property_context_lines(property))}

Tenant/persona/account context:
{chr(10).join(_persona_context_lines(
    persona,
    expose_mobile=conversation_design_id not in LANDLORD_NUMBER_CAPTURE_DESIGNS,
))}

Phone sharing policy:
{chr(10).join(_phone_policy_lines(
    persona,
    stage=stage,
    conversation_design_id=conversation_design_id,
    phone_number_shared=phone_number_shared,
    landlord_asked_for_number=landlord_asked_for_number,
    outbound_count=outbound_count,
    drive_distance=drive_distance,
    phone_ask_count=phone_ask_count,
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
- If the landlord asked multiple questions (income, adults, pets, employment, move date), answer ALL of them in a single reply. Do not skip or defer any question.
- Vary your wording. If you used a phrase in a previous message, say it differently this time.
- No bullet points, lists, or headers in the actual reply. Plain text only.
- Keep it short - 1 to 3 sentences is almost always enough.
- Use natural punctuation; emojis are allowed only rarely and only if the conversation already feels casual.
- Do not repeat identical phone request wording.
- Never use em dashes (—) or en dashes (–). Use a comma or split into two sentences instead.
- Avoid overly polished or corporate punctuation chains.
- Write as a real UK tenant would type on their phone, not as a drafted email. Slightly imperfect phrasing is fine.
- Income and affordability: ONLY share income, salary, or financial figures if the landlord has explicitly asked about them in their most recent message. Do not volunteer financial details proactively — not even briefly or in passing. When the landlord does ask, answer directly using the income figures from the persona context above. Use "around" or "roughly" before the amounts (e.g. "around £5,400 a month combined"). Never say something vague like "our income comfortably covers the rent" without giving a number. Never leave an income question unanswered. Never make up oddly precise figures like £2,741; use rounded £100 amounts from the context.

Hard rules:
- NEVER volunteer income, salary, affordability, or financial figures unless the landlord explicitly asked about them in their last message. If they did not ask, leave these details out entirely.
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
- If the landlord asks for contact details, follow the phone sharing policy for this conversation design.
- If the landlord offers an email or asks for one, politely redirect to phone contact later after the viewing is arranged.
- Output only the final reply text and nothing else.
- NEVER use square brackets [ ], curly brackets {{ }}, or any bracket notation as placeholders anywhere in your reply. A real person does not write [Company Name], [approximate amount], [insert anything], or any similar pattern. If a specific detail is unknown, omit it or rephrase naturally — never write a placeholder.
- NEVER mention or invent a company name or employer name. If asked where you work, state only your job title (e.g. "I work as a software engineer" or "I'm in marketing"). Do not add "at [Company Name]" or any company reference of any kind.
- NEVER write a placeholder for an income figure. The actual income amounts are provided above in the persona context — use them directly (e.g. "around £5,400 a month combined"). If for any reason the figure is unclear, say "comfortably covers the rent" — never write [approximate amount] or similar.
- NEVER say "thanks for sharing your number", "thanks for your number", "got your number", or any phrase that implies you received the landlord's number UNLESS a sequence of actual digits (a phone number) is visibly present in the landlord's messages above. The landlord ASKING for the tenant's number is completely different from the landlord SHARING their own number — do not confuse them.
{f"- Your home is in {origin_place} — you are travelling FROM there TO view this property. If the landlord asks where you live or where you are from, say {origin_place}. NEVER say you live in or near the property area." if origin_place else ""}

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
    if persona.get("mobile_number"):
        tenant_context.append(f"- Mobile number: {persona.get('mobile_number')}")
    else:
        tenant_context.append("- Mobile number: none assigned")
    tenant_context.append(
        f"- Phone strategy: {persona.get('phone_fetching_type') or 'delayed'}"
    )
    tenant_context.append(
        f"- Messaging style: {persona.get('conversation_style') or 'friendly_viewing'}"
    )

    phone_type = persona.get("phone_fetching_type") or "delayed"
    if not persona.get("mobile_number"):
        phone_instruction = "No mobile number is assigned, so do not include any phone number."
    elif phone_type in {"immediate", "whatsapp_first"}:
        phone_instruction = "You may include the mobile number if asking for WhatsApp/video-call coordination feels natural."
    else:
        phone_instruction = "Do not include the mobile number in this first enquiry unless the chosen style explicitly needs WhatsApp/video-call coordination."

    return f"""
You are helping a tenant write a short and natural UK rental enquiry.

Property Details:
- Bedrooms: {property_data.get("bedrooms")}

Tenant context:
{chr(10).join(tenant_context)}

Primary Goal:
- Set up a viewing appointment.
- Sound genuinely interested in the property itself, the household fit, and availability.

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
- If you include a phone number, use only the exact assigned mobile number from the tenant context.
- If no mobile number is assigned, do not include any phone number.
- Do not sound overly enthusiastic or robotic.
- Avoid formulaic openers or repeated wording.
- Never use em dashes (—) or en dashes (–). Use a comma or two short sentences instead.
- Write like a real UK tenant texting from their phone. Slightly imperfect phrasing is better than polished prose.
- Never mention the rent amount, monthly cost, price, or anything like "for £X pcm" or "listed at £X". The landlord already knows their own price and it makes the message feel automated.
- Focus entirely on the property, the household's suitability, employment, and requesting a viewing.
- Maximum 120 words.
- NEVER use square brackets, curly brackets, or any bracket notation as placeholders. Do not write [Company Name], [amount], [insert anything], or similar. Never mention a company or employer name — state only the job title if relevant.
- NEVER invent or placeholder any detail that is not explicitly in the tenant context above.

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
- Never use em dashes (—) or en dashes (–). Use a comma or two short sentences instead.
- Write like a real UK tenant texting, not like a polished email. Slightly informal phrasing is fine.
- NEVER use square brackets, curly brackets, or any bracket notation as placeholders. Do not write [anything] or {{anything}} — a real person texting does not write placeholders.
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
- IMPORTANT: The origin city is {place}. This is fixed for this conversation. Never mention any other city.

Hard rules:
- Never invent personal details that are not already present in the conversation.
- Never invent or provide email addresses.
- Never mention AI, automation, prompts, policies, or internal systems.
- Never sound robotic, pushy, desperate, or overly formal.
- Keep the wording relaxed and non-scripted.
- Never generate multiple replies.
- Never use em dashes (—) or en dashes (–). Use a comma or a new sentence instead.
- NEVER use square brackets, curly brackets, or any bracket notation as placeholders. Do not write [anything] — a real person does not write placeholders.
- Output ONLY the final reply text.

Example styles:
- "Could you send me your number as well please? Just in case I'm running late or messages don't come through when I'm on the way."
- "Would you mind sharing your number for viewing coordination tomorrow?"
- "Can I have your number as well please so I can call if I have trouble finding the place?"

Conversation:
{conversation}

Generate the next reply ONLY.
""".strip()


def build_follow_up_prompt(conversation: str, follow_up_number: int) -> str:
    tone = (
        "brief, friendly, low-pressure — this is the first nudge"
        if follow_up_number <= 1
        else "brief, slightly more direct, but still polite — this is the final nudge before giving up"
    )
    return f"""
You are a tenant who sent a rental enquiry on OpenRent and the landlord has not replied yet.

Current stage:
- This is follow-up message number {follow_up_number} to a landlord who has gone silent.
- No reply has been received since the original enquiry (or previous follow-up).

Primary goals:
- Write a short, natural check-in message asking if the landlord saw your previous message.
- Tone: {tone}.
- Do not repeat the original enquiry text verbatim.
- Do not sound impatient, needy, or scripted.
- Vary the wording from any earlier follow-up in this conversation.

Hard rules:
- Never invent personal details not already present in the conversation.
- Never invent or provide email addresses.
- Never mention AI, automation, prompts, policies, or internal systems.
- Never sound robotic, pushy, or desperate.
- Keep it to one short sentence or two at most.
- Never generate multiple replies.
- Never use em dashes (—) or en dashes (–). Use a comma or a short separate sentence instead.
- NEVER use square brackets, curly brackets, or any bracket notation as placeholders. Do not write [anything] — a real person does not write placeholders.
- Output ONLY the final reply text.

Example styles:
- "Hi, just checking you saw my message about the property, still interested if it's available."
- "Hey, wondering if you got my enquiry, let me know if the place is still up for viewing."
- "Hi again, no worries if you're busy, just wanted to check this is still available."

Conversation:
{conversation}

Generate the next reply ONLY.
""".strip()


def build_viewing_detection_prompt(conversation: str) -> str:
    return f"""
Analyze this OpenRent conversation between a tenant (operator/us) and a landlord.

Determine whether a specific viewing appointment has been mutually agreed.

A viewing IS arranged when:
- Both parties agreed on a specific date and/or time to meet at the property
- The landlord confirmed a time with words like "see you then", "confirmed", "that works", "come at [time]", "booked for", "all arranged"
- There is clear two-way agreement — not just one side proposing

A viewing is NOT arranged when:
- Only one side asked about availability with no confirmed reply from the other
- The conversation is still negotiating times back and forth
- The landlord only asked screening questions without confirming any viewing time
- Only vague intent like "let's arrange something" with no specific date or time

Reply with ONLY this exact JSON and nothing else:
{{
  "viewing_arranged": true or false,
  "viewing_datetime": "YYYY-MM-DD HH:MM" or null,
  "reason": "one sentence"
}}

If viewing_arranged is true but no specific datetime can be extracted, set viewing_datetime to null.

Conversation:
{conversation}
""".strip()


def build_pre_cancel_number_ask_prompt(conversation: str, place: str | None = None) -> str:
    travel_line = (
        f"You are travelling from {place} to the viewing, which is a 4-5 hour journey."
        if place else ""
    )
    return f"""
You are a tenant who has arranged a viewing for a rental property.
You want to ask the landlord for their phone number ahead of the viewing, for practical coordination.

{travel_line}

Primary goal:
- Write a short, natural message asking for the landlord's phone number.
- Frame it as practical coordination: delays, finding the entrance, directions, or last-minute changes.
- Sound casual and human — like a real person texting.

Hard rules:
- One short message only (1-2 sentences maximum).
- Do not hint that you are considering cancelling.
- Do not mention AI, automation, or internal systems.
- Never invent personal details not in the conversation.
- Never use em dashes (—) or en dashes (–). Use a comma or a short separate sentence instead.
- NEVER use square brackets, curly brackets, or any bracket notation as placeholders.
- Output ONLY the final reply text.

Example styles:
- "Just wanted to grab your number before the viewing in case I get delayed on the way."
- "Could I get your number for the viewing? Just in case I have trouble finding the place."
- "Would you mind sending your number over? Handy to have for the day."

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
- Never use em dashes (—) or en dashes (–). Use a comma or a short separate sentence instead.
- NEVER use square brackets, curly brackets, or any bracket notation as placeholders. Do not write [anything] — a real person does not write placeholders.
- NEVER mention phone numbers, say "thanks for your number", "thanks for sharing your number", or acknowledge any contact details whatsoever. The ONLY purpose of this reply is to cancel the viewing. Even if the landlord mentioned or asked about a phone number in the conversation, do not reference it.
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
