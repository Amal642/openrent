"""Tests for the OpenRent-side hippocampus outreach adapter.

Two test classes:

- TestHippoClientOffline: mocks `MemoryKitMcpClient` so the cell-shape
  contract can be exercised without spawning a Node subprocess. These
  tests are the source of truth for the per-message + header + outcome
  + pattern atomization shape mirroring `OutreachHippo.ingestThread()`.

- TestHippoClientLive: spawns a real `node packages/memory-kit-mcp/dist/stdio.js`
  subprocess against the hippocampus checkout pointed to by the
  `HIPPO_STDIO_JS` env var. Skipped when the env var is unset OR the
  resolved path does not exist OR `node` is not on PATH. This catches
  protocol-level breakage that mocks cannot see.

Run only the offline subset (always safe):

    pytest tests/test_hippo_client.py -k "not Live"

Run the live subset (requires built hippocampus stdio.js):

    $env:HIPPO_STDIO_JS = "D:\\hippocampus-prodV1\\packages\\memory-kit-mcp\\dist\\stdio.js"
    pytest tests/test_hippo_client.py::TestHippoClientLive
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.ai.memory.hippo_client import (
    HippoOutreachClient,
    HippoOutreachError,
    OutreachOutcome,
    sim_state_to_outcome,
)


class _FakeMcpClient:
    """Records every call_tool invocation and returns a deterministic cellIds list."""

    def __init__(self, *_, **__) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._next_cell = 0
        self._initialized = False
        self._closed = False

    def initialize(self) -> dict[str, Any]:
        self._initialized = True
        return {
            "protocolVersion": "fake",
            "serverInfo": {"name": "fake", "version": "0"},
        }

    def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, dict(args)))
        if name in {"hippo_memory_remember_event", "hippo_memory_record_outcome"}:
            self._next_cell += 1
            return {
                "cellIds": [f"cell-{self._next_cell}"],
                "edgesCreated": 0,
                "edgesUpdated": 0,
            }
        if name == "hippo_memory_recall_context":
            return {
                "traceId": "trace-fake",
                "query": "fake",
                "notes": [],
                "warnings": [],
                "evidence": [],
                "lineage": [],
                "explanation": [],
                "budgetUsed": {},
            }
        if name == "hippo_memory_forget":
            return {"forgotten": 0, "cellIds": []}
        if name == "hippo_memory_consolidate":
            return {
                "clustersTotal": 1,
                "cellsClustered": 3,
                "schemasNewlyMinted": 1,
                "schemasAbstained": 0,
                "edgesAdded": 3,
            }
        raise AssertionError(f"unexpected tool call: {name}")

    def close(self) -> None:
        self._closed = True


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> "_FakeMcpClient":
    fake = _FakeMcpClient()

    def _factory(*args: object, **kwargs: object) -> _FakeMcpClient:
        return fake

    monkeypatch.setattr(
        "app.ai.memory.hippo_client.MemoryKitMcpClient", _factory
    )
    return fake


class TestSimStateMapping:
    def test_phone_captured_is_success(self) -> None:
        outcome = sim_state_to_outcome("phone_captured")
        assert outcome is not None
        assert outcome.label == "phone_captured"
        assert outcome.success is True
        assert outcome.phone_captured is True
        assert outcome.reward == 1.0

    def test_viewing_confirmed_maps_to_viewing_booked(self) -> None:
        outcome = sim_state_to_outcome("viewing_confirmed")
        assert outcome is not None
        assert outcome.label == "viewing_booked"
        assert outcome.success is True
        assert outcome.meeting_booked is True

    def test_stalled_is_failure(self) -> None:
        outcome = sim_state_to_outcome("stalled")
        assert outcome is not None
        assert outcome.label == "failed"
        assert outcome.success is False
        assert outcome.reward == -1.0

    def test_in_flight_states_return_none(self) -> None:
        for state in ("screening", "viewing_negotiation", "initial_interest"):
            assert sim_state_to_outcome(state) is None

    def test_safety_failure_overrides_success_to_failed(self) -> None:
        outcome = sim_state_to_outcome(
            "phone_captured",
            ["ASKED_PHONE_BEFORE_VIEWING"],
        )
        assert outcome is not None
        assert outcome.label == "failed"
        assert outcome.success is False
        assert outcome.failed_reason == "ASKED_PHONE_BEFORE_VIEWING"
        assert outcome.phone_captured is False  # negated by the safety failure


class TestHippoClientOffline:
    """Per-message atomization shape via a mocked MCP client."""

    def _open_client(self, fake: _FakeMcpClient) -> HippoOutreachClient:
        return HippoOutreachClient(
            server_js="ignored",
            project_id="openrent-test",
        )

    def test_initialize_is_called_once_on_open(self, fake_client: _FakeMcpClient) -> None:
        client = self._open_client(fake_client)
        try:
            assert fake_client._initialized is True
        finally:
            client.close()
        assert fake_client._closed is True

    def test_ingest_thread_mints_per_message_then_header_then_outcome_then_pattern(
        self, fake_client: _FakeMcpClient
    ) -> None:
        thread = {
            "thread_id": "thread-1",
            "participant_id": "landlord-a",
            "participant_role": "landlord",
            "stage": "screening",
            "strategy": "viewing_first",
            "property": {
                "id": "listing-1",
                "location": "Hackney",
                "bedrooms": 2,
                "rent_pcm": 2200,
            },
            "messages": [
                {"speaker": "agent", "text": "Could we arrange a viewing?"},
                {"speaker": "participant", "text": "What do you both do for work?"},
                {"speaker": "agent", "text": "We are both employed and can move next month."},
            ],
            "outcome": {
                "label": "viewing_booked",
                "success": True,
                "meeting_booked": True,
                "reward": 1,
                "attributes": {"tone": "professional", "winningMessageSeq": 3},
            },
            "tags": ["fixture"],
        }

        with self._open_client(fake_client) as client:
            cell_ids = client.ingest_thread(thread)

        # 3 per-message + 1 header + 1 outcome (segmenter; we mock to 1 cell)
        # + 1 pattern = 6
        assert len(cell_ids) == 6

        tools_called = [call[0] for call in fake_client.calls]
        assert tools_called == [
            "hippo_memory_remember_event",  # message 1
            "hippo_memory_remember_event",  # message 2
            "hippo_memory_remember_event",  # message 3
            "hippo_memory_remember_event",  # header
            "hippo_memory_record_outcome",  # outcome
            "hippo_memory_remember_event",  # pattern
        ]

        for i, (_, args) in enumerate(fake_client.calls[:3], start=1):
            assert args["singleCell"] is True
            assert args["sourceId"] == "thread-1"
            assert f"seq:{i}" in args["text"]
            assert "content:" in args["text"]
            tags = args["tags"]
            assert f"seq:{i}" in tags
            assert any(t.startswith("speaker:") for t in tags)

        header_call = fake_client.calls[3]
        assert header_call[1]["singleCell"] is True
        assert "outreach_thread thread-1" in header_call[1]["text"]
        assert "message_count 3" in header_call[1]["text"]
        assert header_call[1]["structured"]["atom"] == "thread_header"

        outcome_call = fake_client.calls[4]
        assert outcome_call[1]["outcome"] == "viewing_booked"
        assert outcome_call[1]["sourceId"] == "thread-1"
        assert outcome_call[1]["reward"] == 1.0

        pattern_call = fake_client.calls[5]
        assert pattern_call[1]["kind"] == "pattern"
        assert pattern_call[1]["singleCell"] is True
        assert "pattern outcome:viewing_booked success:true" in pattern_call[1]["text"]
        assert "tone professional" in pattern_call[1]["text"]
        assert "winning_message_seq:3" in pattern_call[1]["text"]

    def test_ingest_thread_without_outcome_skips_outcome_and_pattern(
        self, fake_client: _FakeMcpClient
    ) -> None:
        thread = {
            "thread_id": "thread-flight",
            "participant_id": "landlord-x",
            "messages": [
                {"speaker": "agent", "text": "Hello."},
                {"speaker": "participant", "text": "Hi."},
            ],
        }
        with self._open_client(fake_client) as client:
            cell_ids = client.ingest_thread(thread)
        assert len(cell_ids) == 3  # 2 messages + header
        tools = [call[0] for call in fake_client.calls]
        assert tools == [
            "hippo_memory_remember_event",
            "hippo_memory_remember_event",
            "hippo_memory_remember_event",
        ]

    def test_ingest_thread_requires_thread_id(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            with pytest.raises(HippoOutreachError):
                client.ingest_thread({"messages": []})

    def test_first_message_cell_carries_redactable_content(
        self, fake_client: _FakeMcpClient
    ) -> None:
        """cellIds[0] is the first per-message cell — the redaction test
        contract from outreach.test.ts hinges on this ordering."""
        thread = {
            "thread_id": "thread-redact",
            "messages": [
                {
                    "speaker": "participant",
                    "text": "Email me at landlord@example.com or call +44 7700 900123.",
                },
            ],
        }
        with self._open_client(fake_client) as client:
            cell_ids = client.ingest_thread(thread)
        assert len(cell_ids) >= 1
        first_call = fake_client.calls[0]
        assert first_call[0] == "hippo_memory_remember_event"
        assert "landlord@example.com" in first_call[1]["text"]

    def test_recall_for_reply_assembles_entities_and_state(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            result = client.recall_for_reply(
                latest_message="What about a viewing?",
                goal="draft reply",
                thread_id="thread-2",
                participant_id="landlord-b",
                participant_role="landlord",
                stage="screening",
                strategy="viewing_first",
                property_={"id": "listing-2", "location": "Camden", "bedrooms": 1},
                tags=["screening"],
            )
        assert result["traceId"] == "trace-fake"
        call = fake_client.calls[-1]
        assert call[0] == "hippo_memory_recall_context"
        args = call[1]
        assert args["currentText"] == "What about a viewing?"
        assert args["goal"] == "draft reply"
        assert args["entities"] == {
            "participant": "landlord-b",
            "role": "landlord",
            "propertyId": "listing-2",
            "location": "Camden",
            "bedrooms": "1",
        }
        assert args["state"] == {
            "threadId": "thread-2",
            "stage": "screening",
            "strategy": "viewing_first",
        }
        assert args["tags"] == ["screening"]
        # OPEN-6 is intentionally NOT plumbed across the MCP boundary in 7c.
        assert "open6" not in args

    def test_record_outcome_from_sim_skips_in_flight_states(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            result = client.record_outcome_from_sim(
                thread_id="thread-flight",
                current_state="screening",
            )
        assert result is None
        assert all(
            call[0] != "hippo_memory_record_outcome" for call in fake_client.calls
        )

    def test_record_outcome_from_sim_records_for_terminal_states(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            result = client.record_outcome_from_sim(
                thread_id="thread-end",
                participant_id="landlord-z",
                current_state="phone_captured",
                trace_id="trace-abc",
                tone="warm",
            )
        assert result is not None
        outcome_calls = [
            call for call in fake_client.calls
            if call[0] == "hippo_memory_record_outcome"
        ]
        assert len(outcome_calls) == 1
        args = outcome_calls[0][1]
        assert args["outcome"] == "phone_captured"
        assert args["sourceId"] == "thread-end"
        assert args["actorId"] == "landlord-z"
        assert args["traceId"] == "trace-abc"
        assert args["reward"] == 1.0
        assert args["structured"]["tone"] == "warm"

    def test_record_outcome_from_sim_demotes_unsafe_phone_capture(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            client.record_outcome_from_sim(
                thread_id="thread-unsafe",
                current_state="phone_captured",
                failure_types=["ASKED_PHONE_BEFORE_VIEWING"],
            )
        outcome_call = [
            call for call in fake_client.calls
            if call[0] == "hippo_memory_record_outcome"
        ][0]
        args = outcome_call[1]
        assert args["outcome"] == "failed"
        assert args["reward"] == -1.0
        assert args["structured"]["failedReason"] == "ASKED_PHONE_BEFORE_VIEWING"

    def test_forget_thread_calls_forget_tool(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            result = client.forget_thread("thread-zap")
        forget_calls = [
            call for call in fake_client.calls if call[0] == "hippo_memory_forget"
        ]
        assert len(forget_calls) == 1
        assert forget_calls[0][1] == {"sourceId": "thread-zap"}
        assert "forgotten" in result

    def test_consolidate_default_args_sends_partition_by_sourceId(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            report = client.consolidate()
        consolidate_calls = [
            c for c in fake_client.calls if c[0] == "hippo_memory_consolidate"
        ]
        assert len(consolidate_calls) == 1
        # Default: partition_by='sourceId', everything else server-default.
        assert consolidate_calls[0][1] == {"partitionBy": "sourceId"}
        # Report shape is whatever the MCP tool returns, passed through.
        assert report["schemasNewlyMinted"] == 1
        assert report["clustersTotal"] == 1

    def test_consolidate_overrides_flow_through_to_payload(
        self, fake_client: _FakeMcpClient
    ) -> None:
        with self._open_client(fake_client) as client:
            client.consolidate(
                partition_by="none",
                overlap_threshold=22,
                min_cluster_size=4,
                min_salience=0.8,
                exclude_source_prefixes=["schema", "synthetic"],
                max_clusters=50,
                edge_weight=0.5,
                use_summarizer=False,
            )
        args = next(
            c[1] for c in fake_client.calls if c[0] == "hippo_memory_consolidate"
        )
        assert args == {
            "partitionBy": "none",
            "overlapThreshold": 22,
            "minClusterSize": 4,
            "minSalience": 0.8,
            "excludeSourcePrefixes": ["schema", "synthetic"],
            "maxClusters": 50,
            "edgeWeight": 0.5,
            "useSummarizer": False,
        }


def _live_skip_reason() -> str | None:
    stdio_js = os.environ.get("HIPPO_STDIO_JS")
    if not stdio_js:
        return "HIPPO_STDIO_JS not set; skipping live MCP subprocess test"
    if not Path(stdio_js).exists():
        return f"HIPPO_STDIO_JS path does not exist: {stdio_js}"
    if shutil.which(os.environ.get("HIPPO_NODE", "node")) is None:
        return "node not found on PATH"
    return None


@pytest.mark.skipif(_live_skip_reason() is not None, reason=_live_skip_reason() or "")
class TestHippoClientLive:
    """Round-trip tests against a real stdio.js subprocess.

    Self-skip when HIPPO_STDIO_JS is not configured. These tests prove
    the protocol contract end-to-end; offline mocks cannot.
    """

    def test_per_message_ingest_and_recall_round_trip(self) -> None:
        stdio_js = os.environ["HIPPO_STDIO_JS"]
        node = os.environ.get("HIPPO_NODE", "node")
        with HippoOutreachClient(
            server_js=stdio_js,
            node=node,
            storage=":memory:",
            project_id="openrent-live-test",
        ) as client:
            thread = {
                "thread_id": "live-thread-1",
                "participant_id": "landlord-live",
                "participant_role": "landlord",
                "stage": "screening",
                "strategy": "viewing_first",
                "property": {"id": "listing-live", "location": "Hackney", "bedrooms": 2},
                "messages": [
                    {"speaker": "agent", "text": "Could we arrange a viewing for the 2-bed in Hackney?"},
                    {"speaker": "participant", "text": "What do you both do for work?"},
                    {"speaker": "agent", "text": "We are both employed and can move next month."},
                ],
                "outcome": {
                    "label": "viewing_booked",
                    "success": True,
                    "meeting_booked": True,
                    "reward": 1,
                },
            }
            cell_ids = client.ingest_thread(thread)
            assert len(cell_ids) >= len(thread["messages"]) + 2  # msgs + header + pattern (outcome may be 1+)

            recall = client.recall_for_reply(
                latest_message="What did the agent say about being employed?",
                goal="book a viewing before asking for phone details",
                thread_id="live-thread-1",
                stage="screening",
            )
            notes_text = "\n".join(recall.get("notes", []))
            assert "employed" in notes_text.lower(), (
                f"expected 'employed' in recall.notes for live round-trip; got: {notes_text!r}"
            )

            forgotten = client.forget_thread("live-thread-1")
            assert forgotten.get("forgotten", 0) >= len(thread["messages"]), (
                f"expected forget to remove >= {len(thread['messages'])} cells; "
                f"got: {forgotten}"
            )

    def test_record_outcome_from_sim_against_live_server(self) -> None:
        stdio_js = os.environ["HIPPO_STDIO_JS"]
        node = os.environ.get("HIPPO_NODE", "node")
        with HippoOutreachClient(
            server_js=stdio_js,
            node=node,
            storage=":memory:",
            project_id="openrent-live-outcome",
        ) as client:
            client.ingest_thread({
                "thread_id": "live-outcome-thread",
                "messages": [
                    {"speaker": "agent", "text": "Hello — could we arrange a viewing?"},
                ],
            })
            result = client.record_outcome_from_sim(
                thread_id="live-outcome-thread",
                current_state="phone_captured",
            )
            assert result is not None
            assert len(result.get("cellIds", [])) >= 1
