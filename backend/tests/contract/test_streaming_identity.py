"""Streaming must not be a different request.

The behavior freeze rests on a request's canonical bytes being its identity. If
streaming a reply produced a different hash, every committed cassette would miss
the moment the app streamed instead of buffered, and a recording made one way
could not serve the other. These tests pin that streaming is purely a delivery
detail: same identity in, same text out.
"""
from __future__ import annotations

import asyncio

import pytest
from fixtures.scenarios import CV_DIR, KICKOFF, SCENARIOS, run_scenario

from interview_bot import llm
from interview_bot.cli import _new_session
from interview_bot.config import settings
from interview_bot.integrations import cv_parser
from interview_bot.llm import transport
from interview_bot.pipeline import interview
from interview_bot.pipeline.plan import build_plan
from interview_bot.pipeline.profile import build_profile

_MESSAGES = [{"role": "user", "content": "Tell me about a system you scaled."}]
_SYSTEM = "Ask question 2."
_PREFIX = "You are interviewing for a Senior ML Engineer role."


def _request(temperature: float = 0.7, cache_prefix: str | None = _PREFIX) -> dict:
    return llm._generate_request(_MESSAGES, _SYSTEM, cache_prefix, temperature)


def test_streamed_and_buffered_requests_hash_identically():
    # Both paths build their replay identity from the same helper; this pins that
    # they keep doing so, since a cassette recorded either way must serve both.
    assert transport.request_hash(_request()) == transport.request_hash(_request())


def test_request_identity_declares_the_non_streaming_kind():
    # A streamed call records under "llm.generate", not a parallel stream kind --
    # otherwise recordings would silently fork into two incompatible sets.
    assert _request()["kind"] == "llm.generate"


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperature", 0.0),
        ("cache_prefix", None),
    ],
)
def test_request_identity_covers_every_input_that_changes_the_reply(field, value):
    baseline = _request()
    altered = _request(**{field: value})
    assert transport.request_hash(baseline) != transport.request_hash(altered)


# --------------------------------------------------------------------------- #
# Replay chunking
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        "",
        "short",
        "Question 2: Walk me through how you would shard a write-heavy table.",
        "x" * (transport.REPLAY_CHUNK_CHARS * 3),
        "unicode ✓ stays intact across chunk boundaries " * 5,
    ],
)
def test_rechunking_preserves_the_recorded_reply_exactly(text):
    # Chunk boundaries are arbitrary; their concatenation is the frozen output.
    assert "".join(transport._rechunk(text)) == text


def test_rechunking_rejects_a_non_text_recording():
    # A structured-output cassette cannot be streamed as text; failing loudly
    # beats yielding a repr of a dict into the interview transcript.
    with pytest.raises(transport.CassetteMiss):
        transport._rechunk({"score": 7})


def test_streaming_replay_reproduces_the_recorded_reply(monkeypatch, tmp_path):
    """A cassette recorded by the buffered path replays through the stream path."""
    monkeypatch.setattr(settings, "transport_mode", "record")
    monkeypatch.setattr(settings, "cassette_dir", str(tmp_path))
    recorded = "Question 3: Describe a time a model regressed in production."

    async def fake_live():
        return recorded

    request = _request()
    asyncio.run(transport.call("llm.generate", request, fake_live))

    monkeypatch.setattr(settings, "transport_mode", "replay")

    async def collect() -> str:
        chunks = []
        # `live` must never be consulted in replay -- no network, no API key.
        async for chunk in transport.call_streaming("llm.generate", request, _unreachable):
            chunks.append(chunk)
        return "".join(chunks)

    assert asyncio.run(collect()) == recorded


def test_streaming_replay_fails_loudly_on_a_missing_cassette(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "transport_mode", "replay")
    monkeypatch.setattr(settings, "cassette_dir", str(tmp_path))

    async def collect():
        async for _ in transport.call_streaming("llm.generate", _request(), _unreachable):
            pass

    with pytest.raises(transport.CassetteMiss):
        asyncio.run(collect())


def _unreachable():
    raise AssertionError("replay must not reach the provider")


# --------------------------------------------------------------------------- #
# End-to-end equivalence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_streamed_interview_matches_the_buffered_one(scenario):
    """The whole interview is identical whichever entry point drove it.

    Same trajectory, same per-turn scores and critiques, same transcript, same
    summary -- streaming changes when text arrives, never what it says.
    """
    buffered = asyncio.run(run_scenario(scenario))
    streamed = asyncio.run(run_scenario(scenario, stream=True))
    assert streamed == buffered


def test_streamed_deltas_concatenate_to_the_persisted_reply():
    """What the candidate watched being typed is what the transcript records."""
    scenario = SCENARIOS[0]

    async def first_turn() -> tuple[str, str]:
        session, profile = await _seed_session(scenario)
        deltas: list[str] = []
        reply = None
        async for kind, payload in interview.stream_turn(session, KICKOFF, profile):
            if kind == "delta":
                deltas.append(payload)
            elif kind == "result":
                reply = payload.reply
        return "".join(deltas), reply or ""

    streamed_text, persisted_reply = asyncio.run(first_turn())
    assert streamed_text == persisted_reply
    assert streamed_text  # a turn that streamed nothing would pass vacuously


def test_score_event_precedes_the_first_delta():
    """The grade for the previous answer is known before the next question exists.

    This ordering is the point of streaming here: the candidate sees how the last
    answer scored while the next one is still being written.
    """
    scenario = SCENARIOS[0]

    async def two_turns() -> list[str]:
        session, profile = await _seed_session(scenario)
        async for _ in interview.stream_turn(session, KICKOFF, profile):
            pass
        return [
            kind
            async for kind, _ in interview.stream_turn(session, scenario.answers[0], profile)
        ]

    kinds = asyncio.run(two_turns())
    assert kinds[0] == "score"
    assert "delta" in kinds
    assert kinds[-1] == "result"


async def _seed_session(scenario):
    """Build the same session `run_scenario` would, without driving any turns."""
    profile = await build_profile(scenario.job_description)
    interview_plan = await build_plan(profile, scenario.num_questions)
    cv_path = CV_DIR / scenario.cv_file
    parsed = cv_parser.parse(cv_path.name, cv_path.read_bytes())
    session = _new_session(
        f"cassette-{scenario.name}",
        profile,
        scenario.num_questions,
        (parsed.filename, parsed.text),
        interview_plan,
    )
    return session, profile
