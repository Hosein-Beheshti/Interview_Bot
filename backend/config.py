from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    database_url: str = "postgresql://postgres:postgres@localhost:5432/interview_bot"
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 300
    deepgram_api_key: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
