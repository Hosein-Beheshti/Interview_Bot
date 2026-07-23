"""Tests for the interview blueprint domain logic (services/interview/plan.py)."""
from types import SimpleNamespace

from interview_bot.domain import plan
from interview_bot.domain.job_profile import JobProfile, minimal

PROFILE = JobProfile(
    role="Backend Engineer",
    key_skills=("Python", "Postgres", "API design"),
    focus_areas=("system design",),
)


def _slot(skill, intent="probe it", difficulty="intermediate"):
    return {"skill": skill, "intent": intent, "difficulty": difficulty}


def test_parse_plan_exact_count_passthrough():
    extracted = {"slots": [_slot("Python"), _slot("Postgres"), _slot("API design")]}
    result = plan.parse_plan(extracted, PROFILE, num_questions=3)
    assert [s.skill for s in result.slots] == ["Python", "Postgres", "API design"]


def test_parse_plan_truncates_when_model_overshoots():
    extracted = {"slots": [_slot(f"skill{i}") for i in range(8)]}
    result = plan.parse_plan(extracted, PROFILE, num_questions=3)
    assert len(result.slots) == 3


def test_parse_plan_pads_from_profile_then_role():
    extracted = {"slots": [_slot("Python")]}
    result = plan.parse_plan(extracted, PROFILE, num_questions=4)
    assert len(result.slots) == 4
    skills = [s.skill for s in result.slots]
    assert skills[0] == "Python"
    # Padding draws from uncovered key_skills/focus_areas before falling back to role.
    assert "Postgres" in skills and "API design" in skills


def test_parse_plan_pads_with_role_when_profile_exhausted():
    thin = minimal("Data Scientist")
    result = plan.parse_plan({"slots": []}, thin, num_questions=2)
    assert len(result.slots) == 2
    assert all(s.skill == "Data Scientist" for s in result.slots)


def test_parse_plan_normalizes_difficulty():
    extracted = {
        "slots": [
            _slot("a", difficulty="easy"),
            _slot("b", difficulty="HARD"),
            _slot("c", difficulty="nonsense"),
        ]
    }
    result = plan.parse_plan(extracted, PROFILE, num_questions=3)
    assert [s.difficulty for s in result.slots] == [
        "foundational",
        "advanced",
        "intermediate",
    ]


def test_parse_plan_skips_empty_slots():
    extracted = {"slots": [_slot("Python"), {"skill": "", "intent": ""}]}
    result = plan.parse_plan(extracted, PROFILE, num_questions=2)
    assert len(result.slots) == 2
    assert result.slots[0].skill == "Python"
    # The empty slot is dropped, then padding refills to the requested count.
    assert result.slots[1].skill != ""


def test_slot_for_is_one_based_and_bounds_safe():
    result = plan.parse_plan({"slots": [_slot("Python"), _slot("Go")]}, PROFILE, 2)
    assert result.slot_for(1).skill == "Python"
    assert result.slot_for(2).skill == "Go"
    assert result.slot_for(3) is None
    assert result.slot_for(0) is None


def test_to_from_dict_roundtrip():
    result = plan.parse_plan({"slots": [_slot("Python"), _slot("Go")]}, PROFILE, 2)
    assert plan.InterviewPlan.from_dict(result.to_dict()) == result


def test_resolve_reads_session_column():
    built = plan.parse_plan({"slots": [_slot("Python")]}, PROFILE, 1)
    session = SimpleNamespace(interview_plan=built.to_dict())
    assert plan.resolve(session) == built


def test_resolve_none_when_unplanned():
    assert plan.resolve(SimpleNamespace(interview_plan=None)) is None
    assert plan.resolve(SimpleNamespace(interview_plan={})) is None


def test_parse_plan_keeps_key_points():
    extracted = {
        "slots": [
            {
                "skill": "Python",
                "intent": "probe it",
                "difficulty": "intermediate",
                "key_points": ["generators", "GIL", "context managers"],
            }
        ]
    }
    result = plan.parse_plan(extracted, PROFILE, num_questions=1)
    assert result.slots[0].key_points == ("generators", "GIL", "context managers")


def test_parse_plan_cleans_caps_and_dedupes_key_points():
    points = ["  a  ", "A", "", "b", "c", "d", "e", "f", "g"]  # dupes/blanks + overflow
    extracted = {"slots": [{"skill": "x", "intent": "y", "key_points": points}]}
    result = plan.parse_plan(extracted, PROFILE, num_questions=1)
    kp = result.slots[0].key_points
    assert kp[0] == "a" and "A" not in kp  # trimmed + case-insensitive dedupe
    assert "" not in kp
    assert len(kp) <= plan._MAX_KEY_POINTS


def test_parse_plan_missing_key_points_defaults_empty():
    result = plan.parse_plan({"slots": [_slot("Python")]}, PROFILE, num_questions=1)
    assert result.slots[0].key_points == ()


def test_padded_slots_have_no_key_points():
    result = plan.parse_plan({"slots": []}, PROFILE, num_questions=2)
    assert all(s.key_points == () for s in result.slots)


def test_key_points_roundtrip_through_dict():
    extracted = {
        "slots": [{"skill": "Go", "intent": "z", "key_points": ["goroutines", "channels"]}]
    }
    result = plan.parse_plan(extracted, PROFILE, num_questions=1)
    assert plan.InterviewPlan.from_dict(result.to_dict()) == result
