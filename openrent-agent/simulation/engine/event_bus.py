from simulation.sessions.event_models import SimulationEvent


class EventBus:
    def __init__(self):
        self._events: list[SimulationEvent] = []

    @property
    def events(self) -> list[SimulationEvent]:
        return list(self._events)

    def emit(self, event: SimulationEvent) -> None:
        self._events.append(event)

