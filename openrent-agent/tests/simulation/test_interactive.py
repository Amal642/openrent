from types import SimpleNamespace

from simulation.interactive import (
    get_interactive_session,
    start_interactive_session,
    submit_interactive_message,
)


def _fake_completion_create(**kwargs):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "I work full-time and can move next week. "
                        "Could you share your phone number please?"
                    )
                )
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=14,
            total_tokens=26,
        ),
    )


def test_interactive_session_persists_actor_and_agent_turns(monkeypatch, tmp_path):
    from app.ai import replies
    from simulation.sessions import store as session_store_module
    from simulation import interactive as interactive_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(interactive_module, "JSONSessionStore", TmpStore)

    started = start_interactive_session()
    updated = submit_interactive_message(
        started["session_id"],
        "Are you working currently? My number is 07123 456 789.",
    )

    assert updated["mode"] == "interactive"
    assert updated["start_mode"] == "agent_starts"
    assert updated["initial_message_source"] == "fixture"
    assert updated["transcript"][0]["speaker"] == "agent"
    assert updated["transcript"][1]["speaker"] == "actor"
    assert updated["transcript"][2]["speaker"] == "agent"
    assert updated["runtime_context"]["current_turn"] == 1
    assert updated["runtime_context"]["extracted_entities"]["phone"] == "07123456789"
    assert updated["runtime_context"]["metrics"]["interactive_turns"] == 1
    assert any(
        event["event_type"] == "ACTOR_RESPONDED" and "working currently" in event["payload"]["message"]
        for event in updated["events"]
    )
    assert any(event["event_type"] == "REPLY_GENERATED" for event in updated["events"])
    assert (tmp_path / f"{started['session_id']}.json").exists()


def test_get_interactive_session_reloads_saved_artifact(monkeypatch, tmp_path):
    from simulation.sessions import store as session_store_module
    from simulation import interactive as interactive_module

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(interactive_module, "JSONSessionStore", TmpStore)

    started = start_interactive_session()
    loaded = get_interactive_session(started["session_id"])

    assert loaded["session_id"] == started["session_id"]
    assert loaded["mode"] == "interactive"
    assert loaded["start_mode"] == "agent_starts"


def test_interactive_agent_starts_emits_initial_template(monkeypatch, tmp_path):
    from simulation.sessions import store as session_store_module
    from simulation import interactive as interactive_module

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(interactive_module, "JSONSessionStore", TmpStore)

    started = start_interactive_session(
        start_mode="agent_starts",
        initial_message_source="manual",
        initial_message="Hello from the initial outreach template.",
    )

    assert started["start_mode"] == "agent_starts"
    assert started["initial_message_source"] == "manual"
    assert started["initial_message"] == "Hello from the initial outreach template."
    assert started["transcript"][0]["speaker"] == "agent"
    assert started["transcript"][0]["source_event"] == "AGENT_INITIAL_MESSAGE_SENT"
    assert started["runtime_context"]["memory"]["initial_agent_message"] == (
        "Hello from the initial outreach template."
    )
