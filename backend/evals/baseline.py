"""Run-over-run comparison of eval report artifacts.

A single run reports levels; a regression gate needs deltas — "84% in-band" only
means something next to last run's number. Both runners write a flat `summary`
block into their JSON artifact so a comparison is a dict lookup rather than a
re-derivation from per-item rows, and `--baseline` prints each headline metric
alongside its movement.

Provenance is checked before any metric is compared. A result is only comparable
within the (prompt_version, rubric_version, model) triple that produced it — the
reason those versions are content-derived hashes at all (see
`domain.rubric.RUBRIC_VERSION`). A baseline recorded under a different triple
therefore gets a loud warning rather than a silently meaningless delta: the
numbers still print, because seeing them is often the point of a prompt change,
but nothing pretends they are a regression signal.
"""
from __future__ import annotations

import json
from pathlib import Path

# Provenance fields whose movement invalidates a comparison. Not every runner
# emits every one; only the keys present in both reports are checked.
PROVENANCE = (
    "provider",
    "model",
    "judge_model",
    "prompt_version",
    "rubric_version",
    "judge_prompt_version",
    "criteria_version",
)


def load(path: Path) -> dict:
    """Read a previous report, or `{}` when it is missing or unreadable.

    A first run has no baseline and a stale path is a typo, not a crash — both
    degrade to "no baseline" so `--baseline` can sit permanently in a CI command
    line without needing the file to exist yet.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def provenance_drift(current_meta: dict, baseline: dict) -> list[str]:
    """Human-readable list of provenance fields that moved since the baseline."""
    baseline_meta = baseline.get("meta", {})
    return [
        f"{key}: {baseline_meta[key]} -> {current_meta[key]}"
        for key in PROVENANCE
        if key in current_meta and key in baseline_meta and current_meta[key] != baseline_meta[key]
    ]


def delta(current: float | None, previous: float | None, *, fmt: str = "{:+.0%}") -> str:
    """Movement of one metric since the baseline, as a print suffix.

    Takes the previous value rather than looking it up, so the same function
    serves the scorer's flat `summary` and the generator's nested `per_criterion`
    block. Returns an empty string when there is nothing to compare, so callers
    append it unconditionally to a line that must also read well on its own.
    """
    if current is None:
        return ""
    if previous is None:
        return "  (new)"
    if current == previous:
        return "  (unchanged)"
    return f"  ({fmt.format(current - previous)})"


def summary_value(baseline: dict, key: str) -> float | None:
    """One metric from a baseline's `summary` block, or None when absent."""
    return baseline.get("summary", {}).get(key) if baseline else None


def report_drift(current_meta: dict, baseline: dict) -> None:
    """Print the baseline's provenance banner before any metric is compared."""
    if not baseline:
        return
    stamp = baseline.get("meta", {}).get("generated_at", "unknown time")
    print(f"  comparing against baseline from {stamp}")
    drift = provenance_drift(current_meta, baseline)
    if drift:
        print("  WARNING: provenance changed since the baseline — deltas are NOT a")
        print("           regression signal, they are the effect of a different system:")
        for line in drift:
            print(f"             - {line}")
