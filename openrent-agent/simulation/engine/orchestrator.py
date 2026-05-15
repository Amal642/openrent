import time

from simulation.engine.session_manager import (
    emit_event,
    finalize_session,
    generate_agent_reply,
    update_context_from_agent_message,
    update_context_from_actor_message,
)
from simulation.observability.metrics import MetricsCollector
from simulation.observability.tracing import build_event_timestamp
from simulation.sessions.store import JSONSessionStore


class SimulationOrchestrator:
    def __init__(
        self,
        actor,
        policy,
        scenario,
        runtime_context,
        event_bus,
        initial_message_provider=None,
    ):
        self.actor = actor
        self.policy = policy
        self.scenario = scenario
        self.context = runtime_context
        self.event_bus = event_bus
        self.metrics = MetricsCollector(runtime_context.metrics)
        self.initial_message_provider = initial_message_provider

    def _emit_actor_message(self, actor_message: str):
        self._emit(
            "ACTOR_RESPONDED",
            {
                "speaker": self.actor.profile.display_name,
                "message": actor_message,
            },
        )
        memory_payload = update_context_from_actor_message(
            self.context,
            actor_message,
        )
        self._emit("MEMORY_UPDATED", memory_payload)
        if memory_payload.get("phone_detected"):
            self._emit(
                "PHONE_DETECTED",
                {"phone": memory_payload["phone_detected"]},
            )

    def _emit_initial_agent_message(self, initial_message: str):
        self._emit(
            "AGENT_INITIAL_MESSAGE_SENT",
            {
                "message": initial_message,
                "source": getattr(self.initial_message_provider, "source", "unknown"),
            },
        )
        self._emit(
            "MEMORY_UPDATED",
            update_context_from_agent_message(
                self.context,
                initial_message,
                key="initial_agent_message",
            ),
        )

    def _emit(self, event_type: str, payload: dict):
        emit_event(self.event_bus, self.context, event_type, payload)

    def run(self):
        session_started = time.perf_counter()
        self._emit(
            "SCENARIO_STARTED",
            {
                "scenario_id": self.scenario.scenario_id,
                "policy_id": self.policy.policy_id,
                "actor_id": self.actor.profile.actor_id,
                "start_mode": self.scenario.start_mode,
            },
        )

        if self.scenario.start_mode == "agent_starts":
            initial_message = self.initial_message_provider.get_message()
            self._emit_initial_agent_message(initial_message)
            self.context.current_turn = 1
            actor_message = self.actor.respond(self.context, initial_message)
            self._emit_actor_message(actor_message)
        else:
            actor_message = self.actor.initial_message()
            self._emit_actor_message(actor_message)

        for turn_index in range(1, self.scenario.max_turns + 1):
            self.context.current_turn = turn_index
            agent_response = generate_agent_reply(
                self.policy,
                self.context,
                self.event_bus,
                self.metrics,
            )

            if agent_response.reply_text:
                actor_response = self.actor.respond(
                    self.context,
                    agent_response.reply_text,
                )
                self._emit(
                    "ACTOR_RESPONDED",
                    {
                        "speaker": self.actor.profile.display_name,
                        "message": actor_response,
                    },
                )
                memory_payload = update_context_from_actor_message(
                    self.context,
                    actor_response,
                )
                self._emit("MEMORY_UPDATED", memory_payload)
                if memory_payload.get("phone_detected"):
                    self._emit(
                        "PHONE_DETECTED",
                        {"phone": memory_payload["phone_detected"]},
                    )
            break

        return finalize_session(
            mode="simulation",
            actor=self.actor,
            policy=self.policy,
            scenario=self.scenario,
            context=self.context,
            event_bus=self.event_bus,
            metrics=self.metrics,
            session_started=session_started,
            store=JSONSessionStore(),
        )
