from interview_bot.domain import profile as jp
from interview_bot.prompts.profile import ProfileExtraction


def test_parse_profile_full():
    raw = {
        "role": "Senior Backend Engineer",
        "company": "Stripe",
        "seniority": "senior",
        "key_skills": ["Python", "Postgres", "API design"],
        "focus_areas": ["system design", "scalability"],
    }
    profile = jp.parse_profile(raw, fallback_role="Engineer")
    assert profile.role == "Senior Backend Engineer"
    assert profile.company == "Stripe"
    assert profile.key_skills == ("Python", "Postgres", "API design")
    assert profile.focus_areas == ("system design", "scalability")


def test_parse_profile_uses_fallback_role_when_missing():
    profile = jp.parse_profile({"key_skills": [], "focus_areas": []}, fallback_role="Engineer")
    assert profile.role == "Engineer"


def test_parse_profile_dedupes_and_caps_lists():
    raw = {
        "role": "Dev",
        "key_skills": ["Python", "python", "  Python  ", "Go"],
        "focus_areas": [],
    }
    profile = jp.parse_profile(raw, fallback_role="Dev")
    assert profile.key_skills == ("Python", "Go")


def test_parse_profile_ignores_blank_company():
    profile = jp.parse_profile(
        {"role": "Dev", "company": "   ", "key_skills": [], "focus_areas": []},
        fallback_role="Dev",
    )
    assert profile.company is None


def test_roundtrip_to_from_dict():
    profile = jp.JobProfile(
        role="Dev", company="Acme", key_skills=("a", "b"), focus_areas=("c",)
    )
    assert jp.JobProfile.from_dict(profile.to_dict()) == profile


def test_minimal_profile():
    profile = jp.minimal("Data Scientist")
    assert profile.role == "Data Scientist"
    assert profile.key_skills == ()


def test_profile_extraction_shape():
    # The Pydantic extraction model is the single source of truth for the shape.
    fields = ProfileExtraction.model_fields
    assert set(fields) == {"role", "company", "seniority", "key_skills", "focus_areas"}
    # role is required; company/seniority are optional
    assert fields["role"].is_required()
    assert not fields["company"].is_required()
    assert not fields["seniority"].is_required()


def test_profile_extraction_normalizes_via_parse_profile():
    # An extracted model round-trips through parse_profile for normalization.
    extracted = ProfileExtraction(role="Dev", key_skills=["Python", "python"])
    profile = jp.parse_profile(extracted.model_dump(), fallback_role="Engineer")
    assert profile.role == "Dev"
    assert profile.key_skills == ("Python",)


def test_build_context_includes_fields():
    profile = jp.JobProfile(
        role="Backend Engineer",
        company="Stripe",
        key_skills=("Python",),
        focus_areas=("system design",),
    )
    context = jp.build_context(profile)
    assert "Backend Engineer" in context
    assert "Stripe" in context
    assert "Python" in context
    assert "system design" in context
