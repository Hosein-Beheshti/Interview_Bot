"""Tests for CV name extraction (integrations/cv_parser.py)."""
from interview_bot.integrations import cv_parser


def test_extracts_first_name_from_top_line():
    text = "Jane Doe\nSoftware Engineer\njane@example.com\n\nExperience\n..."
    assert cv_parser.extract_name(text) == "Jane"


def test_skips_heading_keywords_before_name():
    text = "Curriculum Vitae\nJohn Smith\nSenior Developer\n"
    assert cv_parser.extract_name(text) == "John"


def test_returns_none_when_no_name_line_found():
    text = "Resume\nSummary\nPhone: 555-0100\njane@example.com\nObjective\n"
    assert cv_parser.extract_name(text) is None


def test_ignores_lines_with_digits_or_email():
    text = "jane.doe@example.com\n+1 555 0100\nJane Doe\n"
    assert cv_parser.extract_name(text) == "Jane"
