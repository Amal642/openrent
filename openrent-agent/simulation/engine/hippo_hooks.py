"""Hippocampus memory hooks for the simulation engine.

This module is the thin integration shim between the OpenRent simulation
engine and `app.ai.memory.hippo_client.HippoOutreachClient`. It exists so
the engine modules (`session_manager`, `orchestrator`, `runner`) can stay
small and free of `if hippo is None: ...` branching scattered everywhere.

Contract:

- When `HippoSession | None` is `None`, ALL helpers are explicit no-ops.
  This is the regression-safety guarantee for `--hippo-memory off`
  (the default).
- When the session is present, helpers translate sim-engine shapes
  (transcript / events / evaluation) into the outreach-shaped payloads
  the MCP client expects, and surface failures via warnings on the
  returned dict rather than raising into the orchestrator. The pilot
  cares about outcome differences with memory on vs off, so any MCP
  hiccup MUST NOT crash the run \u2014 it should degrade to "no memory".

Cell-shape contract is owned by `app/ai/memory/hippo_client.py`; this
module does NOT shape cells itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Sequence

from app.ai.memory.hippo_client import (
    HippoOutreachClient,
    HippoOutreachError,
    OutreachOutcome,
    sim_state_to_outcome,
)


DEFAULT_RECALL_GOAL = (
    "Help the AI agent reply to a landlord outreach so the conversation "
    "progresses toward a booked viewing without prematurely capturing the "
    "landlord's phone number."
)


@dataclass(frozen=True)
class HippoSessionMeta:
    """Per-simulation-session metadata stamped onto every cell + recall.

    `thread_id` is the stable key under which the session's transcript is
    stored in the snap. It is the recall + ingest "sourceId" and MUST be
    deterministic across re-runs of the same lead/property pair if you
    want cross-session memory; for one-off sim runs use the sim
    `session_id`.
    """

    thread_id: str
    participant_id: str | None = None
    participant_role: str | None = "landlord"
    account_id: str | None = None
    property: Mapping[str, Any] | None = None
    stage: str | None = None
    strategy: str | None = None
    goal: str = DEFAULT_RECALL_GOAL
    tags: tuple[str, ...] = ()


@dataclass
class HippoSession:
    """Bundle of an open MCP client + the metadata it is scoped to."""

    client: HippoOutreachClient
    meta: HippoSessionMeta

    def close(self) -> None:
        self.client.close()


# ----------------------------------------------------------------------
# Recall hook (pre-reply)


@dataclass(frozen=True)
class RecallTrace:
    """Observability payload for the HIPPO_RECALL event."""

    trace_id: str | None
    query: str | None
    note_count: int
    warning_count: int
    notes_block: str | None
    raw: Mapping[str, Any] = field(default_factory=dict)


def maybe_recall_notes(
    hippo: HippoSession | None,
    *,
    last_actor_text: str | None,
    fallback_query: str | None = None,
) -> RecallTrace | None:
    """Call hippo.recall_for_reply if hippo is wired; otherwise no-op.

    `last_actor_text` is the most recent actor (landlord) message. If
    empty (e.g., before the actor has spoken), we fall back to the
    `fallback_query` so we can still recall cross-session patterns
    keyed on the property/role/goal.
    """

    if hippo is None:
        return None
    query = (last_actor_text or fallback_query or "").strip()
    if not query:
        return None
    try:
        result = hippo.client.recall_for_reply(
            latest_message=query,
            goal=hippo.meta.goal,
            thread_id=hippo.meta.thread_id,
            participant_id=hippo.meta.participant_id,
            participant_role=hippo.meta.participant_role,
            stage=hippo.meta.stage,
            strategy=hippo.meta.strategy,
            property_=hippo.meta.property,
            tags=hippo.meta.tags or None,
        )
    except (HippoOutreachError, Exception) as exc:  # pragma: no cover - defensive
        return RecallTrace(
            trace_id=None,
            query=query,
            note_count=0,
            warning_count=1,
            notes_block=None,
            raw={"error": str(exc)},
        )

    notes = list(result.get("notes") or [])
    warnings = list(result.get("warnings") or [])
    notes_block = _format_notes(notes) if notes else None
    return RecallTrace(
        trace_id=result.get("traceId"),
        query=query,
        note_count=len(notes),
        warning_count=len(warnings),
        notes_block=notes_block,
        raw=result,
    )


def wrap_build_prompt(
    notes_block: str | None,
    build_prompt: Callable[[str], str],
) -> Callable[[str], str]:
    """Return a prompt builder that prepends recalled notes to the prompt.

    When `notes_block` is falsy this returns the original builder
    unchanged so flag-off behaviour stays byte-for-byte identical.
    """

    if not notes_block:
        return build_prompt

    def wrapped(conversation_text: str) -> str:
        base = build_prompt(conversation_text)
        return (
            "Relevant prior outreach context for this lead "
            "(from prior sessions / memory):\n"
            f"{notes_block}\n\n"
            "---\n\n"
            f"{base}"
        )

    return wrapped


def _format_notes(notes: Sequence[Any]) -> str:
    lines: list[str] = []
    for note in notes:
        text = _coerce_note_text(note)
        if not text:
            continue
        lines.append(f"- {text}")
    return "\n".join(lines)


def _coerce_note_text(note: Any) -> str:
    if isinstance(note, str):
        return note.strip()
    if isinstance(note, Mapping):
        for key in ("text", "summary", "note", "content"):
            value = note.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(note).strip()


# ----------------------------------------------------------------------
# Ingest hook (end-of-session)


@dataclass(frozen=True)
class IngestTrace:
    """Observability payload for the HIPPO_INGEST event."""

    cell_ids: tuple[str, ...]
    outcome_label: str | None
    outcome_success: bool | None
    warning: str | None = None


def maybe_ingest_session(
    hippo: HippoSession | None,
    *,
    transcript: Sequence[Any],
    evaluation: Any,
    forget_first: bool = True,
) -> IngestTrace | None:
    """Ingest the finished transcript + sim-derived outcome into hippo.

    `forget_first=True` (the default) deletes any prior cells under
    `meta.thread_id` before re-ingesting. This makes ingest idempotent
    across re-runs of the same `thread_id` (e.g., a sim that re-runs
    the same scenario) without growing the snap unboundedly.
    """

    if hippo is None:
        return None
    messages = _transcript_to_messages(transcript)
    if not messages:
        return IngestTrace(
            cell_ids=(),
            outcome_label=None,
            outcome_success=None,
            warning="empty_transcript",
        )

    current_state, failure_types = _extract_outcome_signals(evaluation)
    outcome = sim_state_to_outcome(current_state, failure_types)

    thread: dict[str, Any] = {
        "thread_id": hippo.meta.thread_id,
        "participant_id": hippo.meta.participant_id,
        "participant_role": hippo.meta.participant_role,
        "account_id": hippo.meta.account_id,
        "property": dict(hippo.meta.property) if hippo.meta.property else None,
        "stage": hippo.meta.stage,
        "strategy": hippo.meta.strategy,
        "messages": messages,
        "tags": list(hippo.meta.tags) if hippo.meta.tags else None,
    }
    if outcome is not None:
        thread["outcome"] = _outcome_to_payload(outcome)

    if forget_first:
        try:
            hippo.client.forget_thread(hippo.meta.thread_id)
        except Exception:  # pragma: no cover - defensive; snap empty == ok
            pass

    try:
        cell_ids = hippo.client.ingest_thread(thread)
    except (HippoOutreachError, Exception) as exc:  # pragma: no cover - defensive
        return IngestTrace(
            cell_ids=(),
            outcome_label=outcome.label if outcome else None,
            outcome_success=outcome.success if outcome else None,
            warning=f"ingest_failed: {exc}",
        )

    return IngestTrace(
        cell_ids=tuple(cell_ids),
        outcome_label=outcome.label if outcome else None,
        outcome_success=outcome.success if outcome else None,
    )


# ----------------------------------------------------------------------
# Transcript / evaluation projection


def _transcript_to_messages(transcript: Sequence[Any]) -> list[dict[str, Any]]:
    """Project a sim transcript into the outreach `messages` shape.

    sim speaker -> outreach speaker mapping:
      agent  -> agent
      actor  -> participant   (landlord plays the "participant" role)
      *      -> system        (defensive; nothing else is expected today)
    """

    messages: list[dict[str, Any]] = []
    for turn in transcript or ():
        speaker = _turn_speaker(turn)
        text = _turn_message(turn)
        if not text:
            continue
        out_speaker = {
            "agent": "agent",
            "actor": "participant",
        }.get(speaker, "system")
        messages.append({"speaker": out_speaker, "text": text})
    return messages


def _turn_speaker(turn: Any) -> str:
    if isinstance(turn, Mapping):
        return turn.get("speaker") or ""
    return getattr(turn, "speaker", "") or ""


def _turn_message(turn: Any) -> str:
    if isinstance(turn, Mapping):
        return turn.get("message") or ""
    return getattr(turn, "message", "") or ""


def _extract_outcome_signals(evaluation: Any) -> tuple[str, tuple[str, ...]]:
    """Pull (current_state, failure_types) off the evaluation result.

    `evaluation.conversation_state` is the dict returned by
    `analyze_conversation_state(...).to_dict()` and has a stable
    `current_state` key; `evaluation.failure_types` is a list[str].
    """

    state: Mapping[str, Any] = {}
    raw_state = getattr(evaluation, "conversation_state", None)
    if isinstance(raw_state, Mapping):
        state = raw_state
    current_state = ""
    raw_current = state.get("current_state") if state else None
    if isinstance(raw_current, str):
        current_state = raw_current
    failure_types_raw = getattr(evaluation, "failure_types", None) or ()
    failure_types: tuple[str, ...] = tuple(
        ft for ft in failure_types_raw if isinstance(ft, str)
    )
    return current_state, failure_types


def _outcome_to_payload(outcome: OutreachOutcome) -> dict[str, Any]:
    """Convert an OutreachOutcome to the dict shape `ingest_thread` accepts.

    `ingest_thread` re-coerces via `_coerce_outcome`, which accepts either
    an OutreachOutcome instance or a Mapping. We use the Mapping form to
    keep this module's surface JSON-safe (handy for replay traces).
    """

    payload = asdict(outcome)
    # `attributes` may be a frozen Mapping; asdict keeps it as-is.
    if payload.get("attributes") is None:
        payload.pop("attributes", None)
    return payload


__all__ = [
    "DEFAULT_RECALL_GOAL",
    "HippoSession",
    "HippoSessionMeta",
    "IngestTrace",
    "RecallTrace",
    "maybe_ingest_session",
    "maybe_recall_notes",
    "wrap_build_prompt",
]
