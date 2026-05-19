from simulation.replay.formatter import format_replay
from simulation.sessions.event_models import SimulationEvent
from simulation.sessions.models import EvaluationResult
from simulation.sessions.transcript import project_transcript


def test_projection_ignores_non_transcript_events():
    events = [
        SimulationEvent(
            event_type="SCENARIO_STARTED",
            turn_index=0,
            timestamp="2026-01-01T00:00:00+00:00",
            payload={"scenario_id": "screening-before-phone"},
        ),
        SimulationEvent(
            event_type="ACTOR_RESPONDED",
            turn_index=0,
            timestamp="2026-01-01T00:00:00+00:00",
            payload={"speaker": "Mr Patel", "message": "Are you working?"},
        ),
        SimulationEvent(
            event_type="PHONE_DETECTED",
            turn_index=1,
            timestamp="2026-01-01T00:00:01+00:00",
            payload={"phone": "07123456789"},
        ),
    ]

    transcript = project_transcript(events)

    assert len(transcript) == 1
    assert transcript[0].speaker == "actor"


def test_projection_includes_agent_initial_message_events():
    events = [
        SimulationEvent(
            event_type="AGENT_INITIAL_MESSAGE_SENT",
            turn_index=0,
            timestamp="2026-01-01T00:00:00+00:00",
            payload={"message": "Hello from the tenant template."},
        ),
        SimulationEvent(
            event_type="ACTOR_RESPONDED",
            turn_index=1,
            timestamp="2026-01-01T00:00:01+00:00",
            payload={"speaker": "Mr Patel", "message": "Tell me more about yourself."},
        ),
    ]

    transcript = project_transcript(events)

    assert [turn.speaker for turn in transcript] == ["agent", "actor"]
    assert transcript[0].source_event == "AGENT_INITIAL_MESSAGE_SENT"


def test_replay_formatter_contains_score_and_event_names():
    events = [
        SimulationEvent(
            event_type="ACTOR_RESPONDED",
            turn_index=0,
            timestamp="2026-01-01T00:00:00+00:00",
            payload={"speaker": "Mr Patel", "message": "Are you working?"},
        )
    ]
    transcript = project_transcript(events)
    evaluation = EvaluationResult(
        evaluator_id="heuristic-v1",
        score=0.8,
        passed=True,
        dimension_scores={"answered_actor_question": 1.0},
        failure_types=[],
        rationale="ok",
        evaluation_timing_ms=0,
    )

    replay = format_replay(events, transcript, evaluation)

    assert "score=0.8" in replay
    assert "[ACTOR_RESPONDED]" in replay
