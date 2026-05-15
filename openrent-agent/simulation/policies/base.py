from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPolicy:
    policy_id: str
    model: str
    temperature: float
    allow_phone_request: bool = True
    allow_negotiation: bool = False
    max_followups: int = 1
    allow_property_claims: bool = False
    allow_price_discussion: bool = False
    escalation_allowed: bool = False

    def build_prompt(self, conversation: str) -> str:
        raise NotImplementedError

