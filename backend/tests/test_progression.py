"""Tests for server-authoritative interview progression.

The decision of what the interviewer asks next is pure server logic driven by the
scorer's control signals, so it is exercised here without any LLM or DB calls.
"""
from types import SimpleNamespace

from interview_bot.config import settings
from interview_bot.domain.progression import apply_turn, decide_next_turn
from interview_bot.domain.scoring import ScoreData
from interview_bot.prompts import interviewer as prompt


def _session(questions_asked=1, followups_on_current=0, num_questions=5):
    return SimpleNamespace(
        session_id="test",
        questions_asked=questions_asked,
        followups_on_current=followups_on_current,
        num_questions=num_questions,
        answers_given=0,
        status="active",
        is_complete=False,
    )


def _score(answer_type="substantive", follow_up_recommended=False):
    return ScoreData(
        overall=7,
        answer_type=answer_type,
        follow_up_recommended=follow_up_recommended,
    )


def test_first_message_opens_with_main_question():
    mode, kind = decide_next_turn(_session(questions_asked=0), None, settings.max_followups_per_question)
    assert mode == prompt.MODE_MAIN
    assert kind is None


def test_no_answer_triggers_simplify_follow_up():
    mode, kind = decide_next_turn(_session(), _score(answer_type="no_answer"), settings.max_followups_per_question)
    assert mode == prompt.MODE_FOLLOW_UP
    assert kind == prompt.FOLLOW_UP_SIMPLIFY


def test_recommended_follow_up_deepens():
    mode, kind = decide_next_turn(_session(), _score(follow_up_recommended=True), settings.max_followups_per_question)
    assert mode == prompt.MODE_FOLLOW_UP
    assert kind == prompt.FOLLOW_UP_DEEPEN


def test_substantive_answer_advances_to_next_main():
    mode, kind = decide_next_turn(_session(questions_asked=2), _score(), settings.max_followups_per_question)
    assert mode == prompt.MODE_MAIN
    assert kind is None


def test_follow_up_budget_exhausted_moves_on():
    # Already used the per-question follow-up budget: a weak answer can no longer
    # trigger another follow-up; progression moves to the next main question.
    busy = _session(questions_asked=2, followups_on_current=settings.max_followups_per_question)
    mode, kind = decide_next_turn(busy, _score(answer_type="no_answer"), settings.max_followups_per_question)
    assert mode == prompt.MODE_MAIN
    assert kind is None


def test_last_main_question_answered_closes():
    last = _session(questions_asked=5, num_questions=5)
    mode, kind = decide_next_turn(last, _score(), settings.max_followups_per_question)
    assert mode == prompt.MODE_CLOSING
    assert kind is None


def test_follow_up_allowed_even_on_last_question():
    last = _session(questions_asked=5, followups_on_current=0, num_questions=5)
    mode, kind = decide_next_turn(last, _score(follow_up_recommended=True), settings.max_followups_per_question)
    assert mode == prompt.MODE_FOLLOW_UP
    assert kind == prompt.FOLLOW_UP_DEEPEN


def test_apply_main_question_increments_and_resets_followups():
    s = _session(questions_asked=2, followups_on_current=1)
    apply_turn(s, prompt.MODE_MAIN)
    assert s.questions_asked == 3
    assert s.followups_on_current == 0


def test_apply_follow_up_increments_only_followups():
    s = _session(questions_asked=2, followups_on_current=0)
    apply_turn(s, prompt.MODE_FOLLOW_UP)
    assert s.questions_asked == 2
    assert s.followups_on_current == 1


def test_apply_closing_marks_complete():
    s = _session(questions_asked=5, num_questions=5)
    apply_turn(s, prompt.MODE_CLOSING)
    assert s.status == "complete"
    assert s.is_complete is True


def test_full_interview_asks_exactly_num_questions_main_questions():
    # Simulate a full run with no follow-ups: every answer is substantive.
    s = _session(questions_asked=0, num_questions=3)
    score = None  # opening turn
    main_count = 0
    closed = False
    for _ in range(20):  # generous upper bound; should terminate well before
        mode, _kind = decide_next_turn(s, score, settings.max_followups_per_question)
        apply_turn(s, mode)
        if mode == prompt.MODE_MAIN:
            main_count += 1
        if mode == prompt.MODE_CLOSING:
            closed = True
            break
        score = _score()  # candidate answers each posed question
    assert closed
    assert main_count == 3
