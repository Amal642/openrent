"""
Handles recommendation questions by combining platform stats, business rules,
and a compact OpenAI call.
"""

import os

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.advisor.rules import rules_summary_for_prompt
from app.advisor.stats_service import all_stats_for_prompt

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_SYSTEM_PROMPT = """\
You are an operations advisor for Land Royal, a UK property rental outreach platform.
Your job is to help non-technical operators make smart operational decisions.

Business rules (fixed — use these for all calculations):
{rules}

Current platform data:
{data}

How to answer:
- Use plain English. Never mention databases, servers, connections, APIs, or infrastructure.
- Show your calculation when answering "how many" or "how long" questions.
- State clearly when an estimate is based on assumptions rather than real data.
- Be specific — give numbers, not vague ranges, whenever the data supports it.
- Keep your answer under 200 words unless a longer explanation is genuinely needed.
- If the question is not something you can calculate, say so honestly and suggest what information would help.
"""


def generate_recommendation(question: str) -> str:
    rules = rules_summary_for_prompt()
    data = all_stats_for_prompt()

    system = _SYSTEM_PROMPT.format(rules=rules, data=data)

    try:
        response = _client.chat.completions.create(
            model=os.getenv("OPENAI_REPLY_MODEL", "gpt-4.1-mini"),
            temperature=0.3,
            max_tokens=400,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
        return (response.choices[0].message.content or "").strip()
    except RateLimitError:
        return (
            "I'm temporarily unavailable due to high demand. "
            "Please try again in a moment."
        )
    except APITimeoutError:
        return "The request timed out. Please try again."
    except APIError as exc:
        return f"Something went wrong generating a recommendation ({exc.status_code}). Please try again."
