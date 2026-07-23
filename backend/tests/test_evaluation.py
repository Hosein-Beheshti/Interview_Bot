from interview_bot.domain.evaluation import parse_score
from interview_bot.domain.rubric import DEFAULT_RUBRIC


def _full_dimensions(value: int) -> dict:
    return {d.key: value for d in DEFAULT_RUBRIC}


def test_parse_score_valid():
    tool_input = {
        "dimensions": _full_dimensions(8),
        "strengths": ["clear"],
        "improvements": ["go deeper"],
    }
    result = parse_score(tool_input)
    assert result is not None
    assert result.overall == 8
    assert result.dimensions == _full_dimensions(8)
    assert result.strengths == ["clear"]
    assert result.improvements == ["go deeper"]


def test_parse_score_computes_weighted_overall():
    dims = {d.key: i + 1 for i, d in enumerate(DEFAULT_RUBRIC)}  # 1, 2, 3
    result = parse_score({"dimensions": dims})
    assert result is not None
    assert result.overall == round(sum(dims.values()) / len(dims))


def test_parse_score_out_of_range_returns_none():
    dims = _full_dimensions(8)
    dims[DEFAULT_RUBRIC[0].key] = 99
    assert parse_score({"dimensions": dims}) is None


def test_parse_score_missing_dimension_returns_none():
    dims = _full_dimensions(8)
    dims.pop(DEFAULT_RUBRIC[0].key)
    assert parse_score({"dimensions": dims}) is None


def test_parse_score_missing_lists_default_empty():
    result = parse_score({"dimensions": _full_dimensions(5)})
    assert result is not None
    assert result.strengths == []
    assert result.improvements == []


def test_parse_score_malformed_returns_none():
    assert parse_score({}) is None
    assert parse_score({"dimensions": {}}) is None
    assert parse_score({"dimensions": {"technical_relevance": "abc"}}) is None


def test_parse_score_reads_control_signals():
    result = parse_score(
        {
            "dimensions": _full_dimensions(6),
            "answer_type": "no_answer",
            "follow_up_recommended": True,
        }
    )
    assert result is not None
    assert result.answer_type == "no_answer"
    assert result.follow_up_recommended is True


def test_parse_score_defaults_control_signals_when_absent():
    result = parse_score({"dimensions": _full_dimensions(6)})
    assert result is not None
    assert result.answer_type == "substantive"
    assert result.follow_up_recommended is False


def test_parse_score_rejects_unknown_answer_type():
    result = parse_score(
        {"dimensions": _full_dimensions(6), "answer_type": "bogus"}
    )
    assert result is not None
    assert result.answer_type == "substantive"


def test_no_answer_scores_zero_with_no_strengths():
    result = parse_score(
        {
            "dimensions": _full_dimensions(7),  # model may still emit dimension scores
            "strengths": ["was honest"],
            "answer_type": "no_answer",
        }
    )
    assert result is not None
    assert result.overall == 0
    assert result.strengths == []
    assert all(v == 0 for v in result.dimensions.values())


def test_parse_score_captures_critique():
    result = parse_score(
        {
            "dimensions": _full_dimensions(6),
            "critique": "Answer lacked tradeoffs and edge cases.",
        }
    )
    assert result is not None
    assert result.critique == "Answer lacked tradeoffs and edge cases."


def test_parse_score_critique_defaults_empty_when_absent():
    result = parse_score({"dimensions": _full_dimensions(5)})
    assert result is not None
    assert result.critique == ""


def test_parse_score_critique_is_string_coerced():
    result = parse_score({"dimensions": _full_dimensions(5), "critique": 42})
    assert result is not None
    assert result.critique == "42"
