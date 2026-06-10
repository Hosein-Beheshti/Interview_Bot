from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    database_url: str = "postgresql://postgres:postgres@localhost:5432/interview_bot"
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 300
    deepgram_api_key: str = ""
    voyage_api_key: str = ""
    embedding_model: str = "voyage-3-lite"
    embedding_dim: int = 512
    cv_max_bytes: int = 5 * 1024 * 1024
    rag_top_k: int = 4
    max_questions: int = 5

    model_config = {"env_file": ".env"}


settings = Settings()
