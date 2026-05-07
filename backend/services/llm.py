from anthropic import AsyncAnthropic
from config import settings

client = AsyncAnthropic(api_key=settings.anthropic_api_key)


async def chat(messages: list[dict], system: str) -> str:
    response = await client.messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text
