"""Terminal harness for running a full interview without the web/DB/UI stack.

Drives the real interview engine (`services.interview.orchestration.run_turn`)
against an in-memory session, so you can iterate on prompts, scoring, and the
chosen LLM provider straight from the shell:

    python -m interview_cli                              # fully interactive
    python -m interview_cli --cv "../My_CV.pdf"          # supply a CV up front
    python -m interview_cli --role "ML Engineer" -n 4    # skip the prompts

What it intentionally skips vs. production: no Postgres, no HTTP, and no vector
retrieval. Short CVs (<= settings.cv_full_text_max_chars) are fed to the model in
full — the same path production uses for them — so for a typical 1-2 page CV this
exercises the identical logic. A very long CV would normally fall back to
pgvector retrieval; here it is simply truncated, with a warning.

The session object is a transient SQLAlchemy model instance that is never added to
a database; `run_turn` only mutates it in memory, which is all we need.
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from logger import logger
from models.interview import InterviewSession
from services import session as session_service
from services.integrations import cv_parser
from services.interview import job_profile, orchestration
from services.observability import observe_turn, shutdown as observability_shutdown

# ANSI colors — purely cosmetic; harmless if the terminal ignores them.
BOLD, DIM, CYAN, GREEN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[33m", "\033[0m",
)


def _load_cv(path_str: str) -> tuple[str, str] | None:
    """Parse a CV file into (filename, text), or return None on any failure."""
    path = Path(path_str).expanduser()
    if not path.is_file():
        print(f"{YELLOW}CV not found: {path}{RESET}")
        return None
    try:
        parsed = cv_parser.parse(path.name, path.read_bytes())
    except cv_parser.CVParseError as e:
        print(f"{YELLOW}Could not parse CV: {e}{RESET}")
        return None
    if parsed.char_count > settings.cv_full_text_max_chars:
        print(
            f"{YELLOW}CV is large ({parsed.char_count} chars); truncating to "
            f"{settings.cv_full_text_max_chars} for this terminal run "
            f"(production would use vector retrieval).{RESET}"
        )
        return parsed.filename, parsed.text[: settings.cv_full_text_max_chars]
    print(f"{DIM}Loaded CV '{parsed.filename}' ({parsed.char_count} chars).{RESET}")
    return parsed.filename, parsed.text


def _new_session(
    session_id: str, profile, num_questions: int, cv: tuple[str, str] | None, interview_plan
) -> InterviewSession:
    """Build a transient, never-persisted session seeded like a fresh interview.

    Column defaults are applied by SQLAlchemy at INSERT time, not at construction,
    so every field the engine reads must be set explicitly here. The id is supplied
    by the caller so the same value can tag the run's traces.
    """
    filename, full_text = cv if cv else (None, None)
    return InterviewSession(
        session_id=session_id,
        role=profile.role,
        status="created",
        num_questions=num_questions,
        messages=[],
        answers_given=0,
        questions_asked=0,
        followups_on_current=0,
        scores=[],
        is_complete=False,
        created_at=datetime.now(timezone.utc),
        cv_filename=filename,
        cv_full_text=full_text,
        cv_indexed_at=datetime.now(timezone.utc) if cv else None,
        job_profile=profile.to_dict(),
        interview_plan=interview_plan.to_dict() if interview_plan else None,
    )


def _print_plan(interview_plan) -> None:
    """Show the upfront coverage blueprint the interviewer will follow."""
    print(f"\n{BOLD}{CYAN}══ Interview plan ({len(interview_plan.slots)} questions) ══{RESET}")
    for i, slot in enumerate(interview_plan.slots, start=1):
        print(f"{BOLD}  Q{i}.{RESET} {slot.skill} {DIM}[{slot.difficulty}]{RESET}")
        print(f"{DIM}       {slot.intent}{RESET}")


def _print_score(score) -> None:
    """Render the score for the answer just given."""
    dims = "  ".join(f"{k}={v}" for k, v in score.dimensions.items())
    print(f"\n{DIM}── score for your answer ──{RESET}")
    print(f"{DIM}overall={score.overall}/10  [{score.answer_type}]  {dims}{RESET}")
    for s in score.strengths:
        print(f"{GREEN}  + {s}{RESET}")
    for s in score.improvements:
        print(f"{YELLOW}  - {s}{RESET}")


def _print_summary(summary: dict) -> None:
    print(f"\n{BOLD}{CYAN}══ Interview complete ══{RESET}")
    for key, value in summary.items():
        print(f"{BOLD}{key}{RESET}: {value}")


async def _build_profile(role: str | None, job_context: str | None):
    if job_context:
        print(f"{DIM}Extracting a job profile from the description…{RESET}")
        return await session_service.build_profile(job_context)
    return job_profile.minimal(role or settings.default_role)


async def run_interview(role, job_context, num_questions, cv) -> None:
    session_id = f"cli-{uuid.uuid4().hex[:8]}"

    # Group the setup-time LLM calls (profile extraction, plan generation) under one
    # trace tagged with the session id — mirrors the web's `session_create` trace.
    async with observe_turn("session_create", session_id=session_id, metadata={"source": "cli"}):
        profile = await _build_profile(role, job_context)
        print(f"{DIM}Designing the interview plan…{RESET}")
        interview_plan = await session_service.build_plan(profile, num_questions)

    session = _new_session(session_id, profile, num_questions, cv, interview_plan)

    print(f"\n{BOLD}Role:{RESET} {profile.role}   {BOLD}Questions:{RESET} {num_questions}")
    print(f"{DIM}Provider: {settings.llm_provider} ({_active_model()}).  "
          f"Type your answers; 'quit' to stop early.{RESET}")

    if interview_plan:
        _print_plan(interview_plan)
    else:
        print(f"{YELLOW}No plan generated — interviewer will self-select topics.{RESET}")
    print()

    # The opening turn poses Q1 regardless of message content (the engine treats
    # the first message as the kickoff), mirroring how the UI starts a session.
    message = "Hello, I'm ready to begin the interview."
    while True:
        # One trace per engine turn, tagged with the session id — mirrors the web's
        # `interview_turn` trace. Display and user think-time stay outside the span,
        # so its latency reflects engine work only.
        async with observe_turn(
            "interview_turn",
            session_id=session_id,
            input={"message": message},
            metadata={"source": "cli", "role": profile.role, "has_cv": session.has_cv},
        ):
            try:
                result = await orchestration.run_turn(session, message, profile)
            except orchestration.InterviewError as e:
                print(f"{YELLOW}Interview engine error: {e}{RESET}")
                return

        if result.score_data is not None:
            _print_score(result.score_data)

        print(f"\n{BOLD}{CYAN}Interviewer "
              f"(Q{session.question_number}/{num_questions}, {result.mode}):{RESET}")
        # Show which planned slot drove this turn. After run_turn, a main question
        # has already incremented questions_asked, so it indexes the slot just used;
        # follow-ups stay on that slot, and closing has none.
        if interview_plan and result.mode == "main_question":
            slot = interview_plan.slot_for(session.questions_asked)
            if slot:
                print(f"{DIM}   ↳ plan slot {session.questions_asked}: "
                      f"{slot.skill} [{slot.difficulty}]{RESET}")
        elif result.mode == "follow_up":
            print(f"{DIM}   ↳ follow-up (adapting to your last answer; "
                  f"does not consume a plan slot){RESET}")
        print(result.reply)

        if result.summary is not None:
            _print_summary(result.summary)
            return

        message = input(f"\n{BOLD}You:{RESET} ").strip()
        if message.lower() in {"quit", "exit"}:
            print(f"{DIM}Ended early.{RESET}")
            return
        if not message:
            message = "(no answer)"


def _active_model() -> str:
    return settings.gemini_model if settings.llm_provider == "gemini" else settings.model


def _prompt_inputs(args) -> tuple[str | None, str | None, int, tuple[str, str] | None]:
    """Fill any missing inputs interactively."""
    job_context = args.job_description
    role = args.role
    if not job_context and not role:
        jd = input("Paste a job description (or leave blank to enter a role): ").strip()
        if jd:
            job_context = jd
        else:
            role = input(f"Role [{settings.default_role}]: ").strip() or settings.default_role

    num = args.questions
    if num is None:
        raw = input(f"Number of questions [{settings.max_questions}]: ").strip()
        num = int(raw) if raw.isdigit() and int(raw) > 0 else settings.max_questions

    cv = None
    cv_path = args.cv
    if cv_path is None:
        cv_path = input("Path to CV (PDF/DOCX/TXT, blank to skip): ").strip().strip('"')
    if cv_path:
        cv = _load_cv(cv_path)

    return role, job_context, num, cv


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an interview in the terminal.")
    parser.add_argument("--cv", help="Path to a CV file (PDF/DOCX/TXT).")
    parser.add_argument("--role", help="Target role (skips the job-description prompt).")
    parser.add_argument("--job-description", help="Full job description text.")
    parser.add_argument("-n", "--questions", type=int, help="Number of main questions.")
    parser.add_argument("--quiet", action="store_true", help="Silence engine INFO logs.")
    args = parser.parse_args()

    if args.quiet:
        import logging

        logger.setLevel(logging.WARNING)

    role, job_context, num, cv = _prompt_inputs(args)
    try:
        asyncio.run(run_interview(role, job_context, num, cv))
    finally:
        # Short-lived process: flush buffered traces before exit so nothing is lost.
        observability_shutdown()


if __name__ == "__main__":
    main()
