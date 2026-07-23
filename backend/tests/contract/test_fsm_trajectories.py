"""FSM trajectory freeze: full interview runs under REPLAY must follow the exact
recorded state sequence and per-turn transition decisions.

Two layers:
  * end-to-end — the `trajectory` (main_question / follow_up / closing sequence)
    and per-turn (mode, answer_type, follow_up_recommended) match the recording;
  * pure — `progression.decide_next_turn` is exercised directly (no cassettes)
    on the transition edges that matter, so a change to the state machine fails
    with a precise, mock-free signal.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from config import settings
from fixtures.scenarios import RECORDINGS_DIR, SCENARIOS, run_scenario
from services.interview import progression, prompt
from services.interview.evaluation import ScoreData

_IDS = [s.name for s in SCENARIOS]


def _load_recording(name: str) -> dict:
    return json.loads((RECORDINGS_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_state_sequence_matches_recording(scenario):
    result = asyncio.run(run_scenario(scenario))
    assert result["trajectory"] == _load_recording(scenario.name)["trajectory"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_per_turn_transition_decisions_match_recording(scenario):
    result = asyncio.run(run_scenario(scenario))
    expected = _load_recording(scenario.name)
    got = [
        (t["mode"], t["answer_type"], t["follow_up_recommended"])
        for t in result["transcript"]
    ]
    want = [
        (t["mode"], t["answer_type"], t["follow_up_recommended"])
        for t in expected["transcript"]
    ]
    assert got == want


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_every_trajectory_terminates_in_closing(scenario):
    """A completed interview always ends in exactly one closing turn."""
    trajectory = _load_recording(scenario.name)["trajectory"]
    assert trajectory[-1] == prompt.MODE_CLOSING
    assert trajectory.count(prompt.MODE_CLOSING) == 1
    assert trajectory.count(prompt.MODE_MAIN) == scenario.num_questions


# --------------------------------------------------------------------------- #
# Pure transition edges — no cassettes, no I/O.
# --------------------------------------------------------------------------- #
def _state(**overrides) -> SimpleNamespace:
    base = dict(
        session_id="t",
        num_questions=3,
        questions_asked=1,
        followups_on_current=0,
        answers_given=1,
        status="active",
        is_complete=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _score(answer_type: str, follow_up: bool) -> ScoreData:
    return ScoreData(overall=5, answer_type=answer_type, follow_up_recommended=follow_up)


def test_opening_turn_is_main_question():
    assert progression.decide_next_turn(_state(questions_asked=0), None) == (
        prompt.MODE_MAIN,
        None,
    )


def test_no_answer_downshifts_to_simplify():
    assert progression.decide_next_turn(
        _state(followups_on_current=0), _score("no_answer", False)
    ) == (prompt.MODE_FOLLOW_UP, prompt.FOLLOW_UP_SIMPLIFY)


def test_promising_answer_probes_deeper():
    assert progression.decide_next_turn(
        _state(followups_on_current=0), _score("partial", True)
    ) == (prompt.MODE_FOLLOW_UP, prompt.FOLLOW_UP_DEEPEN)


def test_followup_budget_exhausted_moves_to_next_main():
    state = _state(followups_on_current=settings.max_followups_per_question, questions_asked=1)
    assert progression.decide_next_turn(state, _score("no_answer", True)) == (
        prompt.MODE_MAIN,
        None,
    )


def test_last_question_answered_moves_to_closing():
    state = _state(
        followups_on_current=settings.max_followups_per_question,
        questions_asked=3,
        num_questions=3,
    )
    assert progression.decide_next_turn(state, _score("substantive", False)) == (
        prompt.MODE_CLOSING,
        None,
    )
