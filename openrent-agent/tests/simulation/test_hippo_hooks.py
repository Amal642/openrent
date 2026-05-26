"""Tests for the hippocampus memory hooks wired into the simulation engine.

Layered:

- TestRecallHook / TestPromptWrapping / TestIngestHook exercise the pure
  helper functions in `simulation.engine.hippo_hooks` with a fake hippo
  session.
- TestRunnerIntegration runs `run_simulation` end-to-end with a fake MCP
  client patched into the runner, to verify the flag toggle, the
  HIPPO_RECALL / HIPPO_INGEST events, and the flag-off regression
  guarantee.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.memory.hippo_client import OutreachOutcome
from simulation.engine.hippo_hooks import (
    HippoSession,
    HippoSessionMeta,
    maybe_ingest_session,
    maybe_recall_notes,
    wrap_build_prompt,
)
from simulation.engine.runner import run_simulation


class _FakeHippoClient:
    """Stand-in for `HippoOutreachClient` recording every call."""

    def __init__(self) -> None:
        self.recall_calls: list[dict[str, Any]] = []
        self.ingest_calls: list[dict[str, Any]] = []
        self.forget_calls: list[str] = []
        self._closed = False
        self._next_cell = 0
        self.recall_return: dict[str, Any] = {
            "traceId": "trace-fake",
            "query": "fake",
            "notes": [],
            "warnings": [],
        }

    def recall_for_reply(self, **kwargs: Any) -> dict[str, Any]:
        self.recall_calls.append(dict(kwargs))
        return dict(self.recall_return)

    def ingest_thread(self, thread: dict[str, Any]) -> list[str]:
        self.ingest_calls.append(dict(thread))
        n = len(thread.get("messages") or []) + 1
        if thread.get("outcome"):
            n += 2
        ids = []
        for _ in range(n):
            self._next_cell += 1
            ids.append(f"cell-{self._next_cell}")
        return ids

    def forget_thread(self, thread_id: str) -> dict[str, Any]:
        self.forget_calls.append(thread_id)
        return {"forgotten": 0, "cellIds": []}

    def close(self) -> None:
        self._closed = True


def _build_session(
    client: _FakeHippoClient | None = None,
    **meta_overrides: Any,
) -> HippoSession:
    base_meta = {
        "thread_id": "thread-test",
        "participant_id": "landlord-test",
        "participant_role": "landlord",
        "account_id": "account-test",
        "property": {"id": "prop-1", "location": "Manchester", "bedrooms": 2},
        "stage": "VIEWING_DISCUSSION",
        "strategy": "viewing_first",
        "tags": ("pilot:7a",),
    }
    base_meta.update(meta_overrides)
    return HippoSession(
        client=client or _FakeHippoClient(),
        meta=HippoSessionMeta(**base_meta),
    )


class TestRecallHook:
    def test_no_op_when_hippo_none(self):
        assert maybe_recall_notes(None, last_actor_text="anything") is None

    def test_returns_none_when_query_empty(self):
        session = _build_session()
        assert maybe_recall_notes(session, last_actor_text="") is None
        assert maybe_recall_notes(session, last_actor_text=None) is None
        assert session.client.recall_calls == []  # type: ignore[attr-defined]

    def test_returns_trace_with_no_notes_when_recall_empty(self):
        client = _FakeHippoClient()
        session = _build_session(client=client)
        trace = maybe_recall_notes(
            session,
            last_actor_text="What's your job?",
        )
        assert trace is not None
        assert trace.query == "What's your job?"
        assert trace.note_count == 0
        assert trace.notes_block is None
        assert len(client.recall_calls) == 1
        kwargs = client.recall_calls[0]
        assert kwargs["latest_message"] == "What's your job?"
        assert kwargs["thread_id"] == "thread-test"
        assert kwargs["participant_role"] == "landlord"

    def test_formats_string_notes_into_bullet_block(self):
        client = _FakeHippoClient()
        client.recall_return = {
            "traceId": "trace-x",
            "query": "Q",
            "notes": [
                "Landlord previously refused phone capture before viewing.",
                "Earlier reply that booked a viewing used a friendly tone.",
            ],
            "warnings": [],
        }
        session = _build_session(client=client)
        trace = maybe_recall_notes(
            session,
            last_actor_text="Who else is moving?",
        )
        assert trace is not None
        assert trace.note_count == 2
        assert trace.notes_block is not None
        assert "Landlord previously refused" in trace.notes_block
        assert trace.notes_block.startswith("- ")

    def test_uses_fallback_query_when_actor_silent(self):
        client = _FakeHippoClient()
        session = _build_session(client=client)
        trace = maybe_recall_notes(
            session,
            last_actor_text=None,
            fallback_query="initial outreach to private landlord",
        )
        assert trace is not None
        assert client.recall_calls[0]["latest_message"] == (
            "initial outreach to private landlord"
        )


class TestPromptWrapping:
    def test_passthrough_when_notes_block_empty(self):
        def base(conv: str) -> str:
            return f"BASE[{conv}]"

        wrapped = wrap_build_prompt(None, base)
        assert wrapped is base  # same identity \u2014 no double-call cost.

    def test_prepends_notes_when_block_present(self):
        def base(conv: str) -> str:
            return f"BASE[{conv}]"

        wrapped = wrap_build_prompt(
            "- prior note 1\n- prior note 2",
            base,
        )
        out = wrapped("hello world")
        assert "Relevant prior outreach context" in out
        assert "prior note 1" in out
        assert "BASE[hello world]" in out
        assert out.index("prior note 1") < out.index("BASE[hello world]")


class _FakeEvaluation:
    def __init__(self, current_state: str, failure_types: tuple[str, ...] = ()):
        self.conversation_state = {"current_state": current_state}
        self.failure_types = list(failure_types)


class TestIngestHook:
    def test_no_op_when_hippo_none(self):
        assert (
            maybe_ingest_session(
                None,
                transcript=[],
                evaluation=_FakeEvaluation("stalled"),
            )
            is None
        )

    def test_empty_transcript_warns_but_does_not_raise(self):
        client = _FakeHippoClient()
        session = _build_session(client=client)
        trace = maybe_ingest_session(
            session,
            transcript=[],
            evaluation=_FakeEvaluation("stalled"),
        )
        assert trace is not None
        assert trace.cell_ids == ()
        assert trace.warning == "empty_transcript"
        assert client.ingest_calls == []
        assert client.forget_calls == []

    def test_terminal_state_records_outcome(self):
        client = _FakeHippoClient()
        session = _build_session(client=client)
        transcript = [
            SimpleNamespace(speaker="agent", message="Hi, viewing this Saturday?"),
            SimpleNamespace(speaker="actor", message="Sure, my number is 07700 900100."),
            SimpleNamespace(speaker="agent", message="Thanks!"),
        ]
        trace = maybe_ingest_session(
            session,
            transcript=transcript,
            evaluation=_FakeEvaluation("phone_captured"),
        )
        assert trace is not None
        assert trace.outcome_label == "phone_captured"
        assert trace.outcome_success is True
        assert client.forget_calls == ["thread-test"]
        assert len(client.ingest_calls) == 1
        thread = client.ingest_calls[0]
        assert thread["thread_id"] == "thread-test"
        assert thread["participant_id"] == "landlord-test"
        assert [m["speaker"] for m in thread["messages"]] == [
            "agent",
            "participant",
            "agent",
        ]
        assert thread["outcome"]["label"] == "phone_captured"
        assert thread["outcome"]["success"] is True

    def test_in_flight_state_skips_outcome(self):
        client = _FakeHippoClient()
        session = _build_session(client=client)
        transcript = [
            SimpleNamespace(speaker="agent", message="When can I view?"),
        ]
        trace = maybe_ingest_session(
            session,
            transcript=transcript,
            evaluation=_FakeEvaluation("initial_interest"),
        )
        assert trace is not None
        assert trace.outcome_label is None
        assert trace.outcome_success is None
        assert "outcome" not in client.ingest_calls[0]

    def test_safety_failure_demotes_phone_capture_to_failed(self):
        client = _FakeHippoClient()
        session = _build_session(client=client)
        transcript = [
            SimpleNamespace(speaker="agent", message="Hey, what's your number?"),
            SimpleNamespace(speaker="actor", message="07700 900100"),
        ]
        trace = maybe_ingest_session(
            session,
            transcript=transcript,
            evaluation=_FakeEvaluation(
                "phone_captured",
                failure_types=("ASKED_PHONE_BEFORE_VIEWING",),
            ),
        )
        assert trace is not None
        assert trace.outcome_label == "failed"
        assert trace.outcome_success is False
        assert (
            client.ingest_calls[0]["outcome"]["failed_reason"]
            == "ASKED_PHONE_BEFORE_VIEWING"
        )

    def test_forget_first_false_does_not_call_forget(self):
        client = _FakeHippoClient()
        session = _build_session(client=client)
        trace = maybe_ingest_session(
            session,
            transcript=[SimpleNamespace(speaker="agent", message="hi")],
            evaluation=_FakeEvaluation("stalled"),
            forget_first=False,
        )
        assert trace is not None
        assert client.forget_calls == []


# ----------------------------------------------------------------------
# Runner integration


def _fake_completion(**_: Any) -> Any:
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


@dataclass
class _RunSetup:
    captured_client: _FakeHippoClient | None = None


@pytest.fixture
def runner_env(monkeypatch, tmp_path):
    """Patches OpenAI + session store; returns nothing of its own."""

    from app.ai import replies
    from simulation.sessions import store as session_store_module

    monkeypatch.setattr(replies, "_default_completion_create", _fake_completion)

    class TmpStore(session_store_module.JSONSessionStore):
        def __init__(self):
            super().__init__(base_dir=str(tmp_path))

    monkeypatch.setattr(
        "simulation.engine.orchestrator.JSONSessionStore",
        TmpStore,
    )
    return monkeypatch


class TestRunnerIntegration:
    def test_flag_off_regression_emits_no_hippo_events(self, runner_env):
        session = run_simulation(deterministic_seed=42, max_turns=1)
        event_types = [e.event_type for e in session.events]
        assert "HIPPO_RECALL" not in event_types
        assert "HIPPO_INGEST" not in event_types
        assert session.runtime_context["flags"]["hippo_memory"] == "off"

    def test_flag_on_emits_recall_and_ingest_events(self, runner_env, monkeypatch):
        setup = _RunSetup()

        def fake_build_hippo_session(**_: Any) -> HippoSession:
            client = _FakeHippoClient()
            client.recall_return = {
                "traceId": "trace-on",
                "query": "Q",
                "notes": [
                    "Prior landlord pushed for viewing before phone share.",
                ],
                "warnings": [],
            }
            setup.captured_client = client
            return HippoSession(
                client=client,
                meta=HippoSessionMeta(
                    thread_id="thread-int",
                    participant_id="landlord-int",
                ),
            )

        monkeypatch.setattr(
            "simulation.engine.runner._build_hippo_session",
            fake_build_hippo_session,
        )

        session = run_simulation(
            deterministic_seed=42,
            max_turns=1,
            hippo_memory=True,
        )

        assert session.runtime_context["flags"]["hippo_memory"] == "on"
        event_types = [e.event_type for e in session.events]
        assert "HIPPO_RECALL" in event_types
        assert "HIPPO_INGEST" in event_types

        recall_event = next(
            e for e in session.events if e.event_type == "HIPPO_RECALL"
        )
        assert recall_event.payload["note_count"] == 1
        assert recall_event.payload["notes_applied"] is True
        assert recall_event.payload["trace_id"] == "trace-on"

        ingest_event = next(
            e for e in session.events if e.event_type == "HIPPO_INGEST"
        )
        assert ingest_event.payload["cell_count"] >= 1
        assert ingest_event.payload["warning"] is None

        assert setup.captured_client is not None
        assert setup.captured_client._closed is True
        assert setup.captured_client.recall_calls, (
            "recall_for_reply should have been called at least once"
        )
        assert setup.captured_client.ingest_calls, (
            "ingest_thread should have been called at finalize"
        )
        assert setup.captured_client.forget_calls == ["thread-int"]

    def test_flag_on_without_server_js_raises(self, runner_env, monkeypatch):
        monkeypatch.delenv("HIPPO_STDIO_JS", raising=False)
        with pytest.raises(RuntimeError, match="HIPPO_STDIO_JS"):
            run_simulation(
                deterministic_seed=42,
                max_turns=1,
                hippo_memory=True,
            )


# ----------------------------------------------------------------------
# Live integration (skipped unless HIPPO_STDIO_JS is set and resolvable)


def _live_server_js() -> str | None:
    candidate = os.environ.get("HIPPO_STDIO_JS")
    if not candidate or not Path(candidate).is_file():
        return None
    if shutil.which("node") is None:
        return None
    return candidate


@pytest.mark.skipif(
    _live_server_js() is None,
    reason=(
        "Set HIPPO_STDIO_JS to a built memory-kit-mcp stdio.js (and have "
        "node on PATH) to run live runner integration."
    ),
)
class TestRunnerLive:
    def test_run_simulation_with_real_mcp_emits_hippo_events(self, runner_env):
        server_js = _live_server_js()
        assert server_js is not None
        session = run_simulation(
            deterministic_seed=42,
            max_turns=1,
            hippo_memory=True,
            hippo_server_js=server_js,
            hippo_snap=":memory:",
            hippo_project_id="openrent-pilot-test",
            hippo_thread_id="thread-live-7a",
        )
        assert session.runtime_context["flags"]["hippo_memory"] == "on"
        event_types = [e.event_type for e in session.events]
        assert "HIPPO_RECALL" in event_types
        assert "HIPPO_INGEST" in event_types
        ingest_event = next(
            e for e in session.events if e.event_type == "HIPPO_INGEST"
        )
        assert ingest_event.payload["cell_count"] >= 1
        assert ingest_event.payload["warning"] is None
