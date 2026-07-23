"""Golden-output freeze: the full pipeline under REPLAY must reproduce the
committed recording byte-for-byte.

This is the invariant made executable — given identical inputs and identical
recorded provider responses, the structured outputs (extracted profile, plan,
per-competency scores, final summary) do not change. The structural refactor in
later steps must keep every one of these green without updating the recordings.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fixtures.scenarios import RECORDINGS_DIR, SCENARIOS, run_scenario

_IDS = [s.name for s in SCENARIOS]


def _load_recording(name: str) -> dict:
    return json.loads((RECORDINGS_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_pipeline_output_matches_recording(scenario):
    result = asyncio.run(run_scenario(scenario))
    expected = _load_recording(scenario.name)
    # Whole-object equality is the strongest freeze: profile, plan, transcript
    # (including per-turn dimensions and critique), scores, and summary all pin.
    assert result == expected


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_extracted_profile_is_frozen(scenario):
    """Narrow assertion on the extraction stage, for a precise failure signal."""
    result = asyncio.run(run_scenario(scenario))
    assert result["profile"] == _load_recording(scenario.name)["profile"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_per_competency_scores_are_frozen(scenario):
    """Freeze the rubric dimensions and weighted overall for every scored turn."""
    result = asyncio.run(run_scenario(scenario))
    expected = _load_recording(scenario.name)
    got = [(t["dimensions"], t["score"], t["answer_type"]) for t in result["transcript"]]
    want = [(t["dimensions"], t["score"], t["answer_type"]) for t in expected["transcript"]]
    assert got == want


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_final_summary_is_frozen(scenario):
    result = asyncio.run(run_scenario(scenario))
    assert result["summary"] == _load_recording(scenario.name)["summary"]
