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

Cassettes are versioned fixture files (JSON, one per request) meant to be
committed. Callers whose live result isn't JSON (a Pydantic model, raw audio
bytes) pass `encode`/`decode` to map between the result and its cassette form;
live and record always return the provider's original result untouched.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
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


def _cassette_path(hash_: str) -> Path:
    return cassette_dir() / f"{hash_[:16]}.json"


def _replay(kind: str, request: dict) -> Any:
    hash_ = request_hash(request)
    path = _cassette_path(hash_)
    if not path.is_file():
        raise CassetteMiss(
            f"No cassette for {kind} request (hash {hash_[:16]}) in {cassette_dir()}. "
            f"The assembled request differs from every recorded one — either record "
            f"it (transport_mode=record) or find what changed the request bytes."
        )
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
    hash_ = request_hash(request)
    with capture_generation_usage() as usage:
        started = time.perf_counter()
        result = await live()
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

    entry = {
        "cassette_version": CASSETTE_VERSION,
        "kind": kind,
        "request_hash": hash_,
        "request": request,
        "response": encode(result),
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
    return result
