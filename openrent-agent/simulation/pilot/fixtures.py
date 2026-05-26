"""K-scenario fixture loader + schema validator for the pilot matrix.

A pilot fixture is a JSON file with this shape:

    {
      "fixture_id": "openrent-pilot-k10-v1",
      "description": "Locked K=10 scenario set for the OpenRent memory pilot.",
      "scenarios": [
        {
          "scenario_key": "s01-screening-agent-starts-mt1-prod",
          "scenario_id": "outreach-screening-before-phone",
          "policy_id": "production-policy-v1",
          "start_mode": "agent_starts",
          "max_turns": 1,
          "conversation_design_id": "viewing_first_v1",
          "initial_message_source": "fixture",
          "category": "production-opener",
          "expected_outcome": "phone_captured",
          "thread_id": "pilot-s01"
        },
        ...
      ]
    }

`scenario_key` is the stable per-row label used in the output CSV and
the per-scenario aggregation. `scenario_id` selects the underlying
scenario builder in `simulation.lab.SCENARIO_BUILDERS`. `expected_outcome`
is documentation only \u2014 the runner never asserts against it.

`thread_id` is the stable hippocampus thread key. With the default
`shared` memory regime, each scenario's thread cells accumulate across
N seeds, so memory recall at seed K has access to outcomes from seeds
1..K-1 for that scenario.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


_VALID_START_MODES = frozenset({"agent_starts", "actor_starts"})


@dataclass(frozen=True)
class PilotScenario:
    """One row of the K-scenario fixture."""

    scenario_key: str
    scenario_id: str
    policy_id: str
    start_mode: str
    max_turns: int
    conversation_design_id: str | None = None
    initial_message_source: str | None = None
    category: str | None = None
    expected_outcome: str | None = None
    thread_id: str | None = None


@dataclass(frozen=True)
class PilotFixture:
    """The fully loaded + validated fixture."""

    fixture_id: str
    description: str
    scenarios: tuple[PilotScenario, ...]

    @property
    def k(self) -> int:
        return len(self.scenarios)


class PilotFixtureError(ValueError):
    """Raised for malformed or missing-required-field fixtures."""


def load_pilot_fixture(path: str | Path) -> PilotFixture:
    """Load + validate a pilot fixture JSON file.

    Raises `PilotFixtureError` for any structural problem; the caller
    is expected to surface this verbatim (don't swallow \u2014 a malformed
    fixture should abort the pilot before any trial runs).
    """

    raw_path = Path(path)
    if not raw_path.is_file():
        raise PilotFixtureError(f"fixture file not found: {raw_path}")
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PilotFixtureError(f"fixture {raw_path} is not valid JSON: {exc}") from exc
    return _validate(data, source=str(raw_path))


def parse_pilot_fixture(data: Any, *, source: str = "<inline>") -> PilotFixture:
    """Validate an already-parsed dict (useful for tests)."""

    return _validate(data, source=source)


def _validate(data: Any, *, source: str) -> PilotFixture:
    if not isinstance(data, dict):
        raise PilotFixtureError(f"{source}: top-level value must be a JSON object")
    fixture_id = _require_str(data, "fixture_id", source)
    description = _require_str(data, "description", source)
    raw_scenarios = data.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise PilotFixtureError(
            f"{source}: 'scenarios' must be a non-empty list"
        )
    seen_keys: set[str] = set()
    scenarios: list[PilotScenario] = []
    for index, raw in enumerate(raw_scenarios):
        scenario = _parse_scenario(raw, index=index, source=source)
        if scenario.scenario_key in seen_keys:
            raise PilotFixtureError(
                f"{source}: duplicate scenario_key "
                f"{scenario.scenario_key!r} at index {index}"
            )
        seen_keys.add(scenario.scenario_key)
        scenarios.append(scenario)
    return PilotFixture(
        fixture_id=fixture_id,
        description=description,
        scenarios=tuple(scenarios),
    )


def _parse_scenario(raw: Any, *, index: int, source: str) -> PilotScenario:
    if not isinstance(raw, dict):
        raise PilotFixtureError(
            f"{source}: scenarios[{index}] must be a JSON object"
        )
    scenario_key = _require_str(raw, "scenario_key", f"{source}.scenarios[{index}]")
    scenario_id = _require_str(raw, "scenario_id", f"{source}.scenarios[{index}]")
    policy_id = _require_str(raw, "policy_id", f"{source}.scenarios[{index}]")
    start_mode = _require_str(raw, "start_mode", f"{source}.scenarios[{index}]")
    if start_mode not in _VALID_START_MODES:
        raise PilotFixtureError(
            f"{source}.scenarios[{index}].start_mode must be one of "
            f"{sorted(_VALID_START_MODES)} (got {start_mode!r})"
        )
    max_turns_raw = raw.get("max_turns", 1)
    if not isinstance(max_turns_raw, int) or max_turns_raw < 1:
        raise PilotFixtureError(
            f"{source}.scenarios[{index}].max_turns must be a positive int"
        )
    return PilotScenario(
        scenario_key=scenario_key,
        scenario_id=scenario_id,
        policy_id=policy_id,
        start_mode=start_mode,
        max_turns=max_turns_raw,
        conversation_design_id=_optional_str(raw, "conversation_design_id"),
        initial_message_source=_optional_str(raw, "initial_message_source"),
        category=_optional_str(raw, "category"),
        expected_outcome=_optional_str(raw, "expected_outcome"),
        thread_id=_optional_str(raw, "thread_id"),
    )


def _require_str(data: dict, key: str, source: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise PilotFixtureError(
            f"{source}.{key} is required and must be a non-empty string"
        )
    return value


def _optional_str(data: dict, key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise PilotFixtureError(f"{key!r} must be a non-empty string when present")
    return value


__all__ = [
    "PilotFixture",
    "PilotFixtureError",
    "PilotScenario",
    "load_pilot_fixture",
    "parse_pilot_fixture",
]
