from dataclasses import dataclass


@dataclass
class SimulationEvent:
    event_type: str
    turn_index: int
    timestamp: str
    payload: dict

