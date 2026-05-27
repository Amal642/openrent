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
        requested_viewing = any(
            phrase in lowered
            for phrase in ["view", "viewing", "arrange", "see the property"]
        )
        offered_time_earlier = context.goal_progress.get("offered_time", False)

        # Phone share fires on the original trust signal (screening
        # reanswered) OR if a viewing time was already offered earlier
        # in the conversation — the offered-time itself substitutes
        # for re-stated screening.
        if asked_for_phone and (
            (answered_move and answered_employment) or offered_time_earlier
        ):
            context.goal_progress["phone_shared"] = True
            context.trust_score = min(1.0, context.trust_score + 0.35)
            return (
                f"Yes, that works for me. You can call me on {SIMULATED_LANDLORD_PHONE} "
                "this evening to arrange the viewing."
            )

        # Proactive viewing-time offer once the agent has answered
        # screening and requested a viewing, without having asked for
        # the phone first. One-shot per trial.
        if (
            not asked_for_phone
            and context.current_turn >= 2
            and requested_viewing
            and (answered_move or answered_employment)
            and not offered_time_earlier
        ):
            context.goal_progress["offered_time"] = True
            return "How about Saturday at 2pm?"

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
