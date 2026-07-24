"""Prompt-byte freeze — the corollary that assembled prompts are outputs too.

Two layers together pin every prompt the system builds:

  * Pure builders — byte-exact snapshots of each prompt-assembly function with
    fixed representative inputs. Fast, no cassettes.
  * Assembled request stream — under REPLAY, capture the exact
    cache_prefix/system/messages of every request that flows through the
    transport waist during a real interview, and snapshot the ordered stream.
    This pins the true bytes sent to the provider, including the scorer's user
    message + reference block and the stable+turn concatenation.

Reordering a section or changing whitespace in any prompt fails these loudly and
requires an explicit `UPDATE_SNAPSHOTS=1`. (Replay hashing already turns prompt
drift into a `CassetteMiss`; these snapshots make the failure explicit and
readable instead of an opaque hash miss.)
"""
from __future__ import annotations

import asyncio
import json

from fixtures.scenarios import run_scenario, scenario_by_name

from interview_bot.domain import profile, rubric
from interview_bot.domain.plan import PlanSlot
from interview_bot.domain.profile import JobProfile
from interview_bot.llm import transport
from interview_bot.prompts import interviewer as prompt
from interview_bot.prompts import plan as plan_prompt
from interview_bot.prompts import profile as profile_prompt
from interview_bot.prompts import scoring as score_prompt

from ._snapshot import assert_json_snapshot, assert_snapshot

# A profile that exercises every optional branch of build_context.
_PROFILE = JobProfile(
    role="Senior Backend Engineer",
    company="Acme Payments",
    seniority="senior",
    key_skills=("Python", "PostgreSQL", "Kafka", "idempotency"),
    focus_areas=("distributed systems", "observability"),
)

_CV_CONTEXT = (
    "Relevant excerpts from the candidate's CV:\n"
    "[1] (Experience) Built the invoicing service on FastAPI + PostgreSQL.\n"
    "[2] (Skills) Kafka, Redis, OpenTelemetry, property-based testing."
)

_SLOT = PlanSlot(
    skill="idempotency in payment webhooks",
    intent="probe how they prevent duplicate charges under retries.",
    difficulty="advanced",
    key_points=("dedupe key scope", "unique constraint", "stored response"),
)


# --------------------------------------------------------------------------- #
# Layer 1: pure prompt-assembly functions.
# --------------------------------------------------------------------------- #
def test_snapshot_stable_prompt_without_cv():
    assert_snapshot(
        "stable_prompt_no_cv",
        prompt.build_stable_prompt(_PROFILE, num_questions=5, cv_context=""),
    )


def test_snapshot_stable_prompt_with_cv():
    assert_snapshot(
        "stable_prompt_with_cv",
        prompt.build_stable_prompt(_PROFILE, num_questions=5, cv_context=_CV_CONTEXT),
    )


def test_snapshot_turn_instructions():
    parts = {
        "main_q1": prompt.turn_instruction(prompt.MODE_MAIN, question_number=1),
        "main_q3": prompt.turn_instruction(prompt.MODE_MAIN, question_number=3),
        "main_with_slot": prompt.turn_instruction(
            prompt.MODE_MAIN, question_number=2, slot=_SLOT
        ),
        "follow_up_deepen": prompt.turn_instruction(
            prompt.MODE_FOLLOW_UP,
            follow_up_kind=prompt.FOLLOW_UP_DEEPEN,
            current_topic="Question 1: How do you design an idempotency scheme?",
        ),
        "follow_up_simplify": prompt.turn_instruction(
            prompt.MODE_FOLLOW_UP,
            follow_up_kind=prompt.FOLLOW_UP_SIMPLIFY,
            current_topic="Question 1: How do you design an idempotency scheme?",
        ),
    }
    rendered = "\n\n".join(f"### {k}\n{v}" for k, v in parts.items())
    assert_snapshot("turn_instructions", rendered)


def test_snapshot_job_context_block():
    assert_snapshot("job_context", profile.build_context(_PROFILE))


def test_snapshot_rubric_description():
    assert_snapshot("rubric_description", rubric.describe_rubric())


def test_snapshot_score_output_format():
    assert_json_snapshot("score_output_format", rubric.build_score_format())


def test_snapshot_constant_system_prompts():
    constants = {
        "score_system": score_prompt.SCORE_SYSTEM,
        "score_cache_prefix": score_prompt.SCORE_CACHE_PREFIX,
        "profile_extract_system": profile_prompt.EXTRACT_SYSTEM,
        "plan_extract_system": plan_prompt.EXTRACT_SYSTEM,
    }
    rendered = "\n\n".join(f"### {k}\n{v}" for k, v in constants.items())
    assert_snapshot("constant_system_prompts", rendered)


# --------------------------------------------------------------------------- #
# Layer 2: the exact bytes sent through the transport waist during a real run.
# --------------------------------------------------------------------------- #
def _render_request(index: int, request: dict) -> str:
    lines = [f"===== [{index}] {request['kind']} ====="]
    prefix = request.get("cache_prefix")
    lines.append("----- cache_prefix -----")
    lines.append(prefix if prefix else "(none)")
    lines.append("----- system -----")
    lines.append(request.get("system") if request.get("system") else "(empty)")
    lines.append("----- messages -----")
    for m in request.get("messages", []):
        lines.append(f"[{m['role']}]")
        lines.append(m["content"])
    schema = request.get("schema")
    if schema is not None:
        lines.append("----- schema -----")
        lines.append(json.dumps(schema, sort_keys=True, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def test_snapshot_assembled_request_stream(monkeypatch):
    """Freeze the ordered prompt bytes actually sent during one interview."""
    captured: list[dict] = []
    original = transport.call

    async def _spy(kind, request, live, **kwargs):
        captured.append(request)
        return await original(kind, request, live, **kwargs)

    monkeypatch.setattr(transport, "call", _spy)

    asyncio.run(run_scenario(scenario_by_name("ml-engineer")))

    # Embedding requests carry no natural-language prompt and are large; the
    # prompt-bytes freeze is about what the LLM sees, so keep LLM requests only.
    llm_requests = [r for r in captured if r["kind"].startswith("llm.")]
    stream = "\n\n".join(
        _render_request(i, r) for i, r in enumerate(llm_requests)
    )
    assert_snapshot("assembled_request_stream_ml_engineer", stream)
