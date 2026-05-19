from simulation.engine.runtime_context import RuntimeContext
from simulation.sessions.models import AgentResponse


def test_runtime_context_snapshot_keeps_memory_separate_from_agent_response():
    context = RuntimeContext(session_id="session-1")
    context.memory["screening"] = "pending"
    context.last_agent_response = AgentResponse(
        reply_text="Test reply",
        raw_prompt="Prompt",
        raw_completion="Test reply",
        model="fake-model",
        temperature=0.0,
        valid=True,
        error=None,
    )
    snapshot = context.snapshot()

    assert snapshot["memory"] == {"screening": "pending"}
    assert snapshot["last_agent_response"]["reply_text"] == "Test reply"

