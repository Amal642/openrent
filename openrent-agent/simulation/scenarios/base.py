from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    description: str
    success_criteria: list[str]
    stop_conditions: list[str]
    start_mode: str = "actor_starts"
    expected_signals: list[str] = field(default_factory=list)
    max_turns: int = 1
