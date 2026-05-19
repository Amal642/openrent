from simulation.actors.base import ActorGoal, ActorProfile, SimulatedActor


class HumanActor(SimulatedActor):
    """Interactive actor whose messages are supplied externally by the UI/API."""

    def __init__(self):
        super().__init__(
            ActorProfile(
                actor_id="human-actor",
                display_name="Human Actor",
                persona="Human-controlled landlord or scenario persona.",
                tone="user-directed",
                goal=ActorGoal(
                    objective="Drive the conversation manually from the UI.",
                    patience=999,
                    trust_threshold=0.0,
                    required_questions=[],
                ),
            )
        )

    def initial_message(self) -> str:
        raise RuntimeError(
            "HumanActor does not generate messages automatically."
        )

    def respond(self, context, agent_reply: str | None) -> str:
        raise RuntimeError(
            "HumanActor responses must be submitted through the interactive API."
        )
