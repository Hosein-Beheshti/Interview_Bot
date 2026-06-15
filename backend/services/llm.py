import anthropic
from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings
from logger import logger
from services import job_profile as job_profile_service
from services import rubric as rubric_service
from services.job_profile import JobProfile
from services.rubric import Dimension

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)

_SCORE_SYSTEM = (
    "You are an expert interview evaluator. Given the job context, the question, "
    "and the candidate's answer, score the answer honestly against every rubric "
    "dimension using the submit_score tool.\n\n"
)


def _trim_to_context_limit(messages: list[dict], system: str) -> list[dict]:
    """Drop oldest messages when total input chars approach the context limit."""
    trimmed = list(messages)
    total = sum(len(m["content"]) for m in trimmed) + len(system)
    while total > settings.max_context_chars and len(trimmed) > 1:
        removed = trimmed.pop(0)
        total -= len(removed["content"])
        logger.warning("Context limit: dropped oldest message to fit within budget")
    return trimmed


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def chat(messages: list[dict], system: str) -> str:
    safe_messages = _trim_to_context_limit(messages, system)
    response = await client.messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=system,
        messages=safe_messages,
    )
    if not response.content or response.content[0].type != "text":
        raise ValueError(f"Unexpected chat response: stop_reason={response.stop_reason}")
    return response.content[0].text


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def score(
    question: str,
    answer: str,
    profile: JobProfile,
    rubric: tuple[Dimension, ...] = rubric_service.DEFAULT_RUBRIC,
) -> dict:
    """Score an answer against the rubric via forced tool use — guaranteed schema."""
    system = _SCORE_SYSTEM + rubric_service.describe_rubric(rubric)
    messages = [
        {
            "role": "user",
            "content": (
                f"{job_profile_service.build_context(profile)}\n\n"
                f"Interview question: {question}\n"
                f"Candidate's answer: {answer}"
            ),
        }
    ]
    response = await client.messages.create(
        model=settings.model,
        max_tokens=400,
        system=system,
        tools=[rubric_service.build_score_tool_schema(rubric)],
        tool_choice={"type": "tool", "name": "submit_score"},
        messages=messages,
    )
    return _require_tool_use(response, "submit_score")


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def extract_job_profile(job_context: str) -> dict:
    """Extract a structured job profile from free-text context via forced tool use."""
    response = await client.messages.create(
        model=settings.model,
        max_tokens=500,
        system=job_profile_service.EXTRACT_SYSTEM,
        tools=[job_profile_service.EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "submit_job_profile"},
        messages=[{"role": "user", "content": job_context}],
    )
    return _require_tool_use(response, "submit_job_profile")


def _require_tool_use(response, tool_name: str) -> dict:
    """Return the input of the named tool_use block, or raise if absent."""
    block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == tool_name),
        None,
    )
    if block is None:
        raise ValueError(
            f"Tool '{tool_name}' not invoked: stop_reason={response.stop_reason}"
        )
    return block.input
