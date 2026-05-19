from dataclasses import asdict, dataclass, field

from simulation.sessions.serializers import json_ready


@dataclass
class AgentResponse:
    reply_text: str | None
    raw_prompt: str | None
    raw_completion: str | None
    model: str | None
    temperature: float | None
    valid: bool
    error: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


@dataclass
class EvaluationResult:
    evaluator_id: str
    score: float
    passed: bool
    dimension_scores: dict
    failure_types: list[str]
    rationale: str
    evaluation_timing_ms: int


@dataclass
class SimulationSession:
    session_id: str
    mode: str
    start_mode: str
    initial_message_source: str | None
    initial_message: str | None
    scenario_id: str
    actor_id: str
    policy_id: str
    deterministic_seed: int
    max_turns: int
    transcript: list
    events: list
    evaluation: EvaluationResult
    runtime_context: dict
    replay_output: str
    observability: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return json_ready(asdict(self))
