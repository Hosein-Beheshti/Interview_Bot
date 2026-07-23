from interview_bot.domain import rubric


def test_score_format_requires_all_dimensions():
    fmt = rubric.build_score_format()
    dims = fmt["schema"]["properties"]["dimensions"]
    assert set(dims["required"]) == {d.key for d in rubric.DEFAULT_RUBRIC}
    expected_scores = list(range(rubric.MIN_SCORE, rubric.MAX_SCORE + 1))
    for d in rubric.DEFAULT_RUBRIC:
        prop = dims["properties"][d.key]
        assert prop["type"] == "integer"
        # Structured outputs ignore numeric minimum/maximum, so the score range is
        # an enum of allowed integers — which structured outputs do enforce.
        assert prop["enum"] == expected_scores
        assert "minimum" not in prop and "maximum" not in prop


def test_score_format_is_json_schema():
    fmt = rubric.build_score_format()
    assert fmt["type"] == "json_schema"
    # structured outputs require additionalProperties:false on every object
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["properties"]["dimensions"]["additionalProperties"] is False
    # critique must be first in required so the model writes it before scores
    assert fmt["schema"]["required"][0] == "critique"
    # control signals are part of the guaranteed shape
    assert set(fmt["schema"]["required"]) >= {"critique", "answer_type", "follow_up_recommended"}


def test_compute_overall_unweighted():
    scores = {d.key: 6 for d in rubric.DEFAULT_RUBRIC}
    assert rubric.compute_overall(scores) == 6


def test_compute_overall_weighted():
    custom = (
        rubric.Dimension("a", "A", "", weight=3.0),
        rubric.Dimension("b", "B", "", weight=1.0),
    )
    # (10*3 + 2*1) / 4 = 8
    assert rubric.compute_overall({"a": 10, "b": 2}, custom) == 8


def test_compute_overall_empty():
    assert rubric.compute_overall({}) == 0


def test_labelled_preserves_rubric_order():
    scores = {d.key: 5 for d in rubric.DEFAULT_RUBRIC}
    labelled = rubric.labelled(scores)
    assert [key for key, _, _ in labelled] == [d.key for d in rubric.DEFAULT_RUBRIC]
    assert all(label for _, label, _ in labelled)


def test_describe_rubric_lists_all_dimensions():
    text = rubric.describe_rubric()
    for d in rubric.DEFAULT_RUBRIC:
        assert d.label in text
