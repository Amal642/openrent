from dataclasses import dataclass


@dataclass
class AgentPolicy:
    policy_id: str
    model: str
    temperature: float
    conversation_design_id: str | None = None
    conversation_design: dict | None = None
    persona: dict | None = None
    property: dict | None = None
    allow_phone_request: bool = True
    allow_negotiation: bool = False
    max_followups: int = 1
    allow_property_claims: bool = False
    allow_price_discussion: bool = False
    escalation_allowed: bool = False

    def build_prompt(self, conversation: str) -> str:
        raise NotImplementedError
