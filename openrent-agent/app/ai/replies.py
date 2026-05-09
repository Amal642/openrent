from openai import OpenAI

from app.config import settings


client = OpenAI(
    api_key=settings.OPENAI_API_KEY
)


def format_conversation(messages):

    lines = []

    for msg in messages:

        sender = msg["sender"]

        text = msg["message"]

        lines.append(
            f"{sender.upper()}: {text}"
        )

    return "\n".join(lines)


def generate_reply(messages):

    conversation = format_conversation(
        messages
    )

    prompt = f"""
You are assisting a tenant searching for rental properties in the UK.

Your role:
- Reply naturally and politely
- Sound human
- Keep replies concise
- Maintain conversation continuity
- Do not sound robotic
- Never mention being an AI
- Never over-explain
- Never generate fake information
- Focus on arranging viewings and progressing the conversation
- Sound like a genuine tenant

Conversation:
{conversation}

Generate the next reply ONLY.
"""

    response = client.chat.completions.create(

        model="gpt-4.1-mini",

        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],

        temperature=0.7
    )

    reply = (
        response.choices[0]
        .message.content
        .strip()
    )

    return reply