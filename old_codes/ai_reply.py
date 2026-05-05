from openai import OpenAI
import os

# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client = OpenAI(api_key="sk-XXXX")

SYSTEM_PROMPT = """
You are a polite English-speaking from UK tenant trying to get a landlord’s phone number 
to discuss a rental property before booking a viewing.
Always sound human.
Never mention AI.
Never repeat previous messages.
Keep replies short, friendly and natural.
"""

def generate_reply(conversation_text):
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Conversation so far:\n{conversation_text}\n\nWrite a reply:"}
        ],
        temperature=0.6,
        max_tokens=150
    )

    return response.choices[0].message.content.strip()
