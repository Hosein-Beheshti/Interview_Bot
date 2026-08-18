from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which LLM backend to use. Picks the provider implementation in
    # interview_bot/llm/ (registry.py). Add a new provider there and select it
    # here (or via the LLM_PROVIDER env var) — no other code changes needed.
    llm_provider: str = "anthropic"  # "anthropic" | "gemini"

    # Anthropic (Claude). Required only when llm_provider == "anthropic".
    anthropic_api_key: str = ""
    model: str = "claude-haiku-4-5-20251001"

    # Model for interviewer turn generation (main questions and follow-ups).
    # Empty means "use `model`", which is the default and keeps one model for
    # everything.
    #
    # Generation is worth splitting out from the rest: it is the only output the
    # candidate reads, it is where a small model's drift shows up (unlabelled
    # questions, follow-ups that wander off topic), and it runs once per turn
    # rather than once per answer plus once per judgement. Scoring, judging, and
    # extraction stay on `model` — they are schema-constrained, so they are far
    # less sensitive to model strength, and they are the higher-volume calls.
    #
    # Set to e.g. "claude-sonnet-4-5" to interview on Sonnet while grading on
    # Haiku. The model name is part of a request's replay identity, so changing
    # it invalidates the interviewer cassettes and needs `make record`.
    generator_model: str = ""

    # Hard ceiling on a single provider HTTP call. Both SDKs default to ten
    # minutes, which is far longer than any turn should take and long enough for
    # a stalled call to pin the request's database connection (and, on /chat, the
    # interview row's lock) for the whole duration. Retries are layered on top,
    # so the worst case is roughly this value x the attempt count.
    llm_timeout_seconds: float = 60.0

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

    # ---- Connection pool ---------------------------------------------------
    # Managed Postgres (Railway et al.) closes connections that have been idle
    # for a while, and the pool has no way to notice: the next checkout hands
    # out a dead socket and the request fails with "server closed the connection
    # unexpectedly". `pool_pre_ping` costs one trivial round trip per checkout
    # and turns that class of error into a transparent reconnect; `pool_recycle`
    # retires connections before the server's own idle timeout can reach them.
    db_pool_pre_ping: bool = True
    db_pool_recycle_seconds: int = 1800
    # Sized against the database's connection limit, not the app's concurrency:
    # every worker process opens its own pool, so the real ceiling is
    # (workers x (pool_size + max_overflow)).
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # ---- Model output budgets ----------------------------------------------
    # Each of these is a `max_tokens`: a hard ceiling on one response's OUTPUT
    # tokens. The model is not told about the cap, so hitting it truncates
    # mid-sentence (`stop_reason: "max_tokens"`) rather than producing a shorter
    # well-formed answer — size each for the longest *legitimate* response, not
    # the typical one. None of these bound input; that is `max_context_chars`.
    #
    # This is the sharpest cost lever in the file: output bills at roughly 5x
    # input, and every one of these fires at least once per interview turn.
    #
    # CAUTION: each value is part of its call's replay identity — the request
    # hash in `llm/__init__.py` includes `max_tokens`. Changing one invalidates
    # the recorded cassettes for that call, and `llm.parse` /
    # `llm.generate_structured` have no cassette fallback, so a change there
    # breaks the offline suite until `make record`. Change these deliberately,
    # in their own commit.
    max_tokens: int = 300  # interviewer turn — the only text the candidate reads
    score_max_tokens: int = 700  # per-answer rubric scoring (critique + dimensions)
    plan_max_tokens: int = 1500  # interview blueprint, once per session
    judge_max_tokens: int = 400  # turn-quality judgement
    # Defaults for `llm.generate_structured` / `llm.parse` when a caller passes no
    # explicit budget. `pipeline/profile.py` is the one live caller that relies on
    # a default (`parse_max_tokens`), so this value is in recorded hashes too.
    structured_max_tokens: int = 400
    parse_max_tokens: int = 500

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
    # A *routing threshold*, not a limit: nothing is rejected for exceeding it.
    cv_full_text_max_chars: int = 12_000

    # ---- Interview shape ----------------------------------------------------
    max_questions: int = 5
    # Maximum follow-up turns allowed per main question (probing a shallow answer
    # or simplifying after an "I don't know"). Follow-ups never consume a main
    # question slot; this caps how long the interview can dwell on one topic.
    #
    # Together these bound the provider calls one interview can make:
    # `max_questions x (1 + max_followups_per_question)` turns, each costing a
    # score + judge + generate. Raising either multiplies the whole bill.
    max_followups_per_question: int = 1
    # Fallback role used when no job context is provided or extraction fails.
    default_role: str = "Software Engineer"
    # ~150K tokens — safety net for large CVs; well within Haiku's 200K context
    # limit. Enforced in `llm/provider.py` by dropping the oldest messages, so
    # exceeding it silently loses transcript history rather than erroring.
    max_context_chars: int = 600_000

    # ---- Request body size caps ---------------------------------------------
    # These bound the *characters* accepted in a single request field, not
    # tokens — a rough proxy (English averages ~4 chars/token) to keep one
    # request from blowing up prompt size / cost, not a real token budget.
    # Pydantic rejects an over-length field with 422 before any LLM call, DB
    # write, or session state is touched — the request never starts.
    job_context_max_chars: int = 8000
    chat_message_max_chars: int = 4000
    role_max_chars: int = 100
    # TTS input, not text an interviewer question ever approaches in length —
    # this exists to stop /speak being driven as an open-ended synthesis proxy.
    tts_text_max_chars: int = 2000

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
    # Under replay, let a free-text generation (`llm.generate`) fall back to the
    # cassette recorded for the same *conversation* when its exact request hash
    # misses. Editing interviewer prompt wording changes the request bytes and so
    # would otherwise miss every cassette, making a one-word prompt tweak cost a
    # full `make record` against the live APIs. The fallback keys on the fields a
    # prompt edit does not touch (provider, model, messages, sampling), so the
    # offline suite keeps exercising the server-owned logic — progression, label
    # repair, scoring, summary — while the prompt is in flux.
    #
    # Deliberately narrow: only `llm.generate`, whose recorded reply is just
    # plausible English. `llm.parse` and `llm.generate_structured` never fall back
    # — their recorded *shape* is the thing under test, so a miss there is a real
    # error. Off by default; the offline gate turns it on (see the Makefile).
    cassette_fallback: bool = False

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

    # Per-client-IP allowances. Each name here is referenced by exactly one
    # `Quota` in api/limits.py, which reads it at charge time — so changing one of
    # these via the environment needs no code change and no recomputed constant.
    sessions_per_hour_per_ip: int = 5
    turns_per_hour_per_ip: int = 60
    cv_uploads_per_hour_per_ip: int = 5
    transcriptions_per_hour_per_ip: int = 60
    tts_chars_per_day_per_ip: int = 20_000

    # Instance-wide daily model-token ceiling — the backstop that bounds spend no
    # matter how the per-IP limits are spread across addresses. Reaching it
    # returns 503 until the window rolls over. 0 disables the ceiling.
    #
    # WHAT IT COUNTS. Every token of every provider call, summed with the weights
    # below: input, output, cache reads, and cache writes. With the default
    # weights all at 1.0 it is a *volume* ceiling, not a bill — a cached input
    # token bills at ~0.1x but still counts as 1 here.
    #
    # SIZING. One 5-question interview makes up to
    # `max_questions x (1 + max_followups_per_question)` = 10 turns, each running
    # score + judge + generate, and every call resends the system prompt, CV, and
    # transcript. That is ~150-250K weighted tokens per completed interview even
    # though the actual Haiku 4.5 bill is only ~$0.10-0.20 (most of the input is a
    # cached prefix). So this default is ~20 interviews/day, ~$2-4/day worst case.
    #
    # The previous default of 150_000 was documented as "20-30 full interviews";
    # that was wrong by more than an order of magnitude — it did not cover one.
    # Measure your own figure in Langfuse before tuning, then set it here.
    daily_token_ceiling: int = 5_000_000

    # Relative weights applied to each token class when charging the ceiling
    # above. All 1.0 means "count raw volume", which is provider-agnostic and the
    # safe default. To make the ceiling track the *invoice* instead, set these to
    # your model's price ratios — for Haiku 4.5 ($1/MTok in, $5/MTok out, cache
    # reads ~0.1x input, cache writes ~1.25x) that is input 1.0, output 5.0,
    # cache_read 0.1, cache_write 1.25, and `daily_token_ceiling` then reads as
    # "input-token-equivalents per day" (~1M of them ≈ $1/day).
    #
    # Weighted totals are rounded down to whole units, so a sub-1.0 weight on a
    # small call can charge 0 — intended: cache reads are meant to be near-free.
    token_weight_input: float = 1.0
    token_weight_output: float = 1.0
    token_weight_cache_read: float = 1.0
    token_weight_cache_write: float = 1.0

    # Optional webhook (Slack incoming webhook, Discord, or anything accepting a
    # JSON {"text": ...} POST) notified the first time the daily token ceiling is
    # reached each day. Empty disables it — best-effort, never blocks a request.
    alert_webhook_url: str = ""
    # Kept short deliberately: this fires on the request that hit the ceiling, so
    # the caller waits on it before getting their 503.
    alert_webhook_timeout_seconds: float = 5.0

    # Whether to read the client IP from X-Forwarded-For. Required behind a proxy
    # or load balancer (Railway, Render, Fly, nginx), where the socket address is
    # the proxy's. Must stay false when the app is directly reachable: the header
    # is caller-supplied, so trusting it lets anyone reset their own rate limit.
    trust_proxy_headers: bool = False

    # How many proxies sit in front of this app. X-Forwarded-For is append-only,
    # so only the rightmost entries were written by infrastructure we control —
    # everything to the left of them is whatever the caller sent. Reading the
    # leftmost entry (the usual mistake) lets anyone mint a fresh rate-limit
    # identity per request by sending the header themselves. 1 is correct for a
    # single edge proxy such as Railway; raise it only if you add another hop.
    trusted_proxy_hops: int = 1

    # How long an interview session — transcript, scores, and the uploaded CV's
    # text and embeddings — is retained before the sweep erases it. Uploaded CVs
    # are personal data from people trying a public demo; keep the window short.
    # Applied by `scripts/purge_expired.py`, which is meant to run on a schedule.
    session_retention_days: int = 30

    # Browser origins allowed to call this API, comma-separated. The default is
    # local development only — a public deployment must set CORS_ORIGINS to its
    # frontend origin. "*" is accepted but disables the protection entirely.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Railway auto-injects this on every deploy (e.g. "production"); empty when
    # running locally or in CI. Used only to decide whether a still-default
    # CORS config is worth a loud startup warning — not a general env-name flag.
    railway_environment: str = ""

    # ---- Auth & credits ---------------------------------------------------
    # Google OAuth client id (Google Cloud Console → Credentials → OAuth client
    # ID). Checked as the ID token's audience — a token minted for a different
    # app is rejected even if otherwise genuine.
    google_client_id: str = ""

    # Credits granted once, at first login. 0 disables the free allowance.
    signup_credit_grant: int = 20

    # Credits debited to start one interview session. Covers the session's
    # speech synthesis too: a session asks a bounded number of questions, so the
    # audio it implies is bounded, and charging it here keeps the price
    # independent of how many requests the client splits each reply into.
    interview_session_credit_cost: int = 8

    # Credits debited per transcription request.
    transcription_credit_cost: int = 1

    # Kill switch: false skips every credit check (per-IP and global-token
    # limits still apply) — lets metering be turned off via env var alone, no
    # redeploy.
    require_credits_to_start_session: bool = True

    # Name of the HttpOnly cookie carrying the (hashed, server-side) session
    # token. Changing it invalidates every existing login at once.
    session_cookie_name: str = "interview_bot_session"

    # Days a login stays valid before the browser must sign in again.
    session_max_age_days: int = 30

    # `extra="ignore"`: tolerate unknown keys in .env (typos, vars for other
    # tools) instead of crashing at startup.
    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

_DEV_CORS_DEFAULT = "http://localhost:5173,http://localhost:3000"


def is_dev_cors_in_production(s: Settings) -> bool:
    """True if a Railway deploy is still running the dev CORS default or a wildcard."""
    if not s.railway_environment:
        return False
    return s.cors_origins.strip() == _DEV_CORS_DEFAULT or "*" in s.cors_origin_list


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
