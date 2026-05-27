"""Tests for the pilot-matrix package + CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from simulation.engine.hippo_hooks import HippoSession, HippoSessionMeta
from simulation.pilot.aggregate import aggregate_trials
from simulation.pilot.fixtures import (
    PilotFixture,
    PilotFixtureError,
    PilotScenario,
    load_pilot_fixture,
    parse_pilot_fixture,
)
from simulation.pilot.matrix import (
    MatrixConfig,
    MatrixResult,
    run_pilot_matrix,
)


# ----------------------------------------------------------------------
# Fixture loader


class TestFixtureLoader:
    def test_loads_locked_k10_fixture(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "simulation"
            / "pilot"
            / "scenarios.k10.json"
        )
        fixture = load_pilot_fixture(path)
        assert fixture.fixture_id == "openrent-pilot-k10-v1"
        assert fixture.k == 10
        keys = [s.scenario_key for s in fixture.scenarios]
        assert len(keys) == len(set(keys)), "scenario_key must be unique per row"
        for s in fixture.scenarios:
            assert s.scenario_id in {
                "outreach-screening-before-phone",
                "outreach-phone-request",
                "reply-after-landlord-question",
            }
            assert s.policy_id in {
                "production-policy-v1",
                "minimal-policy-v1",
                "aggressive-followup-v1",
            }
            assert s.start_mode in {"agent_starts", "actor_starts"}
            assert s.max_turns >= 1

    def test_loads_failed3_probe_fixture(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "simulation"
            / "pilot"
            / "scenarios.failed3.json"
        )
        fixture = load_pilot_fixture(path)
        assert fixture.fixture_id == "openrent-pilot-failed3-v1"
        assert fixture.k == 3
        assert {s.scenario_key for s in fixture.scenarios} == {
            "s02-screening-actor-starts-prod",
            "s04-phone-request-actor-starts-prod",
            "s05-reply-actor-starts-prod",
        }

    def test_rejects_empty_scenarios(self):
        with pytest.raises(PilotFixtureError, match="non-empty list"):
            parse_pilot_fixture({
                "fixture_id": "x",
                "description": "y",
                "scenarios": [],
            })

    def test_rejects_duplicate_scenario_key(self):
        with pytest.raises(PilotFixtureError, match="duplicate scenario_key"):
            parse_pilot_fixture({
                "fixture_id": "x",
                "description": "y",
                "scenarios": [
                    {
                        "scenario_key": "dup",
                        "scenario_id": "outreach-screening-before-phone",
                        "policy_id": "production-policy-v1",
                        "start_mode": "agent_starts",
                        "max_turns": 1,
                    },
                    {
                        "scenario_key": "dup",
                        "scenario_id": "outreach-phone-request",
                        "policy_id": "production-policy-v1",
                        "start_mode": "agent_starts",
                        "max_turns": 1,
                    },
                ],
            })

    def test_rejects_invalid_start_mode(self):
        with pytest.raises(PilotFixtureError, match="start_mode"):
            parse_pilot_fixture({
                "fixture_id": "x",
                "description": "y",
                "scenarios": [
                    {
                        "scenario_key": "s1",
                        "scenario_id": "outreach-screening-before-phone",
                        "policy_id": "production-policy-v1",
                        "start_mode": "sideways",
                        "max_turns": 1,
                    }
                ],
            })

    def test_rejects_non_positive_max_turns(self):
        with pytest.raises(PilotFixtureError, match="max_turns"):
            parse_pilot_fixture({
                "fixture_id": "x",
                "description": "y",
                "scenarios": [
                    {
                        "scenario_key": "s1",
                        "scenario_id": "outreach-screening-before-phone",
                        "policy_id": "production-policy-v1",
                        "start_mode": "agent_starts",
                        "max_turns": 0,
                    }
                ],
            })

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PilotFixtureError, match="not found"):
            load_pilot_fixture(tmp_path / "does-not-exist.json")


# ----------------------------------------------------------------------
# Aggregator


class TestAggregator:
    def test_rates_match_expected_for_simple_two_condition_matrix(self):
        trials = [
            # memory-off / s01: 1/2 pass
            {
                "condition": "memory-off",
                "scenario_key": "s01",
                "passed": True,
                "score": 0.9,
                "phone_captured": True,
                "viewing_booked": False,
                "current_state": "phone_captured",
                "failure_types": [],
                "prompt_tokens": 100,
                "generation_latency_ms": 200,
                "hippo_recall_count": 0,
                "hippo_ingest_count": 0,
            },
            {
                "condition": "memory-off",
                "scenario_key": "s01",
                "passed": False,
                "score": 0.3,
                "phone_captured": False,
                "viewing_booked": False,
                "current_state": "stalled",
                "failure_types": ["FAILED_PHONE_CAPTURE"],
                "prompt_tokens": 110,
                "generation_latency_ms": 210,
                "hippo_recall_count": 0,
                "hippo_ingest_count": 0,
            },
            # memory-on / s01: 2/2 pass
            {
                "condition": "memory-on",
                "scenario_key": "s01",
                "passed": True,
                "score": 0.95,
                "phone_captured": True,
                "viewing_booked": True,
                "current_state": "phone_captured",
                "failure_types": [],
                "prompt_tokens": 130,
                "generation_latency_ms": 220,
                "hippo_recall_count": 1,
                "hippo_ingest_count": 1,
            },
            {
                "condition": "memory-on",
                "scenario_key": "s01",
                "passed": True,
                "score": 0.9,
                "phone_captured": True,
                "viewing_booked": False,
                "current_state": "phone_captured",
                "failure_types": [],
                "prompt_tokens": 140,
                "generation_latency_ms": 215,
                "hippo_recall_count": 1,
                "hippo_ingest_count": 1,
            },
        ]
        agg = aggregate_trials(trials)
        assert agg["trial_count"] == 4
        assert agg["conditions"]["memory-off"]["passed_rate"] == 0.5
        assert agg["conditions"]["memory-on"]["passed_rate"] == 1.0
        assert agg["conditions"]["memory-on"]["phone_captured_rate"] == 1.0
        assert agg["conditions"]["memory-off"]["phone_captured_rate"] == 0.5
        assert agg["conditions"]["memory-on"]["hippo_recall_mean"] == 1.0
        assert agg["scenarios"]["s01"]["memory-on"]["n"] == 2
        assert (
            agg["failure_types_by_condition"]["memory-off"]["FAILED_PHONE_CAPTURE"]
            == 1
        )
        assert (
            agg["current_state_by_condition"]["memory-off"]["phone_captured"] == 1
        )
        assert (
            agg["current_state_by_condition"]["memory-off"]["stalled"] == 1
        )


# ----------------------------------------------------------------------
# Matrix end-to-end with injected runner + hippo factory


@dataclass
class _FakeEvent:
    event_type: str
    turn_index: int
    timestamp: str
    payload: dict[str, Any]

    def to_dict(self):
        return {
            "event_type": self.event_type,
            "turn_index": self.turn_index,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


def _fake_session_dict(
    *,
    seed: int,
    passed: bool,
    current_state: str,
    hippo_memory: str,
    failure_types: list[str] | None = None,
    recall_emitted: bool = False,
    ingest_emitted: bool = False,
    ingest_cells: int = 0,
    outcome_label: str | None = None,
):
    events: list[dict[str, Any]] = []
    if recall_emitted:
        events.append(
            {
                "event_type": "HIPPO_RECALL",
                "turn_index": 1,
                "timestamp": "2026-01-01T00:00:00Z",
                "payload": {
                    "trace_id": "trace-x",
                    "note_count": 1,
                    "notes_applied": True,
                },
            }
        )
    if ingest_emitted:
        events.append(
            {
                "event_type": "HIPPO_INGEST",
                "turn_index": 1,
                "timestamp": "2026-01-01T00:00:01Z",
                "payload": {
                    "cell_count": ingest_cells,
                    "outcome_label": outcome_label,
                    "outcome_success": passed,
                    "warning": None,
                },
            }
        )
    return {
        "session_id": f"fake-{seed}",
        "events": events,
        "evaluation": {
            "score": 0.9 if passed else 0.4,
            "passed": passed,
            "failure_types": failure_types or [],
            "dimension_scores": {"captured_phone": 1.0 if passed else 0.0},
            "conversation_state": {"current_state": current_state},
            "rationale": "fake",
            "evaluator_id": "fake",
            "evaluation_timing_ms": 1,
        },
        "observability": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "generation_latency_ms": 200,
            "evaluation_timing_ms": 5,
            "run_duration_ms": 250,
        },
        "runtime_context": {"flags": {"hippo_memory": hippo_memory}},
        "transcript": [],
    }


def _make_fixture() -> PilotFixture:
    scenarios = (
        PilotScenario(
            scenario_key="s01",
            scenario_id="outreach-screening-before-phone",
            policy_id="production-policy-v1",
            start_mode="agent_starts",
            max_turns=1,
            thread_id="thread-s01",
        ),
        PilotScenario(
            scenario_key="s02",
            scenario_id="outreach-phone-request",
            policy_id="production-policy-v1",
            start_mode="agent_starts",
            max_turns=1,
            thread_id="thread-s02",
        ),
    )
    return PilotFixture(
        fixture_id="test-k2",
        description="test fixture",
        scenarios=scenarios,
    )


class _FakeHippoClient:
    def __init__(self):
        self.closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def close(self):
        self.closed = True

    def recall_for_reply(self, **kwargs):
        self.calls.append(("recall", dict(kwargs)))
        return {"traceId": "trace", "query": "Q", "notes": [], "warnings": []}

    def ingest_thread(self, thread):
        self.calls.append(("ingest", dict(thread)))
        return ["cell-1", "cell-2"]

    def forget_thread(self, thread_id):
        self.calls.append(("forget", {"thread_id": thread_id}))
        return {"forgotten": 0, "cellIds": []}


class TestMatrixRunner:
    def test_memory_off_only_no_hippo_factory_invocations(self, tmp_path):
        fixture = _make_fixture()
        runner_calls: list[dict[str, Any]] = []

        def session_runner(**kwargs):
            runner_calls.append(kwargs)
            assert kwargs.get("hippo") is None
            return _fake_session_dict(
                seed=kwargs["seed"],
                passed=True,
                current_state="phone_captured",
                hippo_memory="off",
            )

        def hippo_factory_must_not_run(**kwargs):
            raise AssertionError(
                "hippo_factory should not be called when memory is off"
            )

        config = MatrixConfig(
            fixture=fixture,
            n_trials=3,
            seed_base=100,
            memory=("memory-off",),
            output_dir=tmp_path,
        )
        result = run_pilot_matrix(
            config,
            session_runner=session_runner,
            hippo_factory=hippo_factory_must_not_run,
        )
        assert len(result.trials) == 6  # K=2 x N=3
        assert all(t["condition"] == "memory-off" for t in result.trials)
        assert all(t["hippo_recall_count"] == 0 for t in result.trials)
        assert all(t["hippo_ingest_count"] == 0 for t in result.trials)
        agg = result.aggregates
        assert agg["conditions"]["memory-off"]["passed_rate"] == 1.0
        # Output artefacts written.
        assert (tmp_path / "trials.jsonl").is_file()
        assert (tmp_path / "per_scenario.json").is_file()
        assert (tmp_path / "manifest.json").is_file()
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["k"] == 2
        assert manifest["n_trials"] == 3
        assert manifest["trial_count"] == 6
        assert manifest["trace_samples"] is False
        assert manifest["hippo_k_evidence"] == 8

    def test_memory_on_shared_regime_reuses_one_client(self):
        fixture = _make_fixture()
        client = _FakeHippoClient()
        factory_invocations: list[str] = []

        def session_runner(**kwargs):
            hippo = kwargs.get("hippo")
            assert hippo is not None, "memory-on must pass a HippoSession"
            return _fake_session_dict(
                seed=kwargs["seed"],
                passed=True,
                current_state="phone_captured",
                hippo_memory="on",
                recall_emitted=True,
                ingest_emitted=True,
                ingest_cells=3,
                outcome_label="phone_captured",
            )

        def hippo_factory(*, config, scope_label):
            factory_invocations.append(scope_label)
            return HippoSession(
                client=client,
                meta=HippoSessionMeta(thread_id="placeholder"),
            )

        config = MatrixConfig(
            fixture=fixture,
            n_trials=2,
            seed_base=100,
            memory=("memory-on",),
            memory_regime="shared",
        )
        result = run_pilot_matrix(
            config,
            session_runner=session_runner,
            hippo_factory=hippo_factory,
        )
        assert factory_invocations == ["shared"], (
            "shared regime must call the factory exactly once per condition"
        )
        assert client.closed is True
        assert len(result.trials) == 4  # K=2 x N=2
        agg = result.aggregates
        assert agg["conditions"]["memory-on"]["hippo_recall_mean"] == 1.0
        assert agg["conditions"]["memory-on"]["hippo_ingest_mean"] == 1.0

    def test_hippo_snap_parent_dir_exists_before_hippo_factory(self, tmp_path):
        """F3 regression: the snap's parent directory must exist before
        the MCP child opens.

        Discovered when a1.2's snap was missing despite --hippo-snap.
        The MCP server's close() calls atomicWriteJson(snap_path, ...)
        which silently fails if the parent directory doesn't yet exist.
        The fix in matrix.py creates the parent at the top of
        run_pilot_matrix, before any MCP session is opened.

        This test inverts the dependency: at the moment hippo_factory is
        called, we assert the snap's parent dir exists. If the fix is
        reverted, this assertion fires before any trial runs.
        """

        fixture = _make_fixture()
        snap_path = tmp_path / "deep" / "nested" / "dir" / "hippo.snap.json"

        def session_runner(**kwargs):
            return _fake_session_dict(
                seed=kwargs["seed"],
                passed=False,
                current_state="viewing_negotiation",
                hippo_memory="on",
                recall_emitted=True,
                ingest_emitted=True,
                ingest_cells=2,
            )

        observed_at_factory_call: dict[str, bool] = {}

        def hippo_factory(*, config, scope_label):
            observed_at_factory_call["parent_exists"] = snap_path.parent.is_dir()
            return HippoSession(
                client=_FakeHippoClient(),
                meta=HippoSessionMeta(thread_id="placeholder"),
            )

        config = MatrixConfig(
            fixture=fixture,
            n_trials=1,
            seed_base=100,
            memory=("memory-on",),
            memory_regime="shared",
            hippo_snap=str(snap_path),
        )
        run_pilot_matrix(
            config,
            session_runner=session_runner,
            hippo_factory=hippo_factory,
        )
        assert observed_at_factory_call.get("parent_exists") is True, (
            "snap's parent dir must already exist when hippo_factory is called; "
            "otherwise the MCP server's atomicWriteJson at close() will fail "
            "silently and the snap will never land on disk."
        )

    def test_hippo_snap_memory_sentinel_does_not_create_directory(self, tmp_path):
        """`:memory:` sentinel must NOT trigger parent-dir creation."""

        fixture = _make_fixture()

        def session_runner(**kwargs):
            return _fake_session_dict(
                seed=kwargs["seed"],
                passed=False,
                current_state="viewing_negotiation",
                hippo_memory="on",
                recall_emitted=True,
                ingest_emitted=True,
                ingest_cells=2,
            )

        def hippo_factory(*, config, scope_label):
            return HippoSession(
                client=_FakeHippoClient(),
                meta=HippoSessionMeta(thread_id="placeholder"),
            )

        config = MatrixConfig(
            fixture=fixture,
            n_trials=1,
            seed_base=100,
            memory=("memory-on",),
            memory_regime="shared",
            hippo_snap=":memory:",
        )
        # Should not raise, should not create any path-like directory.
        run_pilot_matrix(
            config,
            session_runner=session_runner,
            hippo_factory=hippo_factory,
        )
        assert not (tmp_path / ":memory:").exists()

    def test_trace_samples_sidecar_records_compact_recall_and_reply(self, tmp_path):
        fixture = _make_fixture()

        def session_runner(**kwargs):
            session = _fake_session_dict(
                seed=kwargs["seed"],
                passed=False,
                current_state="viewing_negotiation",
                hippo_memory="on",
                recall_emitted=True,
                ingest_emitted=True,
                ingest_cells=4,
            )
            session["events"].append({
                "event_type": "REPLY_GENERATED",
                "turn_index": 1,
                "timestamp": "2026-01-01T00:00:02Z",
                "payload": {
                    "reply_text": "I work full-time. When can I view it?",
                    "raw_prompt": (
                        "Relevant prior outreach context for this lead "
                        "(from prior sessions / memory):\n- one useful note"
                        "\n\n---\n\nBase prompt"
                    ),
                },
            })
            session["events"][0]["payload"].update({
                "query": "Are you working?",
                "notes_block_chars": 17,
                "notes_preview": ["one useful note"],
                "evidence_sources": [{"source_id": "pilot-s02"}],
            })
            return session

        config = MatrixConfig(
            fixture=fixture,
            n_trials=1,
            seed_base=100,
            memory=("memory-on",),
            output_dir=tmp_path,
            trace_samples=True,
            hippo_k_evidence=2,
        )
        result = run_pilot_matrix(
            config,
            session_runner=session_runner,
            hippo_factory=lambda **_: HippoSession(
                client=_FakeHippoClient(),
                meta=HippoSessionMeta(thread_id="placeholder"),
            ),
        )

        assert len(result.trace_samples) == 2
        trace_path = tmp_path / "trace_samples.jsonl"
        assert trace_path.is_file()
        first = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
        assert first["recall"]["query"] == "Are you working?"
        assert first["recall"]["evidence_sources"] == [{"source_id": "pilot-s02"}]
        assert first["reply_text"] == "I work full-time. When can I view it?"
        assert first["memory_block_chars"] > 0
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["trace_samples"] is True
        assert manifest["hippo_k_evidence"] == 2

    def test_memory_on_per_trial_regime_spawns_one_client_per_trial(self):
        fixture = _make_fixture()
        clients: list[_FakeHippoClient] = []

        def session_runner(**kwargs):
            return _fake_session_dict(
                seed=kwargs["seed"],
                passed=True,
                current_state="phone_captured",
                hippo_memory="on",
                recall_emitted=True,
                ingest_emitted=True,
                ingest_cells=2,
                outcome_label="phone_captured",
            )

        def hippo_factory(*, config, scope_label):
            client = _FakeHippoClient()
            clients.append(client)
            return HippoSession(
                client=client,
                meta=HippoSessionMeta(thread_id="placeholder"),
            )

        config = MatrixConfig(
            fixture=fixture,
            n_trials=2,
            seed_base=100,
            memory=("memory-on",),
            memory_regime="per-trial",
        )
        result = run_pilot_matrix(
            config,
            session_runner=session_runner,
            hippo_factory=hippo_factory,
        )
        assert len(clients) == 4  # K=2 x N=2 trials each spawn a new client
        assert all(c.closed for c in clients)
        assert len(result.trials) == 4

    def test_both_conditions_produce_paired_aggregates(self):
        fixture = _make_fixture()

        def session_runner(**kwargs):
            wants_memory = kwargs.get("hippo") is not None
            # Memory on -> always pass; memory off -> alternate.
            seed = kwargs["seed"]
            if wants_memory:
                passed = True
                state = "phone_captured"
            else:
                passed = seed % 2 == 0
                state = "phone_captured" if passed else "stalled"
            return _fake_session_dict(
                seed=seed,
                passed=passed,
                current_state=state,
                hippo_memory="on" if wants_memory else "off",
                recall_emitted=wants_memory,
                ingest_emitted=wants_memory,
                ingest_cells=2 if wants_memory else 0,
                outcome_label=("phone_captured" if wants_memory and passed else None),
            )

        def hippo_factory(*, config, scope_label):
            return HippoSession(
                client=_FakeHippoClient(),
                meta=HippoSessionMeta(thread_id="placeholder"),
            )

        config = MatrixConfig(
            fixture=fixture,
            n_trials=4,
            seed_base=100,
            memory=("memory-off", "memory-on"),
        )
        result = run_pilot_matrix(
            config,
            session_runner=session_runner,
            hippo_factory=hippo_factory,
        )
        assert len(result.trials) == 16  # K=2 x N=4 x M=2
        off_rate = result.aggregates["conditions"]["memory-off"]["passed_rate"]
        on_rate = result.aggregates["conditions"]["memory-on"]["passed_rate"]
        assert on_rate == 1.0
        assert off_rate < on_rate
        # Memory-on records the outcome label on every trial.
        assert result.aggregates["conditions"]["memory-on"]["hippo_ingest_mean"] == 1.0

    def test_trial_runner_error_is_recorded_not_raised(self):
        fixture = _make_fixture()

        def boom_runner(**_kwargs):
            raise RuntimeError("synthetic explosion")

        config = MatrixConfig(
            fixture=fixture,
            n_trials=1,
            seed_base=100,
            memory=("memory-off",),
        )
        result = run_pilot_matrix(
            config,
            session_runner=boom_runner,
            hippo_factory=lambda **_: None,  # never called
        )
        assert len(result.trials) == 2
        for trial in result.trials:
            assert trial["passed"] is False
            assert "TRIAL_RUNNER_ERROR" in trial["failure_types"]
            assert trial["trial_error"] == "synthetic explosion"

    def test_invalid_memory_condition_raises(self):
        fixture = _make_fixture()
        with pytest.raises(ValueError, match="unknown condition"):
            run_pilot_matrix(
                MatrixConfig(
                    fixture=fixture,
                    n_trials=1,
                    seed_base=0,
                    memory=("memory-sometimes",),
                ),
                session_runner=lambda **_: {},
            )

    def test_invalid_regime_raises(self):
        fixture = _make_fixture()
        with pytest.raises(ValueError, match="memory_regime"):
            run_pilot_matrix(
                MatrixConfig(
                    fixture=fixture,
                    n_trials=1,
                    seed_base=0,
                    memory=("memory-off",),
                    memory_regime="invented",
                ),
                session_runner=lambda **_: {},
            )

    def test_invalid_hippo_k_evidence_raises(self):
        fixture = _make_fixture()
        with pytest.raises(ValueError, match="hippo_k_evidence"):
            run_pilot_matrix(
                MatrixConfig(
                    fixture=fixture,
                    n_trials=1,
                    seed_base=0,
                    memory=("memory-on",),
                    hippo_k_evidence=0,
                ),
                session_runner=lambda **_: {},
                hippo_factory=lambda **_: None,
            )

    def test_zero_n_trials_raises(self):
        fixture = _make_fixture()
        with pytest.raises(ValueError, match="n_trials"):
            run_pilot_matrix(
                MatrixConfig(
                    fixture=fixture,
                    n_trials=0,
                    seed_base=0,
                    memory=("memory-off",),
                ),
                session_runner=lambda **_: {},
            )


# ----------------------------------------------------------------------
# Real-engine integration (mocks only the LLM call)


class TestMatrixWithRealEngine:
    """Exercise the real `run_simulation_session` against the locked K=10
    fixture with N=2, mocking only the OpenAI call. Catches scenario_id /
    policy_id resolution issues that the fake-runner tests above don't."""

    def test_k10_n2_memory_off_completes_with_real_engine(
        self, monkeypatch, tmp_path
    ):
        from app.ai import replies
        from simulation.sessions import store as session_store_module

        def fake_completion(**_: Any):
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

        monkeypatch.setattr(replies, "_default_completion_create", fake_completion)

        class TmpStore(session_store_module.JSONSessionStore):
            def __init__(self):
                super().__init__(base_dir=str(tmp_path))

        monkeypatch.setattr(
            "simulation.engine.orchestrator.JSONSessionStore", TmpStore
        )

        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "simulation"
            / "pilot"
            / "scenarios.k10.json"
        )
        fixture = load_pilot_fixture(fixture_path)

        config = MatrixConfig(
            fixture=fixture,
            n_trials=2,
            seed_base=2000,
            memory=("memory-off",),
            output_dir=tmp_path / "out",
        )
        result = run_pilot_matrix(config)

        assert len(result.trials) == 20  # K=10 x N=2
        assert all(t["condition"] == "memory-off" for t in result.trials)
        # Every scenario_key from the fixture must appear in the trials.
        seen_keys = {t["scenario_key"] for t in result.trials}
        assert seen_keys == {s.scenario_key for s in fixture.scenarios}
        # No hippo events when memory is off.
        assert all(t["hippo_recall_count"] == 0 for t in result.trials)
        assert all(t["hippo_ingest_count"] == 0 for t in result.trials)
        # Manifest written and shape checks.
        manifest = json.loads(
            (tmp_path / "out" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["k"] == 10
        assert manifest["trial_count"] == 20
        assert manifest["memory_conditions"] == ["memory-off"]
        # Sanity: aggregator computed a numeric rate per condition.
        rate = result.aggregates["conditions"]["memory-off"]["passed_rate"]
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0


# ----------------------------------------------------------------------
# CLI smoke


class TestCli:
    def test_memory_arg_parses_known_values(self):
        from simulation.cli.run_pilot_matrix import _memory_arg

        assert _memory_arg("off") == ("memory-off",)
        assert _memory_arg("on") == ("memory-on",)
        assert _memory_arg("both") == ("memory-off", "memory-on")

    def test_memory_arg_rejects_unknown(self):
        from simulation.cli.run_pilot_matrix import _memory_arg
        import argparse

        with pytest.raises(argparse.ArgumentTypeError):
            _memory_arg("sometimes")
