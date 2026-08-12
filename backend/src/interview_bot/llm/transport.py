"""Record/replay waist for every model-provider network call.

Every call to a model provider — LLM generation (`llm.py`), embeddings
(`embeddings.py`), speech (`speech.py`) — funnels through `call()`. Three modes,
selected by `settings.transport_mode`:

    live    invoke the provider; nothing recorded (production default).
    record  invoke the provider AND write (request, response, latency, token
            usage) to a cassette file keyed by the request's content hash.
    replay  serve the recorded response for the request hash from disk. No
            network, no API keys; a missing cassette raises `CassetteMiss`.

The request dict is canonicalized (sorted-key compact JSON) and SHA-256 hashed;
the hash is the cassette's identity. Any change to the assembled request — one
byte of prompt text included — therefore misses its cassette and fails loudly
under replay, which is exactly the property the behavior-freeze tests rely on.

That strictness prices every prompt edit at a paid re-record, which is the right
trade while proving a refactor changed nothing and the wrong one while tuning the
interviewer. `settings.cassette_fallback` relaxes it for free-text generation
only: on a miss, replay the cassette for the same conversation. See
`_replay_fallback` — the exact-hash path is untouched, so a run with the fallback
off still proves the strict property.

Cassettes are versioned fixture files (JSON, one per request) meant to be
committed. Callers whose live result isn't JSON (a Pydantic model, raw audio
bytes) pass `encode`/`decode` to map between the result and its cassette form;
live and record always return the provider's original result untouched.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from interview_bot.config import settings
from interview_bot.logger import logger
from interview_bot.telemetry import capture_generation_usage, record_generation_usage

CASSETTE_VERSION = 1


def _project_root() -> Path:
    """The backend project root (the dir holding pyproject.toml).

    Cassettes are a repo-level fixture asset living beside `fixtures/`, not
    packaged data, so a relative `cassette_dir` is anchored here rather than at a
    fixed depth from this module — robust to where the module sits in the package.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return here.parents[3]  # backend/ (src/interview_bot/llm/transport.py)


class CassetteMiss(LookupError):
    """Replay mode was asked for a request with no recorded cassette."""


def cassette_dir() -> Path:
    configured = Path(settings.cassette_dir)
    return configured if configured.is_absolute() else _project_root() / configured


def canonical_request(request: dict) -> str:
    """The canonical byte form of a request: sorted keys, compact separators."""
    return json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_hash(request: dict) -> str:
    return hashlib.sha256(canonical_request(request).encode("utf-8")).hexdigest()


# --- The prompt-iteration escape hatch ------------------------------------
# Exact-hash replay is what freezes behavior, but it also means one edited word
# of interviewer guidance misses every cassette and demands a paid re-record.
# When `settings.cassette_fallback` is on, a missed `llm.generate` falls back to
# the cassette recorded for the same *conversation*, so prompt wording can move
# freely while the offline suite still exercises everything downstream of the
# reply. Narrow on purpose — see the `cassette_fallback` note in `config.py`.

_FALLBACK_KINDS = frozenset({"llm.generate"})

# The request fields a prompt edit rewrites. Everything else — provider, model,
# messages, sampling params — must still match exactly for a cassette to be a
# candidate at all.
_PROMPT_FIELDS = frozenset({"system", "cache_prefix"})

# Matching on the non-prompt fields alone is not enough: on the opening turn every
# fixture has the same (empty) message list, and what distinguishes them — role,
# job context, CV — lives entirely in the prompt. So candidates are ranked by how
# similar their prompt text is to the one being replayed. A reworded rule leaves
# it near-identical; a different role scores nowhere close. Below this ratio the
# best candidate is a different conversation, and missing loudly beats replaying
# someone else's interview.
_FALLBACK_MIN_RATIO = 0.75


def _replay_identity(request: dict) -> str:
    """The part of a request that must match exactly for a fallback candidate."""
    return canonical_request({k: v for k, v in request.items() if k not in _PROMPT_FIELDS})


def _prompt_text(request: dict) -> str:
    """The prompt-bearing text of a request, as one comparable string."""
    return "\n".join(str(request.get(field) or "") for field in sorted(_PROMPT_FIELDS))


def _nearest_cassette(kind: str, request: dict) -> tuple[Path | None, float]:
    """The recorded cassette whose prompt most resembles this request's.

    Scanned fresh on every miss rather than cached: the dir is a few dozen small
    files, this runs only on a miss, and a cache left stale by `make record`
    would be a genuinely confusing thing to debug.
    """
    identity = _replay_identity(request)
    prompt = _prompt_text(request)
    best: Path | None = None
    best_ratio = 0.0

    # Sorted so that equally-similar candidates resolve the same way every run —
    # the fallback must not make replay depend on directory order.
    for path in sorted(cassette_dir().glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidate = entry.get("request")
        if entry.get("kind") != kind or not isinstance(candidate, dict):
            continue
        if _replay_identity(candidate) != identity:
            continue
        ratio = SequenceMatcher(None, prompt, _prompt_text(candidate)).ratio()
        if ratio > best_ratio:
            best, best_ratio = path, ratio

    return best, best_ratio


async def call(
    kind: str,
    request: dict,
    live: Callable[[], Awaitable[Any]],
    *,
    encode: Callable[[Any], Any] = lambda result: result,
    decode: Callable[[Any], Any] = lambda payload: payload,
) -> Any:
    """Run one provider call through the waist.

    `request` must contain every input that determines the provider's response
    (provider, model, messages, sampling params, …) and be JSON-serializable —
    it is the replay identity. `live` is a zero-arg async callable so that in
    replay mode no provider client (and no API key) is ever constructed.
    """
    mode = settings.transport_mode
    if mode == "live":
        return await live()
    if mode == "replay":
        return decode(_replay(kind, request))
    if mode == "record":
        return await _record(kind, request, live, encode)
    raise ValueError(
        f"Unknown transport_mode={mode!r}. Expected 'live', 'record', or 'replay'."
    )


async def call_streaming(
    kind: str,
    request: dict,
    live: Callable[[], AsyncIterator[str]],
) -> AsyncIterator[str]:
    """Run one streaming provider call through the waist, yielding text chunks.

    Streaming is treated as a delivery detail of an otherwise ordinary call: the
    `request` passed here is byte-identical to the non-streaming form, so it
    hashes to the same cassette. A cassette recorded either way replays either
    way, and the frozen outputs are unaffected by which transport a caller picks.

    In replay the recorded reply is re-chunked deterministically — the pieces are
    arbitrary, their concatenation is not.
    """
    mode = settings.transport_mode
    if mode == "live":
        async for chunk in live():
            yield chunk
        return
    if mode == "replay":
        for chunk in _rechunk(_replay(kind, request)):
            yield chunk
        return
    if mode == "record":
        async for chunk in _record_streaming(kind, request, live):
            yield chunk
        return
    raise ValueError(
        f"Unknown transport_mode={mode!r}. Expected 'live', 'record', or 'replay'."
    )


# Replay chunk size. Only affects how a recorded reply is sliced on the way out;
# the concatenation is identical regardless, so no test depends on this value.
REPLAY_CHUNK_CHARS = 24


def _rechunk(text: Any) -> list[str]:
    """Slice a recorded reply into stream-sized pieces."""
    if not isinstance(text, str):
        raise CassetteMiss(
            f"Cassette holds a {type(text).__name__} response, which cannot be "
            f"streamed as text. Streaming replay expects a recorded string reply."
        )
    return [text[i : i + REPLAY_CHUNK_CHARS] for i in range(0, len(text), REPLAY_CHUNK_CHARS)]


async def _record_streaming(
    kind: str,
    request: dict,
    live: Callable[[], AsyncIterator[str]],
) -> AsyncIterator[str]:
    """Stream from the provider, accumulating the full reply into a cassette.

    Writes the same entry shape as a non-streaming recording, so cassettes stay
    interchangeable between the two paths.
    """
    chunks: list[str] = []
    with capture_generation_usage() as usage:
        started = time.perf_counter()
        async for chunk in live():
            chunks.append(chunk)
            yield chunk
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

    _write_cassette(kind, request, "".join(chunks), latency_ms, usage)


def _cassette_path(hash_: str) -> Path:
    return cassette_dir() / f"{hash_[:16]}.json"


def _miss(kind: str, hash_: str, extra: str = "") -> CassetteMiss:
    return CassetteMiss(
        f"No cassette for {kind} request (hash {hash_[:16]}) in {cassette_dir()}. "
        f"The assembled request differs from every recorded one — either record "
        f"it (transport_mode=record) or find what changed the request bytes.{extra}"
    )


def _replay_fallback(kind: str, request: dict, hash_: str) -> Path:
    """Resolve a missed request to a same-conversation cassette, or raise.

    Only reached on an exact-hash miss, and only yields a path when the fallback
    is enabled for this kind — otherwise a miss stays the hard error it is.
    """
    if not settings.cassette_fallback or kind not in _FALLBACK_KINDS:
        hint = (
            ""
            if kind in _FALLBACK_KINDS
            else f" ({kind} never falls back — its recorded shape is under test.)"
        )
        raise _miss(kind, hash_, hint)

    path, ratio = _nearest_cassette(kind, request)
    if path is None or ratio < _FALLBACK_MIN_RATIO:
        raise _miss(
            kind,
            hash_,
            f" The closest recording for this conversation scores {ratio:.2f} "
            f"prompt similarity (need {_FALLBACK_MIN_RATIO}), so the inputs "
            f"changed, not just the prompt wording.",
        )

    # Loud on purpose: this reply was recorded against different prompt bytes, so
    # assertions on the reply *text* no longer mean anything — only the logic
    # downstream of it does.
    logger.warning(
        f"Cassette fallback: {kind} request {hash_[:16]} missed; replaying "
        f"{path.name} ({ratio:.2f} prompt similarity), recorded for the same "
        f"conversation under different prompt bytes. Run `make record` before "
        f"trusting generated text."
    )
    return path


def _replay(kind: str, request: dict) -> Any:
    hash_ = request_hash(request)
    path = _cassette_path(hash_)
    if not path.is_file():
        path = _replay_fallback(kind, request, hash_)
    entry = json.loads(path.read_text(encoding="utf-8"))
    if entry["kind"] != kind:
        raise CassetteMiss(
            f"Cassette {path.name} is kind={entry['kind']!r}, expected {kind!r} "
            f"(hash collision across kinds — should be impossible)."
        )
    # Re-emit the recorded token usage so traces under replay carry the same
    # cost/latency metadata a live run would.
    if entry.get("usage"):
        record_generation_usage(**entry["usage"])
    return entry["response"]


async def _record(
    kind: str,
    request: dict,
    live: Callable[[], Awaitable[Any]],
    encode: Callable[[Any], Any],
) -> Any:
    with capture_generation_usage() as usage:
        started = time.perf_counter()
        result = await live()
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

    _write_cassette(kind, request, encode(result), latency_ms, usage)
    return result


def _write_cassette(
    kind: str,
    request: dict,
    response: Any,
    latency_ms: float,
    usage: dict,
) -> None:
    """Persist one recording. Shared by the buffered and streaming record paths."""
    hash_ = request_hash(request)
    entry = {
        "cassette_version": CASSETTE_VERSION,
        "kind": kind,
        "request_hash": hash_,
        "request": request,
        "response": response,
        "latency_ms": latency_ms,
        "usage": usage,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    path = _cassette_path(hash_)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("response") != entry["response"]:
            logger.warning(
                f"Cassette collision: {path.name} ({kind}) re-recorded with a "
                f"different response — the previous recording is overwritten. "
                f"Identical requests can only replay one response; vary the "
                f"fixture inputs if both trajectories must coexist."
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
