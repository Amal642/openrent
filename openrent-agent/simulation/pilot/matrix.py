"""N\u00d7K pilot matrix runner.

Runs every (condition, scenario, seed) trial in a deterministic order
and produces three output artefacts in `output_dir`:

  - trials.jsonl   : one row per trial (raw evidence)
  - per_scenario.json : scenario \u00d7 condition aggregates
  - manifest.json  : run config, fixture metadata, git sha, timestamps

The matrix runner is intentionally pure-Python with no I/O hidden in
the engine path: it calls `simulation.lab.run_simulation_session(...)`
trial-by-trial, then extracts the fields it needs from the returned
session dict. That keeps the runner orthogonal to engine internals and
makes its output stable across engine refactors.

Memory regimes:
  - "shared"   : one HippoSession (one MCP subprocess) reused across
                 ALL trials of a given condition. Memory snap accumulates
                 in scenario \u00d7 seed order. This is the default \u2014 it's
                 the most production-like regime and gives the cleanest
                 cross-trial memory signal.
  - "per-trial": fresh HippoSession per trial (each gets an empty snap).
                 Useful as a sanity ablation: if memory-on still helps
                 per-trial, the gain is from within-session recall;
                 if it only helps under "shared", the gain is from
                 cross-trial memory.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from simulation.engine.hippo_hooks import HippoSession, HippoSessionMeta
from simulation.lab import run_simulation_session
from simulation.pilot.aggregate import aggregate_trials
from simulation.pilot.fixtures import PilotFixture, PilotScenario


# ----------------------------------------------------------------------
# Public dataclasses


@dataclass(frozen=True)
class MatrixConfig:
    """Inputs that fully determine a pilot-matrix run."""

    fixture: PilotFixture
    n_trials: int
    seed_base: int
    memory: tuple[str, ...]
    """Conditions to run, e.g. ('memory-off',) or ('memory-off', 'memory-on')."""
    memory_regime: str = "shared"
    output_dir: Path | None = None
    hippo_server_js: str | None = None
    hippo_snap: str = ":memory:"
    hippo_project_id: str = "openrent-sim-pilot"
    hippo_thread_prefix: str = ""
    hippo_k_evidence: int = 8
    trace_samples: bool = False
    enable_schemas: bool = False
    """When True and the trial is memory-on, call
    `hippo.client.consolidate(...)` after every session_runner call.
    Schemas mint as a side effect on the substrate; per-trial reports
    are captured in `MatrixResult.consolidate_events`.

    Locked in by hippocampus-1:docs/OPENRENT-PILOT-A2-PRECOMMIT.md
    Q3 ("after every trial"). Defaults to False so a0/a1/a1.1/a1.2
    matrix commands stay byte-identical."""


@dataclass
class MatrixResult:
    """Aggregated outcome of a matrix run."""

    config: MatrixConfig
    trials: list[dict[str, Any]] = field(default_factory=list)
    trace_samples: list[dict[str, Any]] = field(default_factory=list)
    consolidate_events: list[dict[str, Any]] = field(default_factory=list)
    aggregates: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0
    manifest: dict[str, Any] = field(default_factory=dict)


# Type alias for the session-runner injection (eases testing).
SessionRunner = Callable[..., dict[str, Any]]


# ----------------------------------------------------------------------
# Top-level entrypoint


def run_pilot_matrix(
    config: MatrixConfig,
    *,
    session_runner: SessionRunner = run_simulation_session,
    hippo_factory: Callable[..., HippoSession] | None = None,
) -> MatrixResult:
    """Run the full matrix, returning aggregated results.

    `session_runner` and `hippo_factory` are dependency-injected for
    tests: production callers leave them at default (the real
    `run_simulation_session` and the real `HippoOutreachClient`).
    """

    if config.n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if not config.memory:
        raise ValueError("at least one condition (memory-off|memory-on) is required")
    for condition in config.memory:
        if condition not in {"memory-off", "memory-on"}:
            raise ValueError(
                f"unknown condition {condition!r}; expected memory-off / memory-on"
            )
    if config.memory_regime not in {"shared", "per-trial"}:
        raise ValueError(
            f"unknown memory_regime {config.memory_regime!r}; "
            "expected 'shared' or 'per-trial'"
        )
    if config.hippo_k_evidence < 1:
        raise ValueError("hippo_k_evidence must be >= 1")

    factory = hippo_factory or _default_hippo_factory

    # Ensure the snap's parent directory exists BEFORE the MCP child opens.
    # The MCP server calls `atomicWriteJson(snap_path, ...)` from its
    # close() handler; without the parent dir, the write fails silently at
    # process exit and the snap never lands. Discovered by the a2 Q4 probe
    # when the a1.2 snap was missing despite --hippo-snap being set; see
    # `hippocampus-1:docs/OPENRENT-PILOT-A2-PRECOMMIT.md` "Known Bugs".
    if config.hippo_snap and config.hippo_snap != ":memory:":
        Path(config.hippo_snap).parent.mkdir(parents=True, exist_ok=True)

    result = MatrixResult(config=config)
    result.started_at = time.time()

    for condition in config.memory:
        wants_memory = condition == "memory-on"
        with _hippo_lifecycle(
            config=config,
            wants_memory=wants_memory,
            regime=config.memory_regime,
            factory=factory,
        ) as hippo_provider:
            for scenario in config.fixture.scenarios:
                for trial_index in range(config.n_trials):
                    seed = config.seed_base + trial_index
                    hippo = hippo_provider(scenario, trial_index)
                    trial_started = time.perf_counter()
                    session_dict = _safe_run_session(
                        session_runner,
                        scenario=scenario,
                        seed=seed,
                        hippo=hippo,
                    )
                    trial_elapsed_ms = int(
                        (time.perf_counter() - trial_started) * 1000
                    )
                    row = _extract_trial_row(
                        session_dict,
                        condition=condition,
                        scenario=scenario,
                        seed=seed,
                        trial_index=trial_index,
                        trial_elapsed_ms=trial_elapsed_ms,
                    )
                    result.trials.append(row)
                    if config.trace_samples:
                        result.trace_samples.append(
                            _extract_trace_sample(session_dict, row=row)
                        )
                    if config.enable_schemas and hippo is not None:
                        consolidate_event = _safe_consolidate(
                            hippo,
                            condition=condition,
                            scenario_key=scenario.scenario_key,
                            seed=seed,
                            trial_index=trial_index,
                        )
                        result.consolidate_events.append(consolidate_event)

    result.finished_at = time.time()
    result.aggregates = aggregate_trials(result.trials)
    result.manifest = _build_manifest(config, result)

    if config.output_dir is not None:
        _write_artefacts(config.output_dir, result)

    return result


# ----------------------------------------------------------------------
# Trial-level helpers


def _safe_consolidate(
    hippo: HippoSession,
    *,
    condition: str,
    scenario_key: str,
    seed: int,
    trial_index: int,
) -> dict[str, Any]:
    """Run one consolidate pass and capture the report (or error).

    A consolidate failure MUST NOT kill the matrix — the consolidator is
    a side-effect mechanism; if it errors we record the failure and let
    the next trial proceed (the matrix's verdict is then evaluated at
    apparatus-precondition level, see
    docs/OPENRENT-PILOT-A2-PRECOMMIT.md A1–A4).
    """

    base = {
        "condition": condition,
        "scenario_key": scenario_key,
        "seed": seed,
        "trial_index": trial_index,
    }
    try:
        # min_salience=1.05 is the Q4-amended OpenRent-specific value,
        # measurement-justified by experiments/a2-tn-salience-probe/probe.py.
        # See hippocampus-1:docs/OPENRENT-PILOT-A2-Q4-AMENDMENT.md. The
        # chess default of 1.2 is too strict for freshly-ingested OpenRent
        # cells (rememberV2 starts cells at 1.0; recall bumps +0.05/touch).
        report = hippo.client.consolidate(
            partition_by="sourceId",
            min_salience=1.05,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {**base, "error": f"{type(exc).__name__}: {exc}"}
    return {**base, "report": report}


def _safe_run_session(
    session_runner: SessionRunner,
    *,
    scenario: PilotScenario,
    seed: int,
    hippo: HippoSession | None,
) -> dict[str, Any]:
    """Call session_runner and surface failures as a structured error row.

    A single trial crash MUST NOT kill the entire matrix \u2014 the pilot
    cares about rates across N trials, so one OpenAI hiccup or one
    MCP timeout should be recorded as a failed trial and the loop
    should continue.
    """

    try:
        return session_runner(
            seed=seed,
            max_turns=scenario.max_turns,
            scenario_id=scenario.scenario_id,
            actor_id=scenario.actor_id,
            policy_id=scenario.policy_id,
            start_mode=scenario.start_mode,
            initial_message_source=scenario.initial_message_source,
            conversation_design_id=scenario.conversation_design_id,
            hippo=hippo,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "session_id": f"errored-{seed}",
            "events": [],
            "evaluation": {
                "score": 0.0,
                "passed": False,
                "failure_types": ["TRIAL_RUNNER_ERROR"],
                "dimension_scores": {},
                "conversation_state": {"current_state": "errored"},
                "rationale": f"trial failed: {exc}",
            },
            "observability": {},
            "runtime_context": {"flags": {}},
            "transcript": [],
            "_trial_error": str(exc),
        }


def _extract_trial_row(
    session_dict: Mapping[str, Any],
    *,
    condition: str,
    scenario: PilotScenario,
    seed: int,
    trial_index: int,
    trial_elapsed_ms: int,
) -> dict[str, Any]:
    evaluation = session_dict.get("evaluation") or {}
    state = evaluation.get("conversation_state") or {}
    observability = session_dict.get("observability") or {}
    events = session_dict.get("events") or []
    runtime_flags = (
        (session_dict.get("runtime_context") or {}).get("flags") or {}
    )
    failure_types = list(evaluation.get("failure_types") or [])
    current_state = state.get("current_state")
    phone_captured = (current_state == "phone_captured") and (
        "ASKED_PHONE_BEFORE_VIEWING" not in failure_types
    )
    viewing_booked = current_state in {"viewing_confirmed", "coordination"}

    recall_count = 0
    ingest_count = 0
    ingest_cell_count = 0
    ingest_outcome_label: str | None = None
    for event in events:
        event_type = _event_type(event)
        if event_type == "HIPPO_RECALL":
            recall_count += 1
        elif event_type == "HIPPO_INGEST":
            ingest_count += 1
            payload = _event_payload(event)
            cells = payload.get("cell_count")
            if isinstance(cells, int):
                ingest_cell_count += cells
            label = payload.get("outcome_label")
            if isinstance(label, str):
                ingest_outcome_label = label

    return {
        "condition": condition,
        "memory_flag": runtime_flags.get("hippo_memory", "off"),
        "scenario_key": scenario.scenario_key,
        "scenario_id": scenario.scenario_id,
        "conversation_design_id": scenario.conversation_design_id,
        "policy_id": scenario.policy_id,
        "start_mode": scenario.start_mode,
        "max_turns": scenario.max_turns,
        "seed": seed,
        "trial_index": trial_index,
        "session_id": session_dict.get("session_id"),
        "passed": bool(evaluation.get("passed")),
        "score": evaluation.get("score"),
        "dimension_scores": evaluation.get("dimension_scores") or {},
        "current_state": current_state,
        "failure_types": failure_types,
        "phone_captured": phone_captured,
        "viewing_booked": viewing_booked,
        "prompt_tokens": observability.get("prompt_tokens"),
        "completion_tokens": observability.get("completion_tokens"),
        "total_tokens": observability.get("total_tokens"),
        "generation_latency_ms": observability.get("generation_latency_ms"),
        "evaluation_timing_ms": observability.get("evaluation_timing_ms"),
        "run_duration_ms": observability.get("run_duration_ms"),
        "trial_elapsed_ms": trial_elapsed_ms,
        "hippo_recall_count": recall_count,
        "hippo_ingest_count": ingest_count,
        "hippo_ingest_cell_count": ingest_cell_count,
        "hippo_ingest_outcome_label": ingest_outcome_label,
        "trial_error": session_dict.get("_trial_error"),
    }


def _event_type(event: Any) -> str:
    if isinstance(event, Mapping):
        return str(event.get("event_type") or "")
    return str(getattr(event, "event_type", "") or "")


def _event_payload(event: Any) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        payload = event.get("payload") or {}
        return payload if isinstance(payload, Mapping) else {}
    payload = getattr(event, "payload", {}) or {}
    return payload if isinstance(payload, Mapping) else {}


def _extract_trace_sample(
    session_dict: Mapping[str, Any],
    *,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    events = session_dict.get("events") or []
    recall_payload = _first_event_payload(events, "HIPPO_RECALL")
    reply_payload = _first_event_payload(events, "REPLY_GENERATED")
    raw_prompt = reply_payload.get("raw_prompt")
    raw_prompt = raw_prompt if isinstance(raw_prompt, str) else ""
    memory_block_chars = 0
    if raw_prompt.startswith("Relevant prior outreach context"):
        memory_block, _sep, _rest = raw_prompt.partition("\n\n---\n\n")
        memory_block_chars = len(memory_block)

    return {
        "condition": row.get("condition"),
        "scenario_key": row.get("scenario_key"),
        "seed": row.get("seed"),
        "trial_index": row.get("trial_index"),
        "passed": row.get("passed"),
        "score": row.get("score"),
        "failure_types": row.get("failure_types"),
        "current_state": row.get("current_state"),
        "prompt_tokens": row.get("prompt_tokens"),
        "total_tokens": row.get("total_tokens"),
        "hippo_recall_count": row.get("hippo_recall_count"),
        "hippo_ingest_count": row.get("hippo_ingest_count"),
        "hippo_ingest_cell_count": row.get("hippo_ingest_cell_count"),
        "recall": {
            "trace_id": recall_payload.get("trace_id"),
            "query": recall_payload.get("query"),
            "note_count": recall_payload.get("note_count"),
            "warning_count": recall_payload.get("warning_count"),
            "notes_applied": recall_payload.get("notes_applied"),
            "notes_block_chars": recall_payload.get("notes_block_chars"),
            "notes_preview": recall_payload.get("notes_preview") or [],
            "evidence_sources": recall_payload.get("evidence_sources") or [],
        },
        "reply_text": reply_payload.get("reply_text"),
        "raw_prompt_chars": len(raw_prompt),
        "memory_block_chars": memory_block_chars,
    }


def _first_event_payload(
    events: Sequence[Any],
    event_type: str,
) -> Mapping[str, Any]:
    for event in events:
        if _event_type(event) == event_type:
            return _event_payload(event)
    return {}


# ----------------------------------------------------------------------
# Hippo lifecycle (snap regime + factory)


@contextmanager
def _hippo_lifecycle(
    *,
    config: MatrixConfig,
    wants_memory: bool,
    regime: str,
    factory: Callable[..., HippoSession],
) -> Iterator[Callable[[PilotScenario, int], HippoSession | None]]:
    """Yield a per-trial HippoSession provider for one condition pass.

    - memory-off  : provider always yields None (no MCP traffic).
    - memory-on / shared : one HippoSession reused across all trials;
                           closed when the context exits.
    - memory-on / per-trial : a new HippoSession per trial; closed
                              immediately after that trial returns.
    """

    if not wants_memory:
        def off_provider(_scenario: PilotScenario, _trial: int) -> None:
            return None

        yield off_provider
        return

    if regime == "shared":
        session = factory(config=config, scope_label="shared")
        try:
            def shared_provider(
                scenario: PilotScenario, _trial: int
            ) -> HippoSession:
                session.meta = _meta_for_scenario(config, scenario)
                return session

            yield shared_provider
        finally:
            session.close()
        return

    live: list[HippoSession] = []

    def per_trial_provider(
        scenario: PilotScenario, trial: int
    ) -> HippoSession:
        session = factory(
            config=config,
            scope_label=f"trial:{scenario.scenario_key}:{trial}",
        )
        session.meta = _meta_for_scenario(config, scenario)
        live.append(session)
        return session

    try:
        yield per_trial_provider
    finally:
        while live:
            live.pop().close()


def _meta_for_scenario(
    config: MatrixConfig, scenario: PilotScenario
) -> HippoSessionMeta:
    base_thread = scenario.thread_id or scenario.scenario_key
    thread_id = f"{config.hippo_thread_prefix}{base_thread}" if config.hippo_thread_prefix else base_thread
    return HippoSessionMeta(
        thread_id=thread_id,
        participant_id=f"{thread_id}-landlord",
        participant_role="landlord",
        stage=None,
        strategy=scenario.category,
        tags=("pilot", f"scenario:{scenario.scenario_key}"),
    )


def _default_hippo_factory(
    *,
    config: MatrixConfig,
    scope_label: str,
) -> HippoSession:
    """Construct the real `HippoOutreachClient` from MCP config.

    Imported lazily so the matrix module is importable without the
    `app.ai.memory.hippo_client` dependency (e.g. on a thin CI worker
    that only runs memory-off paths).
    """

    from app.ai.memory.hippo_client import HippoOutreachClient

    server_js = config.hippo_server_js or os.environ.get("HIPPO_STDIO_JS")
    if not server_js:
        raise RuntimeError(
            "memory-on requested but neither MatrixConfig.hippo_server_js "
            "nor the HIPPO_STDIO_JS environment variable is set."
        )
    client = HippoOutreachClient(
        server_js=server_js,
        storage=config.hippo_snap,
        project_id=f"{config.hippo_project_id}-{scope_label}",
        k_evidence=config.hippo_k_evidence,
    )
    meta = HippoSessionMeta(thread_id="placeholder")  # overwritten per scenario
    return HippoSession(client=client, meta=meta)


# ----------------------------------------------------------------------
# Artefact writers


def _write_artefacts(output_dir: Path, result: MatrixResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    trials_path = output_dir / "trials.jsonl"
    with trials_path.open("w", encoding="utf-8") as fh:
        for row in result.trials:
            fh.write(json.dumps(row, default=_jsonify, sort_keys=True))
            fh.write("\n")
    (output_dir / "per_scenario.json").write_text(
        json.dumps(result.aggregates, indent=2, sort_keys=True, default=_jsonify),
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(result.manifest, indent=2, sort_keys=True, default=_jsonify),
        encoding="utf-8",
    )
    if result.config.trace_samples:
        trace_path = output_dir / "trace_samples.jsonl"
        with trace_path.open("w", encoding="utf-8") as fh:
            for row in result.trace_samples:
                fh.write(json.dumps(row, default=_jsonify, sort_keys=True))
                fh.write("\n")
    if result.consolidate_events:
        consolidate_path = output_dir / "consolidate_events.jsonl"
        with consolidate_path.open("w", encoding="utf-8") as fh:
            for row in result.consolidate_events:
                fh.write(json.dumps(row, default=_jsonify, sort_keys=True))
                fh.write("\n")


def _jsonify(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"object is not JSON-serializable: {type(value)!r}")


def _build_manifest(config: MatrixConfig, result: MatrixResult) -> dict[str, Any]:
    return {
        "fixture_id": config.fixture.fixture_id,
        "fixture_description": config.fixture.description,
        "k": config.fixture.k,
        "n_trials": config.n_trials,
        "seed_base": config.seed_base,
        "memory_conditions": list(config.memory),
        "memory_regime": config.memory_regime,
        "hippo_project_id": config.hippo_project_id,
        "hippo_thread_prefix": config.hippo_thread_prefix,
        "hippo_snap": config.hippo_snap,
        "hippo_k_evidence": config.hippo_k_evidence,
        "trace_samples": config.trace_samples,
        "enable_schemas": config.enable_schemas,
        "trial_count": len(result.trials),
        "started_at_epoch": result.started_at,
        "finished_at_epoch": result.finished_at,
        "elapsed_seconds": round(result.finished_at - result.started_at, 3),
        "git_sha": _git_sha(),
        "scenarios": [
            {
                "scenario_key": s.scenario_key,
                "scenario_id": s.scenario_id,
                "policy_id": s.policy_id,
                "start_mode": s.start_mode,
                "max_turns": s.max_turns,
                "thread_id": s.thread_id,
                "category": s.category,
                "expected_outcome": s.expected_outcome,
            }
            for s in config.fixture.scenarios
        ],
    }


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # pragma: no cover - defensive
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


__all__ = [
    "MatrixConfig",
    "MatrixResult",
    "run_pilot_matrix",
]
