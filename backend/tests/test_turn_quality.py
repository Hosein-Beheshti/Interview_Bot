"""Tests for the interviewer turn-format contract (domain/turn_quality.py).

`check_format` is the assertion; `repair` is what production does about it. Both
are pure string logic — the FSM's bookkeeping depends on the label, so this is
the seam where a drifting model is brought back in line without an LLM call.
"""
from interview_bot.domain import turn_quality
from interview_bot.domain.progression import MODE_CLOSING, MODE_FOLLOW_UP, MODE_MAIN


def test_correctly_labelled_main_question_is_left_alone():
    reply = "Question 2: How would you detect feature drift in production?"
    assert turn_quality.check_format(MODE_MAIN, 2, reply)
    assert turn_quality.repair(MODE_MAIN, 2, reply) == (reply, None)


def test_label_mid_sentence_still_counts():
    """The opening turn introduces itself first; the label need not lead."""
    reply = "I'm your interviewer today. Question 1: walk me through your ranking stack."
    assert turn_quality.check_format(MODE_MAIN, 1, reply)
    assert turn_quality.repair(MODE_MAIN, 1, reply) == (reply, None)


def test_wrong_number_is_renumbered_in_place():
    """The server's count is authoritative, so the label is what gets corrected —
    and the sentence around it survives."""
    reply = "Question 2: how do you keep the feature store consistent?"
    repaired, kind = turn_quality.repair(MODE_MAIN, 3, reply)
    assert kind == turn_quality.REPAIR_RENUMBERED
    assert repaired == "Question 3: how do you keep the feature store consistent?"
    assert turn_quality.check_format(MODE_MAIN, 3, repaired)


def test_missing_label_is_prepended():
    """What the recorded traffic actually does: bridge conversationally and never
    label the question at all."""
    reply = "That's a solid monitoring strategy, but you didn't address drift."
    repaired, kind = turn_quality.repair(MODE_MAIN, 2, reply)
    assert kind == turn_quality.REPAIR_LABELLED
    assert repaired == f"Question 2: {reply}"
    assert turn_quality.check_format(MODE_MAIN, 2, repaired)


def test_follow_up_that_poses_a_numbered_question_is_stripped():
    """A follow-up must not consume a main-question slot in the candidate's view."""
    reply = "Question 3: what would you do if the cache went stale?"
    repaired, kind = turn_quality.repair(MODE_FOLLOW_UP, 3, reply)
    assert kind == turn_quality.REPAIR_UNLABELLED
    assert repaired == "what would you do if the cache went stale?"
    assert turn_quality.check_format(MODE_FOLLOW_UP, 3, repaired)


def test_clean_follow_up_is_left_alone():
    reply = "Following up on that — what breaks first under load?"
    assert turn_quality.check_format(MODE_FOLLOW_UP, 2, reply)
    assert turn_quality.repair(MODE_FOLLOW_UP, 2, reply) == (reply, None)


def test_follow_up_mentioning_the_bare_word_is_not_rewritten():
    """There is no structural label to remove, so `repair` leaves it — the
    stricter `check_format` may still flag it for the eval."""
    reply = "Question aside, how would you measure that?"
    repaired, kind = turn_quality.repair(MODE_FOLLOW_UP, 2, reply)
    assert (repaired, kind) == (reply, None)
    assert not turn_quality.check_format(MODE_FOLLOW_UP, 2, reply)


def test_closing_turn_has_no_format_contract():
    reply = "That wraps up the interview. Wishing you the best."
    assert turn_quality.check_format(MODE_CLOSING, 3, reply)
    assert turn_quality.repair(MODE_CLOSING, 3, reply) == (reply, None)


def test_repair_always_satisfies_check_format_for_main_questions():
    """The property that makes the repair worth having at all."""
    for reply in (
        "Question 7: mismatched number",
        "no label at all here",
        "Question  4 :  odd spacing",
        "Question 2: correct already",
    ):
        repaired, _ = turn_quality.repair(MODE_MAIN, 2, reply)
        assert turn_quality.check_format(MODE_MAIN, 2, repaired), repaired
