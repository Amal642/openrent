from app.ai.prompts import build_reply_prompt
from simulation.policies.base import AgentPolicy


class AggressiveFollowupPolicy(AgentPolicy):
    def __init__(self):
        super().__init__(
            policy_id="aggressive-followup-v1",
            model="gpt-4.1-mini",
            temperature=0.2,
            allow_phone_request=True,
            allow_negotiation=False,
            max_followups=3,
            allow_property_claims=False,
            allow_price_discussion=False,
            escalation_allowed=False,
        )

    def build_prompt(self, conversation: str) -> str:
        return build_reply_prompt(conversation)

