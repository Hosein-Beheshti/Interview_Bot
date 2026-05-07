from services.evaluation import extract_score_json, is_interview_complete


def test_extract_score_valid_json():
    reply = 'Good answer! {"score": 8, "strengths": ["clear"], "improvements": ["depth"]}'
    result = extract_score_json(reply)
    assert result is not None
    assert result.score == 8
    assert result.strengths == ["clear"]
    assert result.improvements == ["depth"]


def test_extract_score_invalid_returns_none():
    assert extract_score_json("Just text, no JSON") is None
    assert extract_score_json('{"score": 99}') is None  # out of range
    assert extract_score_json("") is None


def test_extract_score_missing_lists():
    reply = '{"score": 5}'
    result = extract_score_json(reply)
    assert result is not None
    assert result.score == 5
    assert result.strengths == []
    assert result.improvements == []


def test_is_interview_complete():
    assert is_interview_complete("Good job. INTERVIEW_COMPLETE") is True
    assert is_interview_complete("Just a regular response") is False
