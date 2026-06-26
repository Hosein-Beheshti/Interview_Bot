from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which LLM backend to use. Picks the provider implementation in
    # services/integrations/providers/. Add a new provider there and select it
    # here (or via the LLM_PROVIDER env var) — no other code changes needed.
    llm_provider: str = "anthropic"  # "anthropic" | "gemini"

    # Anthropic (Claude). Required only when llm_provider == "anthropic".
    anthropic_api_key: str = ""
    model: str = "claude-haiku-4-5-20251001"

    # Google Gemini. Required only when llm_provider == "gemini". A free key is
    # available from https://aistudio.google.com/apikey.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    # Gemini 2.5+ "flash"/"pro" are thinking models: by default they spend part of
    # the output-token budget on internal reasoning, which can truncate a bounded
    # structured-output response into invalid JSON. 0 disables thinking (valid for
    # flash models); -1 lets the model decide; a positive value caps the budget.
    # Scoring already reasons explicitly via the rubric's `critique` field, so
    # model-level thinking is redundant here.
    gemini_thinking_budget: int = 0

    database_url: str = "postgresql://postgres:postgres@localhost:5432/interview_bot"
    max_tokens: int = 300
    # Sampling temperature for interviewer question/reply generation. Lower =>
    # more deterministic and better at obeying the turn's constraints (stay on
    # topic for follow-ups, don't invent CV details); higher => more varied
    # phrasing. 0.7 balances adherence against repetitive-sounding questions.
    # (Answer scoring is separate and pinned to 0 for reproducibility.)
    generation_temperature: float = 0.7
    deepgram_api_key: str = ""
    voyage_api_key: str = ""
    embedding_model: str = "voyage-3-lite"
    embedding_dim: int = 512
    cv_max_bytes: int = 5 * 1024 * 1024
    rag_top_k: int = 4
    # CVs at or below this many characters (~3K tokens, ~2 pages) are sent to the
    # interviewer in full on every turn — best grounding, no retrieval query to
    # construct, and nearly free once the prompt prefix is cached. Larger CVs
    # would bloat the context, so they fall back to per-question vector retrieval.
    cv_full_text_max_chars: int = 12_000
    max_questions: int = 5
    # Maximum follow-up turns allowed per main question (probing a shallow answer
    # or simplifying after an "I don't know"). Follow-ups never consume a main
    # question slot; this caps how long the interview can dwell on one topic.
    max_followups_per_question: int = 1
    # Fallback role used when no job context is provided or extraction fails.
    default_role: str = "Software Engineer"
    # ~150K tokens — safety net for large CVs; well within Haiku's 200K context limit
    max_context_chars: int = 600_000

    # Observability (self-hosted Langfuse). Tracing is best-effort: when disabled
    # (the default) or misconfigured it is a no-op and never affects a request, so
    # local/dev/CI run untouched. Point host/keys at your self-hosted instance and
    # set langfuse_enabled=true to turn it on. Keys come from the Langfuse project
    # settings page.
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # On networks with a TLS-inspecting proxy (corporate Zscaler/Netskope, etc.),
    # outbound HTTPS is re-signed by a private root CA that Python's bundled
    # `certifi` does not trust, so API calls fail with CERTIFICATE_VERIFY_FAILED.
    # When true, route SSL verification through the OS trust store (where that root
    # CA already lives) via `truststore`. Best-effort: silently skipped if the
    # package isn't installed.
    use_system_trust_store: bool = True

    # `extra="ignore"`: tolerate unknown keys in .env (typos, vars for other
    # tools) instead of crashing at startup.
    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


def _enable_system_trust_store() -> None:
    """Make Python validate TLS against the OS trust store (corporate-proxy CAs).

    Imported and injected here, at config load, so it takes effect before any HTTP
    client (Anthropic, Gemini, Voyage, …) opens a connection.
    """
    if not settings.use_system_trust_store:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        # Package missing or injection unsupported — fall back to certifi.
        pass


_enable_system_trust_store()
