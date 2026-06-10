from anthropic import AsyncAnthropic
from config import settings

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

_SCORE_TOOL = {
    "name": "submit_score",
    "description": "Score the candidate's last answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 1, "maximum": 10},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "improvements": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["score", "strengths", "improvements"],
    },
}

_SCORE_SYSTEM = (
    "You are an expert interview evaluator. "
    "Score the candidate's answer honestly and concisely using the submit_score tool."
)


async def chat(messages: list[dict], system: str) -> str:
    response = await client.messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text


async def score(question: str, answer: str, role: str) -> dict:
    """Dedicated scoring call using forced tool use — guaranteed schema."""
    messages = [
        {
            "role": "user",
            "content": (
                f"Role being interviewed for: {role}\n"
                f"Interview question: {question}\n"
                f"Candidate's answer: {answer}"
            ),
        }
    ]
    response = await client.messages.create(
        model=settings.model,
        max_tokens=200,
        system=_SCORE_SYSTEM,
        tools=[_SCORE_TOOL],
        tool_choice={"type": "tool", "name": "submit_score"},
        messages=messages,
    )
    return response.content[0].input
