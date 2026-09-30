import re
from pathlib import Path
from types import SimpleNamespace

from simulation.engine.runner import run_simulation
from simulation.sessions.event_models import SimulationEvent
from simulation.sessions.transcript import project_transcript


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


def _patch_deterministic_runtime(monkeypatch, tmp_path):
    from app.ai import replies
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion_create)
    monkeypatch.setattr(
        "simulation.engine.runner.uuid.uuid4",
        lambda: "session-fixed",
    )
    monkeypatch.setattr(
        "simulation.engine.orchestrator.build_event_timestamp",
        lambda: "2026-01-01T00:00:00+00:00",
    )

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(
        "simulation.engine.orchestrator.JSONSessionStore",
        TmpStore,
    )


def test_transcript_is_derived_from_events_only():
    events = [
        SimulationEvent(
            event_type="SCENARIO_STARTED",
            turn_index=0,
            timestamp="2026-01-01T00:00:00+00:00",
            payload={"scenario_id": "s1"},
        ),
        SimulationEvent(
            event_type="ACTOR_RESPONDED",
            turn_index=0,
            timestamp="2026-01-01T00:00:00+00:00",
            payload={"speaker": "Mr Patel", "message": "Question from actor"},
        ),
        SimulationEvent(
            event_type="MEMORY_UPDATED",
            turn_index=1,
            timestamp="2026-01-01T00:00:01+00:00",
            payload={"memory": {"hidden": "state"}},
        ),
        SimulationEvent(
            event_type="REPLY_GENERATED",
            turn_index=1,
            timestamp="2026-01-01T00:00:01+00:00",
            payload={"reply_text": "Agent reply"},
        ),
    ]

    transcript = project_transcript(events)

    assert [turn.speaker for turn in transcript] == ["actor", "agent"]
    assert [turn.message for turn in transcript] == [
        "Question from actor",
        "Agent reply",
    ]


# Measured wall-clock durations: real elapsed time, never deterministic. They
# were 0 ms on an idle machine, so the equality below passed only by luck and
# failed whenever the box was busy (any commit, 2026-09-30).
_WALL_CLOCK_KEYS = {
    "latency_ms",
    "run_duration_ms",
    "evaluation_timing_ms",
    "generation_latency_ms",
}


def _without_wall_clock(value):
    if isinstance(value, dict):
        return {
            k: _without_wall_clock(v)
            for k, v in value.items()
            if k not in _WALL_CLOCK_KEYS
        }
    if isinstance(value, list):
        return [_without_wall_clock(v) for v in value]
    if isinstance(value, str):
        # The rendered replay text embeds the same durations.
        return re.sub(
            r"(['\"](?:%s)['\"]:\s*)\d+" % "|".join(sorted(_WALL_CLOCK_KEYS)),
            r"\g<1>0",
            value,
        )
    return value


def test_same_seed_gives_same_output(monkeypatch, tmp_path):
    _patch_deterministic_runtime(monkeypatch, tmp_path)
    first = run_simulation(deterministic_seed=42, max_turns=1).to_dict()
    second = run_simulation(deterministic_seed=42, max_turns=1).to_dict()

    assert _without_wall_clock(first) == _without_wall_clock(second)


def test_memory_does_not_leak_into_transcript(monkeypatch, tmp_path):
    _patch_deterministic_runtime(monkeypatch, tmp_path)
    session = run_simulation(deterministic_seed=42, max_turns=1)

    session.runtime_context["memory"]["private_note"] = "screen tenant quietly"
    transcript_messages = [turn.message for turn in session.transcript]

    assert all("private_note" not in message for message in transcript_messages)
    assert all(
        "screen tenant quietly" not in message
        for message in transcript_messages
    )


def test_simulation_code_does_not_import_openrent_or_browser():
    simulation_root = Path(__file__).resolve().parents[2] / "simulation"
    forbidden_imports = ("app.openrent", "app.browser")

    for path in simulation_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert all(forbidden not in content for forbidden in forbidden_imports), path
