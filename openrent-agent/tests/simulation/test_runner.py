from types import SimpleNamespace

from simulation.engine.runner import run_simulation


def test_runner_creates_json_backed_session(monkeypatch, tmp_path):
    def fake_completion_create(**kwargs):
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

    from app.ai import replies
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(
        "simulation.engine.orchestrator.JSONSessionStore",
        TmpStore,
    )

    session = run_simulation(deterministic_seed=42, max_turns=1)

    assert session.evaluation.passed is True
    assert session.start_mode == "agent_starts"
    assert session.initial_message_source == "fixture"
    assert session.transcript[0].speaker == "agent"
    assert session.transcript[0].source_event == "AGENT_INITIAL_MESSAGE_SENT"
    assert session.transcript[1].speaker == "actor"
    assert session.transcript[2].speaker == "agent"
    assert (tmp_path / f"{session.session_id}.json").exists()


def test_runner_supports_agent_starts_template_flow(monkeypatch, tmp_path):
    def fake_completion_create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "Thanks, I work full-time and can move next week. "
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

    from app.ai import replies
    from simulation import lab as simulation_lab
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr("simulation.engine.orchestrator.JSONSessionStore", TmpStore)

    artifact = simulation_lab.run_simulation_session(
        seed=42,
        max_turns=1,
        start_mode="agent_starts",
        initial_message_source="manual",
        initial_message="Hi, I'm Mary from the real outreach flow.",
    )

    assert artifact["start_mode"] == "agent_starts"
    assert artifact["initial_message_source"] == "manual"
    assert artifact["initial_message"] == "Hi, I'm Mary from the real outreach flow."
    assert artifact["transcript"][0]["speaker"] == "agent"
    assert artifact["transcript"][0]["source_event"] == "AGENT_INITIAL_MESSAGE_SENT"
    assert artifact["events"][1]["event_type"] == "AGENT_INITIAL_MESSAGE_SENT"
