"""Tests for server-side interview result aggregation (services/summary.py)."""
from services.interview.summary import build_summary


def _rec(q, score, follow_up=False, strengths=None, improvements=None):
    return {
        "q": q,
        "follow_up": follow_up,
        "score": score,
        "strengths": strengths or [],
        "improvements": improvements or [],
    }


def test_empty_scores_yield_zero_overall():
    s = build_summary("Engineer", [])
    assert s["overall"] == 0.0
    assert s["breakdown"] == []


def test_overall_is_mean_rounded_to_one_decimal():
    s = build_summary("Engineer", [_rec(1, 8), _rec(2, 7), _rec(3, 6)])
    assert s["overall"] == 7.0


def test_no_answer_zero_drags_overall_down():
    s = build_summary("Engineer", [_rec(1, 8), _rec(2, 0)])
    assert s["overall"] == 4.0


def test_follow_up_is_labelled_distinctly():
    s = build_summary("Engineer", [_rec(1, 5), _rec(1, 7, follow_up=True)])
    labels = [b["label"] for b in s["breakdown"]]
    assert labels == ["Q1", "Q1 follow-up"]


def test_strengths_and_improvements_are_deduped_and_capped():
    scores = [
        _rec(1, 8, strengths=["clear", "deep"], improvements=["x"]),
        _rec(2, 7, strengths=["clear", "concise"], improvements=["x", "y"]),
    ]
    s = build_summary("Engineer", scores)
    assert s["strengths"] == ["clear", "deep", "concise"]
    assert s["improvements"] == ["x", "y"]


def test_copy_text_includes_role_overall_and_labels():
    s = build_summary("Backend Engineer", [_rec(1, 8, strengths=["clear"])])
    text = s["copy_text"]
    assert "Backend Engineer" in text
    assert "Overall Score: 8.0/10" in text
    assert "Q1: 8/10" in text
    assert "+ clear" in text
