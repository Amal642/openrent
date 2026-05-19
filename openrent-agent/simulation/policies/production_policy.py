from app.ai.prompts import build_reply_prompt
from app.config import settings
from simulation.policies.base import AgentPolicy


class ProductionPolicy(AgentPolicy):
    def __init__(
        self,
        conversation_design_id: str | None = None,
        conversation_design: dict | None = None,
        persona: dict | None = None,
    ):
        super().__init__(
            policy_id="production-policy-v1",
            model=settings.OPENAI_REPLY_MODEL,
            temperature=settings.SIMULATION_DEFAULT_TEMPERATURE,
            conversation_design_id=conversation_design_id,
            conversation_design=conversation_design,
            persona=persona,
            allow_phone_request=True,
            allow_negotiation=False,
            max_followups=settings.SIMULATION_MAX_FOLLOWUPS,
            allow_property_claims=False,
            allow_price_discussion=False,
            escalation_allowed=False,
        )

    def build_prompt(self, conversation: str) -> str:
        return build_reply_prompt(
            conversation,
            persona=self.persona,
            conversation_design_id=self.conversation_design_id,
        )

