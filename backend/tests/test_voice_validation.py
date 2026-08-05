"""Tests for audio content-type validation (integrations/speech.py)."""
from interview_bot.integrations import speech


def test_accepts_each_supported_content_type():
    for content_type in speech.SUPPORTED_CONTENT_TYPES:
        assert speech.is_supported_content_type(content_type)


def test_accepts_content_type_with_codec_suffix():
    assert speech.is_supported_content_type("audio/webm;codecs=opus")


def test_rejects_none():
    assert not speech.is_supported_content_type(None)


def test_rejects_empty_string():
    assert not speech.is_supported_content_type("")


def test_rejects_unrelated_content_type():
    assert not speech.is_supported_content_type("application/pdf")
