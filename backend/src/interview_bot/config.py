from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which LLM backend to use. Picks the provider implementation in
    # interview_bot/llm/ (registry.py). Add a new provider there and select it
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
    # One recorded answer, not a media file. Deepgram bills by audio duration, so
    # this is a cost bound as much as a request-size bound.
    audio_max_bytes: int = 10 * 1024 * 1024
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

    # Model-call transport mode — the record/replay seam for every network call
    # to a model provider (LLM, embeddings, speech):
    #   "live"    hit the provider APIs (production default)
    #   "record"  hit the APIs AND write (request, response, latency, token
    #             usage) to a cassette file keyed by the request's content hash
    #   "replay"  serve recorded responses from disk by request hash — no
    #             network, no API keys; a missing cassette is a hard error
    transport_mode: str = "live"  # "live" | "record" | "replay"
    # Where cassettes live. A relative path is anchored at the backend root so
    # the same value works from any working directory.
    cassette_dir: str = "cassettes"

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

    # ---- Admission control -------------------------------------------------
    # Every endpoint below is unauthenticated by design (a public demo), and each
    # one spends money with a third party per call. These are the caps that make
    # publishing the URL safe. Enforced in api/limits.py; set false only for
    # local development.
    rate_limit_enabled: bool = True

    # Per-client-IP allowances.
    sessions_per_hour_per_ip: int = 5
    turns_per_hour_per_ip: int = 60
    cv_uploads_per_hour_per_ip: int = 5
    transcriptions_per_hour_per_ip: int = 60
    tts_chars_per_day_per_ip: int = 20_000

    # Instance-wide daily model-token ceiling — the backstop that bounds the bill
    # no matter how the per-IP limits are spread across addresses. Counts every
    # token in and out, across all providers and operations. Reaching it returns
    # 503 until the window rolls over. 0 disables the ceiling.
    #
    # The default is deliberately conservative: ~150K tokens/day is roughly
    # $0.20/day on Haiku 4.5 at a 90/10 input/output split, or about 20-30 full
    # interviews. A forgotten environment variable should fail toward a small
    # bill, not an unbounded one — raise it once you know what real traffic costs.
    daily_token_ceiling: int = 150_000

    # Whether to read the client IP from X-Forwarded-For. Required behind a proxy
    # or load balancer (Railway, Render, Fly, nginx), where the socket address is
    # the proxy's. Must stay false when the app is directly reachable: the header
    # is caller-supplied, so trusting it lets anyone reset their own rate limit.
    trust_proxy_headers: bool = False

    # How long an interview session — transcript, scores, and the uploaded CV's
    # text and embeddings — is retained before the sweep erases it. Uploaded CVs
    # are personal data from people trying a public demo; keep the window short.
    # Applied by `scripts/purge_expired.py`, which is meant to run on a schedule.
    session_retention_days: int = 30

    # Browser origins allowed to call this API, comma-separated. The default is
    # local development only — a public deployment must set CORS_ORIGINS to its
    # frontend origin. "*" is accepted but disables the protection entirely.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # `extra="ignore"`: tolerate unknown keys in .env (typos, vars for other
    # tools) instead of crashing at startup.
    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


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
