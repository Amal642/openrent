"""Pure aggregation helpers for pilot-matrix trial rows.

Designed for the OpenRent pilot but generic over (condition, scenario,
seed, outcome) tuples. Every function is pure: same input, same output,
no side effects, no I/O. The matrix runner builds raw trial rows; this
module reduces them to scenario- and condition-level rates.

Conventions:
- A "trial row" is the dict returned by `matrix._extract_trial_row`. It
  has at minimum: `condition`, `scenario_key`, `seed`, `passed`,
  `score`, `current_state`, `failure_types`, `phone_captured`,
  `viewing_booked`, `hippo_recall_count`, `hippo_ingest_count`,
  `prompt_tokens`, `generation_latency_ms`.
- "Condition" is the pilot label: "memory-off" or "memory-on" (the
  matrix runner stamps these). a3 ablation extends this with
  "memory-on-no-singlecell" once the runner supports the flag.
"""

from __future__ import annotations

from collections import Counter
from statistics import mean, pstdev
from typing import Any, Iterable, Mapping, Sequence


_DEFAULT_RATE_KEYS = (
    "passed",
    "phone_captured",
    "viewing_booked",
)


def aggregate_trials(
    trials: Sequence[Mapping[str, Any]],
    *,
    rate_keys: Sequence[str] = _DEFAULT_RATE_KEYS,
) -> dict[str, Any]:
    """Aggregate a flat list of trials into condition \u00d7 scenario tables.

    Returns:
      {
        "trial_count": int,
        "conditions": {<condition>: {<rate_key>: rate, "n": int, ...}},
        "scenarios": {
          <scenario_key>: {
            <condition>: {<rate_key>: rate, "n": int, ...}
          }
        },
        "failure_types_by_condition": {<condition>: {<ft>: count, ...}},
        "current_state_by_condition": {<condition>: {<state>: count, ...}}
      }
    """

    trial_count = len(trials)
    by_condition: dict[str, list[Mapping[str, Any]]] = {}
    by_scenario_condition: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for trial in trials:
        condition = str(trial.get("condition") or "unknown")
        scenario_key = str(trial.get("scenario_key") or "unknown")
        by_condition.setdefault(condition, []).append(trial)
        by_scenario_condition.setdefault((scenario_key, condition), []).append(trial)

    conditions: dict[str, dict[str, Any]] = {}
    for condition, rows in by_condition.items():
        conditions[condition] = _summarize(rows, rate_keys=rate_keys)

    scenarios: dict[str, dict[str, dict[str, Any]]] = {}
    for (scenario_key, condition), rows in by_scenario_condition.items():
        scenarios.setdefault(scenario_key, {})[condition] = _summarize(
            rows, rate_keys=rate_keys
        )

    failure_types_by_condition: dict[str, dict[str, int]] = {}
    current_state_by_condition: dict[str, dict[str, int]] = {}
    for condition, rows in by_condition.items():
        failure_types_by_condition[condition] = _failure_type_histogram(rows)
        current_state_by_condition[condition] = _current_state_histogram(rows)

    return {
        "trial_count": trial_count,
        "conditions": conditions,
        "scenarios": scenarios,
        "failure_types_by_condition": failure_types_by_condition,
        "current_state_by_condition": current_state_by_condition,
    }


def _summarize(
    rows: Sequence[Mapping[str, Any]],
    *,
    rate_keys: Sequence[str],
) -> dict[str, Any]:
    n = len(rows)
    out: dict[str, Any] = {"n": n}
    for key in rate_keys:
        out[f"{key}_rate"] = _rate(rows, key)
    out["score_mean"] = _mean_of(rows, "score")
    out["score_std"] = _std_of(rows, "score")
    out["prompt_tokens_mean"] = _mean_of(rows, "prompt_tokens")
    out["generation_latency_ms_mean"] = _mean_of(
        rows, "generation_latency_ms"
    )
    out["hippo_recall_mean"] = _mean_of(rows, "hippo_recall_count")
    out["hippo_ingest_mean"] = _mean_of(rows, "hippo_ingest_count")
    return out


def _rate(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    if not rows:
        return None
    hits = sum(1 for row in rows if bool(row.get(key)))
    return round(hits / len(rows), 4)


def _mean_of(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return None
    return round(mean(values), 4)


def _std_of(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
    if len(values) < 2:
        return 0.0 if values else None
    return round(pstdev(values), 4)


def _failure_type_histogram(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        for ft in row.get("failure_types") or ():
            if isinstance(ft, str):
                counter[ft] += 1
    return dict(counter.most_common())


def _current_state_histogram(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        state = row.get("current_state")
        if isinstance(state, str):
            counter[state] += 1
    return dict(counter.most_common())


__all__ = ["aggregate_trials"]
