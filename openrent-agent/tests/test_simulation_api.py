from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.main import app


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


def test_simulation_run_endpoint_returns_full_artifact(monkeypatch, tmp_path):
    from app.ai import replies
    from simulation.engine import orchestrator as orchestrator_module
    from simulation import lab as simulation_lab
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(simulation_lab, "JSONSessionStore", TmpStore)
    monkeypatch.setattr(orchestrator_module, "JSONSessionStore", TmpStore)

    client = TestClient(app)
    response = client.post(
        "/simulation/run",
        json={
            "seed": 7,
            "max_turns": 1,
            "scenario_id": "screening-before-phone",
            "actor_id": "landlord-default",
            "policy_id": "minimal-policy-v1",
            "start_mode": "actor_starts",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["scenario_id"] == "reply-after-landlord-question"
    assert payload["policy_id"] == "minimal-policy-v1"
    assert payload["evaluation"]["passed"] is True


def test_simulation_run_endpoint_supports_agent_starts(monkeypatch, tmp_path):
    from app.ai import replies
    from simulation.engine import orchestrator as orchestrator_module
    from simulation import lab as simulation_lab
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(simulation_lab, "JSONSessionStore", TmpStore)
    monkeypatch.setattr(orchestrator_module, "JSONSessionStore", TmpStore)

    client = TestClient(app)
    response = client.post(
        "/simulation/run",
        json={
            "seed": 7,
            "max_turns": 1,
            "start_mode": "agent_starts",
            "initial_message_source": "manual",
            "initial_message": "Hi from the initial outreach template.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_mode"] == "agent_starts"
    assert payload["initial_message_source"] == "manual"
    assert payload["transcript"][0]["speaker"] == "agent"


def test_simulation_session_listing_and_detail_endpoints(monkeypatch, tmp_path):
    from app.ai import replies
    from simulation.engine import orchestrator as orchestrator_module
    from simulation import lab as simulation_lab
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(simulation_lab, "JSONSessionStore", TmpStore)
    monkeypatch.setattr(orchestrator_module, "JSONSessionStore", TmpStore)

    client = TestClient(app)
    run_response = client.post("/simulation/run", json={"seed": 11, "max_turns": 1})
    session_id = run_response.json()["session_id"]

    list_response = client.get("/simulation/sessions")
    assert list_response.status_code == 200
    sessions = list_response.json()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["score"] == 1.0
    assert sessions[0]["run_duration_ms"] is not None
    assert sessions[0]["created_at"]

    detail_response = client.get(f"/simulation/sessions/{session_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["session_id"] == session_id
    assert detail["transcript"][0]["speaker"] == "agent"
    assert detail["start_mode"] == "agent_starts"


def test_simulation_results_endpoint_returns_evaluation_and_observability(
    monkeypatch,
    tmp_path,
):
    from app.ai import replies
    from simulation.engine import orchestrator as orchestrator_module
    from simulation import lab as simulation_lab
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(simulation_lab, "JSONSessionStore", TmpStore)
    monkeypatch.setattr(orchestrator_module, "JSONSessionStore", TmpStore)

    client = TestClient(app)
    run_response = client.post("/simulation/run", json={"seed": 21, "max_turns": 1})
    session_id = run_response.json()["session_id"]

    response = client.get(f"/simulation/results/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["evaluation"]["passed"] is True
    assert payload["failure_types"] == []
    assert payload["observability"]["run_duration_ms"] is not None


def test_interactive_endpoints_create_fetch_and_update_session(
    monkeypatch,
    tmp_path,
):
    from app.ai import replies
    from simulation import interactive as interactive_module
    from simulation import lab as simulation_lab
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion_create)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(simulation_lab, "JSONSessionStore", TmpStore)
    monkeypatch.setattr(interactive_module, "JSONSessionStore", TmpStore)

    client = TestClient(app)
    start_response = client.post(
        "/simulation/interactive/start",
        json={"scenario_id": "reply-after-landlord-question", "start_mode": "actor_starts"},
    )

    assert start_response.status_code == 200
    session_id = start_response.json()["session_id"]

    detail_response = client.get(f"/simulation/interactive/{session_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["mode"] == "interactive"

    message_response = client.post(
        f"/simulation/interactive/{session_id}/message",
        json={"message": "Are you working currently?"},
    )
    assert message_response.status_code == 200
    updated = message_response.json()
    assert updated["session_id"] == session_id
    assert updated["transcript"][0]["speaker"] == "actor"
    assert updated["transcript"][1]["speaker"] == "agent"

    results_response = client.get(f"/simulation/results/{session_id}")
    assert results_response.status_code == 200
    assert results_response.json()["session_id"] == session_id


def test_interactive_start_endpoint_supports_agent_starts(
    monkeypatch,
    tmp_path,
):
    from simulation import interactive as interactive_module
    from simulation.sessions import store as session_store_module

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(interactive_module, "JSONSessionStore", TmpStore)

    client = TestClient(app)
    start_response = client.post(
        "/simulation/interactive/start",
        json={
            "start_mode": "agent_starts",
            "initial_message_source": "manual",
            "initial_message": "Hello from the initial template.",
        },
    )

    assert start_response.status_code == 200
    session_id = start_response.json()["session_id"]

    detail_response = client.get(f"/simulation/interactive/{session_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["start_mode"] == "agent_starts"
    assert detail["initial_message_source"] == "manual"
    assert detail["transcript"][0]["speaker"] == "agent"
