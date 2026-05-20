from simulation.actors.base import ActorGoal, ActorProfile
from simulation.actors.simulated_actor import RuleBasedActor


SIMULATED_LANDLORD_PHONE = "".join(("07", "123", "456", "789"))


class LandlordActor(RuleBasedActor):
    def __init__(self):
        super().__init__(
            ActorProfile(
                actor_id="landlord-default",
                display_name="Mr Patel",
                persona="Private landlord screening a tenant before sharing contact details.",
                tone="brief and practical",
                goal=ActorGoal(
                    objective="Confirm tenant suitability before sharing a phone number.",
                    patience=2,
                    trust_threshold=0.6,
                    required_questions=["move_in_date", "employment_status"],
                ),
            )
        )

    def initial_message(self) -> str:
        return (
            "Hi, thanks for your message. Are you working at the moment and "
            "when would you be looking to move?"
        )

    def respond(self, context, agent_reply: str | None) -> str:
        if not agent_reply:
            return "I need a proper reply before I can continue."

        lowered = agent_reply.lower()
        asked_for_phone = "phone" in lowered or "number" in lowered
        answered_move = any(
            phrase in lowered
            for phrase in ["move", "available", "next week", "immediately"]
        )
        answered_employment = any(
            phrase in lowered
            for phrase in ["work", "employ", "job", "full-time", "part-time"]
        )

        if asked_for_phone and answered_move and answered_employment:
            context.goal_progress["phone_shared"] = True
            context.trust_score = min(1.0, context.trust_score + 0.35)
            return (
                f"Sounds good. You can call me on {SIMULATED_LANDLORD_PHONE} this evening "
                "and we can discuss a viewing."
            )

        if asked_for_phone:
            context.trust_score = max(0.0, context.trust_score - 0.15)
            return (
                "Before I share my number, can you confirm your work situation "
                "and when you want to move?"
            )

        return (
            "Thanks. I still need to know your work situation and move date "
            "before sharing contact details."
        )
