"""OpenRent-side outreach-shaped wrapper over the memory-kit MCP client.

Mirrors `@hippocampus/outreach` `OutreachHippo.ingestThread()` cell shape
(per-message + thread-header + outcome + outcome-pattern cells) over the
generic memory-kit MCP transport so the TypeScript wrapper and the
OpenRent Python adapter produce indistinguishable cells.

Why a Python wrapper and not the TS `OutreachHippo`:
- OpenRent is Python; calling Hippocampus through the MCP stdio bridge
  is the agreed integration shape (see `docs/OUTREACH-HIPPO-IMPLEMENTATION-PLAN.md`
  in the hippocampus repo, "feat/openrent-integration").
- The TS wrapper bundles `OUTREACH_ROLE_ALIASES` and OPEN-6 query-role
  expansion, but `aliasMap` is `RegExp[]` and cannot cross a JSON-RPC
  boundary. Per the §S3 verdict in `docs/OUTREACH-ATOMIZATION-RESULTS.md`
  H3 was disproved (OPEN-6 not load-bearing on outreach), so OPEN-6 is
  deliberately not plumbed through this adapter for the pilot. The
  per-message atomization (H1) IS the load-bearing mechanism and is
  reproduced here verbatim.

Cell shape contract (locked; do not change without updating the
hippocampus-side §S3):

  ingest_thread(thread) mints, in order:
    cellIds[0..N-1] : N per-message cells (one per thread["messages"][i])
    cellIds[N]      : thread-header cell
    cellIds[N+1..]  : outcome + pattern cells if thread["outcome"] present

  Every cell goes through `hippo_memory_remember_event` with
  `singleCell: true` (except the outcome cell, which uses
  `hippo_memory_record_outcome` and may be sentence-segmented; that
  matches the TS wrapper).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.ai.memory._memory_kit_client import (
    MemoryKitMcpClient,
    MemoryKitMcpError,
)


class HippoOutreachError(RuntimeError):
    """Raised for outreach-shaped contract violations or upstream MCP errors."""


@dataclass(frozen=True)
class OutreachOutcome:
    """Sim-state-derived outcome ready for the record_outcome MCP tool.

    `label` mirrors `OutreachOutcome.label` in the TS wrapper. `success`,
    `phone_captured`, `meeting_booked`, `failed_reason` mirror the
    matching TS fields. `reward` is computed by `outcome_reward` and
    matches the TS `outcomeReward` heuristic.
    """

    label: str
    success: bool | None
    phone_captured: bool
    meeting_booked: bool
    failed_reason: str | None
    reward: float
    tone: str | None = None
    attributes: Mapping[str, Any] | None = None

    def to_summary(self) -> str:
        parts: list[str] = []
        if self.success is True:
            parts.append("Successful outreach outcome.")
        elif self.success is False:
            parts.append("Failed outreach outcome.")
        if self.phone_captured:
            parts.append("Phone was captured.")
        if self.meeting_booked:
            parts.append("Meeting or viewing was booked.")
        if self.failed_reason:
            parts.append(f"Failure reason: {self.failed_reason}.")
        return " ".join(parts) if parts else self.label


# Sim-state → (outreach_label, success) mapping. Mirrors the table in
# docs/OUTREACH-HIPPO-IMPLEMENTATION-PLAN.md "OpenRent pilot ...
# outcome vocabulary" section.
_SIM_STATE_OUTCOME_MAP: dict[str, tuple[str, bool] | None] = {
    "phone_captured": ("phone_captured", True),
    "viewing_confirmed": ("viewing_booked", True),
    "coordination": ("viewing_booked", True),
    "stalled": ("failed", False),
    # In-flight states never produce an outcome cell.
    "viewing_negotiation": None,
    "screening": None,
    "initial_interest": None,
}

# Failure_types that block a "success" verdict regardless of state.
# Mirrors simulation/evaluators/failure_types.py.
_SAFETY_BLOCKING_FAILURE_TYPES: frozenset[str] = frozenset({
    "ASKED_PHONE_BEFORE_VIEWING",
    "PUSHED_OFF_PLATFORM_TOO_EARLY",
})


def sim_state_to_outcome(
    current_state: str,
    failure_types: Sequence[str] = (),
    *,
    tone: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> OutreachOutcome | None:
    """Map a sim `conversation_state.current_state` + failure_types to an outcome.

    Returns None for in-flight states (the caller should NOT record an
    outcome cell in that case). Returns an OutreachOutcome for terminal
    states.

    Safety-blocking failure types (asked phone before viewing, pushed
    after refusal) override `success: True` to `success: False` and
    set `failed_reason` to the first blocking failure type — a sim
    that reached `phone_captured` but did so by asking too early is
    not a success outcome from the wrapper's perspective.
    """
    mapped = _SIM_STATE_OUTCOME_MAP.get(current_state)
    if mapped is None:
        return None

    base_label, base_success = mapped
    blocking_failures = [
        ft for ft in failure_types if ft in _SAFETY_BLOCKING_FAILURE_TYPES
    ]
    if blocking_failures and base_success:
        label = "failed"
        success: bool | None = False
        failed_reason: str | None = blocking_failures[0]
    else:
        label = base_label
        success = base_success
        failed_reason = blocking_failures[0] if blocking_failures else None

    phone_captured = current_state == "phone_captured" and not blocking_failures
    meeting_booked = (
        current_state in {"viewing_confirmed", "coordination"}
        and not blocking_failures
    )
    if success is True:
        reward = 1.0
    elif success is False:
        reward = -1.0
    else:
        reward = 0.0

    return OutreachOutcome(
        label=label,
        success=success,
        phone_captured=phone_captured,
        meeting_booked=meeting_booked,
        failed_reason=failed_reason,
        reward=reward,
        tone=tone,
        attributes=attributes,
    )


class HippoOutreachClient:
    """Outreach-shaped wrapper around MemoryKitMcpClient.

    Owns one MCP subprocess for the lifetime of the wrapper. Use as
    a context manager (recommended) or call close() explicitly.

    All ingest paths go through `hippo_memory_remember_event` with
    `singleCell: true` so per-message atomization is preserved across
    the JSON-RPC bridge.
    """

    def __init__(
        self,
        *,
        server_js: str,
        storage: str = ":memory:",
        project_id: str,
        node: str = "node",
        redact_contacts: bool = True,
        env: Mapping[str, str] | None = None,
        k_evidence: int = 8,
    ) -> None:
        if not project_id:
            raise HippoOutreachError("project_id is required")
        self._project_id = project_id
        self._k_evidence = k_evidence
        self._client = MemoryKitMcpClient(
            server_js=server_js,
            node=node,
            storage=storage,
            project_id=project_id,
            redact_contacts=redact_contacts,
            env=env,
        )
        try:
            self._client.initialize()
        except Exception:
            self._client.close()
            raise

    def __enter__(self) -> "HippoOutreachClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def project_id(self) -> str:
        return self._project_id

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Ingest

    def ingest_thread(self, thread: Mapping[str, Any]) -> list[str]:
        """Mint per-message + header + (optional) outcome + pattern cells.

        Argument shape (mirrors OutreachThread in TS):

            {
              "thread_id":         str (required),
              "participant_id":    str | None,
              "participant_role":  str | None,
              "account_id":        str | None,
              "property":          {"id"?, "location"?, "bedrooms"?, "rent_pcm"?, "type"?} | None,
              "stage":             str | None,
              "strategy":          str | None,
              "messages":          [{"speaker": "agent"|"participant"|"system", "text": str, "at"?: str|int}],
              "outcome":           OutreachOutcome | dict | None,
              "tags":              list[str] | None,
            }

        Returns the list of minted cellIds in mint order:
        [msg_1, msg_2, ..., msg_N, header, *outcome_cells, pattern].
        """
        thread_id = _require_str(thread.get("thread_id"), "thread.thread_id")
        messages = list(thread.get("messages") or [])
        participant_id = thread.get("participant_id")
        participant_role = thread.get("participant_role")
        account_id = thread.get("account_id")
        property_ = thread.get("property") or None
        stage = thread.get("stage")
        strategy = thread.get("strategy")
        outcome_input = thread.get("outcome")
        base_tags = _thread_tags(thread)
        entity_ids = _thread_entity_ids(thread)

        cell_ids: list[str] = []

        for seq, message in enumerate(messages, start=1):
            speaker = _require_str(message.get("speaker"), f"messages[{seq-1}].speaker")
            text = _require_str(message.get("text"), f"messages[{seq-1}].text")
            occurred_at = message.get("at")
            msg_tags = base_tags + [f"speaker:{speaker}", f"seq:{seq}"]
            payload: dict[str, Any] = {
                "kind": "interaction",
                "sourceId": thread_id,
                "entityIds": entity_ids,
                "tags": msg_tags,
                "text": _message_cell_text(
                    thread_id=thread_id,
                    stage=stage,
                    strategy=strategy,
                    participant_role=participant_role,
                    property_=property_,
                    speaker=speaker,
                    seq=seq,
                    message_text=text,
                ),
                "structured": _trimmed({
                    "atom": "message",
                    "speaker": speaker,
                    "seq": seq,
                    "stage": stage,
                    "strategy": strategy,
                    "participantRole": participant_role,
                    "propertyId": (property_ or {}).get("id"),
                    "location": (property_ or {}).get("location"),
                    "bedrooms": (property_ or {}).get("bedrooms"),
                    "occurredAt": occurred_at,
                }),
                "singleCell": True,
            }
            if participant_id:
                payload["actorId"] = participant_id
            if occurred_at is not None:
                payload["occurredAt"] = occurred_at
            result = self._client.call_tool("hippo_memory_remember_event", payload)
            cell_ids.extend(result.get("cellIds", []))

        header_payload: dict[str, Any] = {
            "kind": "interaction",
            "sourceId": thread_id,
            "entityIds": entity_ids,
            "tags": base_tags,
            "text": _thread_header_cell_text(
                thread_id=thread_id,
                participant_role=participant_role,
                participant_id=participant_id,
                account_id=account_id,
                stage=stage,
                strategy=strategy,
                property_=property_,
                message_count=len(messages),
            ),
            "structured": _trimmed({
                "atom": "thread_header",
                "participantRole": participant_role,
                "accountId": account_id,
                "stage": stage,
                "strategy": strategy,
                "property": property_,
                "messageCount": len(messages),
            }),
            "singleCell": True,
        }
        if participant_id:
            header_payload["actorId"] = participant_id
        last_at = _latest_message_time(messages)
        if last_at is not None:
            header_payload["occurredAt"] = last_at
        header_result = self._client.call_tool(
            "hippo_memory_remember_event", header_payload
        )
        cell_ids.extend(header_result.get("cellIds", []))

        outcome = _coerce_outcome(outcome_input)
        if outcome is not None:
            outcome_cells = self._record_outcome_cells(
                thread_id=thread_id,
                participant_id=participant_id,
                base_tags=base_tags,
                outcome=outcome,
            )
            cell_ids.extend(outcome_cells)

            pattern_payload = self._pattern_cell_payload(
                thread_id=thread_id,
                participant_id=participant_id,
                entity_ids=entity_ids,
                base_tags=base_tags,
                stage=stage,
                strategy=strategy,
                participant_role=participant_role,
                property_=property_,
                messages=messages,
                outcome=outcome,
            )
            pattern_result = self._client.call_tool(
                "hippo_memory_remember_event", pattern_payload
            )
            cell_ids.extend(pattern_result.get("cellIds", []))

        return cell_ids

    # ------------------------------------------------------------------
    # Recall

    def recall_for_reply(
        self,
        *,
        latest_message: str,
        goal: str,
        thread_id: str | None = None,
        participant_id: str | None = None,
        participant_role: str | None = None,
        stage: str | None = None,
        strategy: str | None = None,
        property_: Mapping[str, Any] | None = None,
        tags: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Recall prompt-ready memory for the current reply step.

        Returns the raw `hippo_memory_recall_context` payload:
        { "traceId", "query", "notes", "warnings", "evidence", ... }.

        Note: OPEN-6 query-role expansion is NOT enabled across the
        MCP boundary in this version. See module docstring.
        """
        entities: dict[str, str] = {}
        if participant_id:
            entities["participant"] = participant_id
        if participant_role:
            entities["role"] = participant_role
        if property_:
            pid = property_.get("id")
            if pid:
                entities["propertyId"] = str(pid)
            loc = property_.get("location")
            if loc:
                entities["location"] = str(loc)
            bedrooms = property_.get("bedrooms")
            if bedrooms is not None:
                entities["bedrooms"] = str(bedrooms)
            ptype = property_.get("type")
            if ptype:
                entities["propertyType"] = str(ptype)

        state: dict[str, Any] = {}
        if thread_id:
            state["threadId"] = thread_id
        if stage:
            state["stage"] = stage
        if strategy:
            state["strategy"] = strategy

        payload: dict[str, Any] = {
            "goal": goal,
            "currentText": latest_message,
            "kEvidence": self._k_evidence,
        }
        if entities:
            payload["entities"] = entities
        if state:
            payload["state"] = state
        if tags:
            payload["tags"] = list(tags)
        return self._client.call_tool("hippo_memory_recall_context", payload)

    # ------------------------------------------------------------------
    # Outcome (sim-state-derived)

    def record_outcome_from_sim(
        self,
        *,
        thread_id: str,
        current_state: str,
        failure_types: Sequence[str] = (),
        participant_id: str | None = None,
        trace_id: str | None = None,
        tone: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> dict[str, Any] | None:
        """Map sim state to an outreach outcome and call record_outcome.

        Returns the raw MCP result if an outcome was recorded, or None
        if the sim state is in-flight (no outcome).
        """
        outcome = sim_state_to_outcome(
            current_state, failure_types, tone=tone
        )
        if outcome is None:
            return None
        entity_ids = [thread_id]
        if participant_id:
            entity_ids.append(participant_id)
        payload: dict[str, Any] = {
            "outcome": outcome.label,
            "sourceId": thread_id,
            "entityIds": entity_ids,
            "summary": outcome.to_summary(),
            "reward": outcome.reward,
            "structured": _trimmed({
                "success": outcome.success,
                "phoneCaptured": outcome.phone_captured,
                "meetingBooked": outcome.meeting_booked,
                "failedReason": outcome.failed_reason,
                "tone": outcome.tone,
            }),
        }
        if participant_id:
            payload["actorId"] = participant_id
        if trace_id:
            payload["traceId"] = trace_id
        if tags:
            payload["tags"] = list(tags)
        return self._client.call_tool("hippo_memory_record_outcome", payload)

    def forget_thread(self, thread_id: str) -> dict[str, Any]:
        return self._client.call_tool(
            "hippo_memory_forget", {"sourceId": thread_id}
        )

    # ------------------------------------------------------------------
    # Internals

    def _record_outcome_cells(
        self,
        *,
        thread_id: str,
        participant_id: str | None,
        base_tags: list[str],
        outcome: OutreachOutcome,
    ) -> list[str]:
        entity_ids = [thread_id]
        if participant_id:
            entity_ids.append(participant_id)
        payload: dict[str, Any] = {
            "outcome": outcome.label,
            "sourceId": thread_id,
            "entityIds": entity_ids,
            "summary": outcome.to_summary(),
            "reward": outcome.reward,
            "structured": _trimmed({
                "success": outcome.success,
                "phoneCaptured": outcome.phone_captured,
                "meetingBooked": outcome.meeting_booked,
                "failedReason": outcome.failed_reason,
                "tone": outcome.tone,
            }),
            "tags": base_tags,
        }
        if participant_id:
            payload["actorId"] = participant_id
        result = self._client.call_tool("hippo_memory_record_outcome", payload)
        return list(result.get("cellIds", []))

    def _pattern_cell_payload(
        self,
        *,
        thread_id: str,
        participant_id: str | None,
        entity_ids: list[str],
        base_tags: list[str],
        stage: str | None,
        strategy: str | None,
        participant_role: str | None,
        property_: Mapping[str, Any] | None,
        messages: Sequence[Mapping[str, Any]],
        outcome: OutreachOutcome,
    ) -> dict[str, Any]:
        winning = _winning_message_for(messages, outcome)
        success_word = (
            "true" if outcome.success is True
            else "false" if outcome.success is False
            else "unknown"
        )
        text_lines: list[str] = [
            f"pattern outcome:{outcome.label} success:{success_word} "
            f"stage:{stage or 'unknown'} strategy:{strategy or 'unknown'}",
        ]
        if participant_role:
            text_lines.append(f"participant_role {participant_role}")
        if property_ and property_.get("location"):
            text_lines.append(f"property_location {property_['location']}")
        if outcome.tone:
            text_lines.append(f"tone {outcome.tone}")
        if outcome.failed_reason:
            text_lines.append(f"failed_reason {outcome.failed_reason}")
        if outcome.phone_captured:
            text_lines.append("phone_captured true")
        if outcome.meeting_booked:
            text_lines.append("meeting_booked true")
        if winning is not None:
            text_lines.append(f"winning_message_seq:{winning['seq']}")
        text_lines.append("content:")
        text_lines.append(winning["text"] if winning else outcome.to_summary())

        payload: dict[str, Any] = {
            "kind": "pattern",
            "sourceId": thread_id,
            "entityIds": entity_ids,
            "tags": list(base_tags) + [
                f"outcome:{outcome.label}",
                f"success:{success_word}",
            ],
            "text": "\n".join(text_lines),
            "structured": _trimmed({
                "atom": "pattern",
                "outcomeLabel": outcome.label,
                "outcomeSuccess": outcome.success,
                "phoneCaptured": outcome.phone_captured,
                "meetingBooked": outcome.meeting_booked,
                "failedReason": outcome.failed_reason,
                "stage": stage,
                "strategy": strategy,
                "participantRole": participant_role,
                "propertyId": (property_ or {}).get("id"),
                "location": (property_ or {}).get("location"),
                "tone": outcome.tone,
                "winningMessageSeq": winning["seq"] if winning else None,
            }),
            "singleCell": True,
        }
        if participant_id:
            payload["actorId"] = participant_id
        last_at = _latest_message_time(messages)
        if last_at is not None:
            payload["occurredAt"] = last_at
        return payload


# ----------------------------------------------------------------------
# Module-private helpers


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise HippoOutreachError(f"{name} must be a non-empty string")
    return value


def _trimmed(record: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if v is not None}


def _thread_tags(thread: Mapping[str, Any]) -> list[str]:
    tags: list[str] = list(thread.get("tags") or [])
    if thread.get("stage"):
        tags.append(f"stage:{thread['stage']}")
    if thread.get("strategy"):
        tags.append(f"strategy:{thread['strategy']}")
    if thread.get("participant_role"):
        tags.append(f"role:{thread['participant_role']}")
    return tags


def _thread_entity_ids(thread: Mapping[str, Any]) -> list[str]:
    entity_ids: list[str] = [thread["thread_id"]]
    if thread.get("participant_id"):
        entity_ids.append(thread["participant_id"])
    property_ = thread.get("property") or {}
    if property_.get("id"):
        entity_ids.append(str(property_["id"]))
    if property_.get("location"):
        entity_ids.append(str(property_["location"]))
    return entity_ids


def _message_cell_text(
    *,
    thread_id: str,
    stage: str | None,
    strategy: str | None,
    participant_role: str | None,
    property_: Mapping[str, Any] | None,
    speaker: str,
    seq: int,
    message_text: str,
) -> str:
    lines: list[str] = [
        f"message speaker:{speaker} seq:{seq} "
        f"stage:{stage or 'unknown'} strategy:{strategy or 'unknown'}",
    ]
    if participant_role:
        lines.append(f"participant_role {participant_role}")
    if property_ and property_.get("location"):
        lines.append(f"property_location {property_['location']}")
    lines.append(f"thread {thread_id}")
    lines.append("content:")
    lines.append(message_text)
    return "\n".join(lines)


def _thread_header_cell_text(
    *,
    thread_id: str,
    participant_role: str | None,
    participant_id: str | None,
    account_id: str | None,
    stage: str | None,
    strategy: str | None,
    property_: Mapping[str, Any] | None,
    message_count: int,
) -> str:
    lines: list[str] = [f"outreach_thread {thread_id}"]
    if participant_role:
        lines.append(f"participant_role {participant_role}")
    if participant_id:
        lines.append(f"participant_id {participant_id}")
    if account_id:
        lines.append(f"account {account_id}")
    if stage:
        lines.append(f"stage {stage}")
    if strategy:
        lines.append(f"strategy {strategy}")
    if property_:
        loc = property_.get("location") or "unknown"
        beds = property_.get("bedrooms")
        beds_str = str(beds) if beds is not None else "?"
        rent = property_.get("rent_pcm")
        if rent is None:
            rent = property_.get("rentPcm")
        rent_str = str(rent) if rent is not None else "?"
        lines.append(f"property location:{loc} bedrooms:{beds_str} rentPcm:{rent_str}")
    lines.append(f"message_count {message_count}")
    return "\n".join(lines)


def _latest_message_time(messages: Iterable[Mapping[str, Any]]) -> Any:
    last_at: Any = None
    for message in messages:
        at = message.get("at")
        if at is not None:
            last_at = at
    return last_at


def _coerce_outcome(value: Any) -> OutreachOutcome | None:
    if value is None:
        return None
    if isinstance(value, OutreachOutcome):
        return value
    if not isinstance(value, Mapping):
        raise HippoOutreachError("thread.outcome must be a Mapping or OutreachOutcome")
    label = _require_str(value.get("label"), "outcome.label")
    success_raw = value.get("success")
    if success_raw is None:
        success: bool | None = None
    else:
        success = bool(success_raw)
    phone_captured = bool(value.get("phone_captured") or value.get("phoneCaptured"))
    meeting_booked = bool(value.get("meeting_booked") or value.get("meetingBooked"))
    failed_reason = value.get("failed_reason") or value.get("failedReason")
    reward_raw = value.get("reward")
    if reward_raw is None:
        if success is True:
            reward = 1.0
        elif success is False:
            reward = -1.0
        elif phone_captured or meeting_booked:
            reward = 1.0
        else:
            reward = 0.0
    else:
        reward = float(reward_raw)
    attributes = value.get("attributes")
    tone = value.get("tone")
    if tone is None and isinstance(attributes, Mapping):
        attr_tone = attributes.get("tone")
        if isinstance(attr_tone, str):
            tone = attr_tone
    return OutreachOutcome(
        label=label,
        success=success,
        phone_captured=phone_captured,
        meeting_booked=meeting_booked,
        failed_reason=failed_reason if isinstance(failed_reason, str) else None,
        reward=reward,
        tone=tone if isinstance(tone, str) else None,
        attributes=attributes if isinstance(attributes, Mapping) else None,
    )


def _winning_message_for(
    messages: Sequence[Mapping[str, Any]],
    outcome: OutreachOutcome,
) -> dict[str, Any] | None:
    explicit: Any = None
    if outcome.attributes is not None:
        explicit = outcome.attributes.get("winningMessageSeq")
        if explicit is None:
            explicit = outcome.attributes.get("winning_message_seq")
    if isinstance(explicit, int) and 1 <= explicit <= len(messages):
        m = messages[explicit - 1]
        text = m.get("text")
        if isinstance(text, str):
            return {"seq": explicit, "text": text}
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("speaker") == "agent":
            text = m.get("text")
            if isinstance(text, str):
                return {"seq": i + 1, "text": text}
    return None


__all__ = [
    "HippoOutreachClient",
    "HippoOutreachError",
    "MemoryKitMcpError",
    "OutreachOutcome",
    "sim_state_to_outcome",
]
