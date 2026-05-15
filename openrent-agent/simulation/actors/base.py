from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActorGoal:
    objective: str
    patience: int = 2
    trust_threshold: float = 0.5
    required_questions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActorProfile:
    actor_id: str
    display_name: str
    persona: str
    tone: str
    goal: ActorGoal


class SimulatedActor(ABC):
    def __init__(self, profile: ActorProfile):
        self.profile = profile

    @abstractmethod
    def initial_message(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def respond(self, context, agent_reply: str | None) -> str:
        raise NotImplementedError

