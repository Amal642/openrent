from dataclasses import dataclass, field

from simulation.sessions.models import AgentResponse


@dataclass
class RuntimeContext:
    session_id: str
    current_turn: int = 0
    memory: dict = field(default_factory=dict)
    extracted_entities: dict = field(default_factory=dict)
    trust_score: float = 0.35
    flags: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    deterministic_seed: int = 42
    goal_progress: dict = field(default_factory=dict)
    last_agent_response: object | None = None
    last_actor_response: str | None = None

    @classmethod
    def from_snapshot(cls, snapshot: dict | None) -> "RuntimeContext":
        snapshot = snapshot or {}
        context = cls(
            session_id=snapshot.get("session_id", ""),
            current_turn=snapshot.get("current_turn", 0),
            memory=dict(snapshot.get("memory") or {}),
            extracted_entities=dict(snapshot.get("extracted_entities") or {}),
            trust_score=snapshot.get("trust_score", 0.35),
            flags=dict(snapshot.get("flags") or {}),
            metrics=dict(snapshot.get("metrics") or {}),
            deterministic_seed=snapshot.get("deterministic_seed", 42),
            goal_progress=dict(snapshot.get("goal_progress") or {}),
            last_actor_response=snapshot.get("last_actor_response"),
        )
        last_agent_response = snapshot.get("last_agent_response")
        if last_agent_response:
            context.last_agent_response = AgentResponse(
                reply_text=last_agent_response.get("reply_text"),
                raw_prompt=last_agent_response.get("raw_prompt"),
                raw_completion=last_agent_response.get("raw_completion"),
                model=last_agent_response.get("model"),
                temperature=last_agent_response.get("temperature"),
                valid=last_agent_response.get("valid", False),
                error=last_agent_response.get("error"),
                prompt_tokens=last_agent_response.get("prompt_tokens", 0),
                completion_tokens=last_agent_response.get(
                    "completion_tokens",
                    0,
                ),
                total_tokens=last_agent_response.get("total_tokens", 0),
                latency_ms=last_agent_response.get("latency_ms", 0),
            )
        return context

    def snapshot(self) -> dict:
        agent_response = self.last_agent_response
        agent_snapshot = None
        if agent_response is not None:
            agent_snapshot = {
                "reply_text": agent_response.reply_text,
                "raw_prompt": agent_response.raw_prompt,
                "raw_completion": agent_response.raw_completion,
                "model": agent_response.model,
                "temperature": agent_response.temperature,
                "error": agent_response.error,
                "valid": agent_response.valid,
                "prompt_tokens": agent_response.prompt_tokens,
                "completion_tokens": agent_response.completion_tokens,
                "total_tokens": agent_response.total_tokens,
                "latency_ms": agent_response.latency_ms,
            }

        return {
            "session_id": self.session_id,
            "current_turn": self.current_turn,
            "memory": dict(self.memory),
            "extracted_entities": dict(self.extracted_entities),
            "trust_score": self.trust_score,
            "flags": dict(self.flags),
            "metrics": dict(self.metrics),
            "deterministic_seed": self.deterministic_seed,
            "goal_progress": dict(self.goal_progress),
            "last_agent_response": agent_snapshot,
            "last_actor_response": self.last_actor_response,
        }
