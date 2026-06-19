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
    # Maximum follow-up turns allowed per main question (probing a shallow answer
    # or simplifying after an "I don't know"). Follow-ups never consume a main
    # question slot; this caps how long the interview can dwell on one topic.
    max_followups_per_question: int = 1
    # Fallback role used when no job context is provided or extraction fails.
    default_role: str = "Software Engineer"
    # ~150K tokens — safety net for large CVs; well within Haiku's 200K context limit
    max_context_chars: int = 600_000

    model_config = {"env_file": ".env"}


settings = Settings()
