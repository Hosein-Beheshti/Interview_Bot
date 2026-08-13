"""Interview-session setup flow.

Composes the async, LLM-backed steps that turn a pasted job description into a
persisted, ready-to-run session: extract the profile, design the plan, insert the
row. Plain persistence (fetch/insert) lives in
`interview_bot.persistence.sessions`; the extraction calls in
`interview_bot.pipeline.profile` / `interview_bot.pipeline.plan`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from interview_bot.config import settings
from interview_bot.domain.profile import minimal
from interview_bot.logger import logger
from interview_bot.persistence import sessions as store
from interview_bot.persistence import users as user_store
from interview_bot.persistence.models import InterviewSession
from interview_bot.pipeline.plan import build_plan
from interview_bot.pipeline.profile import build_profile
from interview_bot.telemetry import observe_turn, set_session


class InsufficientCreditsError(RuntimeError):
    """Raised when the caller does not have enough credits to start a session.

    Carries both numbers so the route can say how short the caller is; the
    HTTP wording itself belongs to `api.credits`, not here.
    """

    def __init__(self, needed: int, balance: int) -> None:
        super().__init__(f"needs {needed} credits, balance {balance}")
        self.needed = needed
        self.balance = balance


async def create_from_context(
    db: Session,
    *,
    job_context: str | None,
    role: str | None,
    user_id: str,
    num_questions: int | None = None,
) -> InterviewSession:
    """Create a session from a pasted job description, or a role-only fallback.

    Wrapped in a trace so the setup-time LLM calls (profile extraction, plan
    generation) are grouped and, once the session id exists, tagged onto it.

    Debits the session-creation credit cost before doing any LLM work: this is
    the same choke point `POST /sessions` uses via `credits.require(...)`, but
    `/chat` and `/cv/upload` only create a session *sometimes* (when no
    `session_id` was supplied), so they can't use a blanket route dependency
    without wrongly charging every ordinary turn — this function is the one
    place both of those lazy-create paths funnel through.

    Respects `require_credits_to_start_session` the same way `credits.require`
    does, so the kill switch turns off metering everywhere a session can be
    created, not just at `POST /sessions`.
    """
    charged = 0
    if settings.require_credits_to_start_session:
        cost = settings.interview_session_credit_cost
        if user_store.debit_credits(db, user_id, cost) is None:
            account = user_store.get(db, user_id)
            raise InsufficientCreditsError(cost, account.credits if account else 0)
        charged = cost

    try:
        return await _build_and_store(
            db,
            job_context=job_context,
            role=role,
            user_id=user_id,
            num_questions=num_questions,
        )
    except Exception:
        # The debit committed before this work started (it has to — see
        # `users.refund_credits`), so a failure here would otherwise bill the
        # caller for a session that does not exist. Give the credits back before
        # the error propagates. Best-effort: a failed refund must not replace the
        # original error, which is the one that explains what actually broke.
        if charged:
            try:
                user_store.refund_credits(db, user_id, charged)
            except Exception as refund_error:
                logger.error(
                    f"Credit refund failed | user={user_id} | credits={charged} | "
                    f"error={refund_error}"
                )
        raise


async def _build_and_store(
    db: Session,
    *,
    job_context: str | None,
    role: str | None,
    user_id: str,
    num_questions: int | None,
) -> InterviewSession:
    """The paid-for work itself: extract, plan, persist. Split out so the credit
    refund above wraps every failure path in one place."""
    resolved_questions = num_questions or settings.max_questions
    async with observe_turn("session_create", metadata={"has_job_context": bool(job_context)}):
        if job_context:
            profile = await build_profile(job_context)
        else:
            profile = minimal(role or settings.default_role)
        interview_plan = await build_plan(profile, resolved_questions)
        session = store.create(
            db,
            profile=profile,
            num_questions=resolved_questions,
            job_context=job_context,
            interview_plan=interview_plan,
            user_id=user_id,
        )
        set_session(session.session_id)
        return session
