"""Tests for interviewer prompt rendering (prompts/interviewer.py)."""
from interview_bot.domain.plan import PlanSlot
from interview_bot.prompts import interviewer as prompt


def _build(mode, question_number=1, follow_up_kind=None):
    return prompt.turn_instruction(mode, question_number, follow_up_kind)


def test_first_main_question_introduces_and_labels():
    text = _build(prompt.MODE_MAIN, question_number=1)
    assert "introduce yourself" in text
    assert '"Question 1:"' in text


def test_later_main_question_labels_number_without_intro():
    text = _build(prompt.MODE_MAIN, question_number=3)
    assert '"Question 3:"' in text
    assert "introduce yourself" not in text


def test_deepen_follow_up_stays_on_topic_and_unnumbered():
    text = _build(prompt.MODE_FOLLOW_UP, question_number=2, follow_up_kind=prompt.FOLLOW_UP_DEEPEN)
    assert "deeper" in text.lower()
    assert "SAME topic" in text
    assert "numbered question" in text


def test_simplify_follow_up_is_supportive_and_does_not_reveal_answer():
    text = _build(prompt.MODE_FOLLOW_UP, question_number=2, follow_up_kind=prompt.FOLLOW_UP_SIMPLIFY)
    assert "could not answer" in text
    assert "simpler" in text
    assert "reveal the answer" in text


def test_main_question_pins_topic_to_plan_slot():
    slot = PlanSlot(
        skill="Kubernetes networking",
        intent="probe production debugging experience.",
        difficulty="advanced",
    )
    text = prompt.turn_instruction(prompt.MODE_MAIN, question_number=2, slot=slot)
    assert "Kubernetes networking" in text
    assert "advanced" in text


def test_main_question_without_slot_has_no_focus_clause():
    text = prompt.turn_instruction(prompt.MODE_MAIN, question_number=2)
    assert "Focus this question on" not in text


def test_first_main_question_greets_by_name_when_known():
    text = prompt.turn_instruction(prompt.MODE_MAIN, question_number=1, candidate_name="Hosein")
    assert "Hosein" in text


def test_first_main_question_omits_greeting_when_name_unknown():
    text = prompt.turn_instruction(prompt.MODE_MAIN, question_number=1)
    assert "Greet the candidate" not in text


def test_later_main_question_ignores_candidate_name():
    text = prompt.turn_instruction(prompt.MODE_MAIN, question_number=3, candidate_name="Hosein")
    assert "Hosein" not in text


def test_follow_up_ignores_slot():
    slot = PlanSlot(skill="Redis", intent="x", difficulty="advanced")
    text = prompt.turn_instruction(
        prompt.MODE_FOLLOW_UP, question_number=2, follow_up_kind=prompt.FOLLOW_UP_DEEPEN, slot=slot
    )
    assert "Redis" not in text
