from dataclasses import dataclass, field


@dataclass
class MemoryState:
    notes: list[str] = field(default_factory=list)
    extracted_entities: dict = field(default_factory=dict)

