"""Shared interview scenarios: the fixture set behind the cassettes and tests.

One source of truth for how a scripted interview is driven through the real
pipeline — job-profile extraction -> interview plan -> FSM interview loop with
per-answer scoring -> final summary. Both `scripts/record_cassettes.py` (which
records/verifies the cassettes) and the contract tests import from here, so the
tests exercise exactly the code that produced the fixtures.

`run_scenario` talks to model providers only through the transport waist
(`services.integrations.transport`), so under `transport_mode="replay"` it runs
fully offline with no API keys. Scenarios use distinct roles/CVs on purpose:
identical requests share one cassette slot, so two trajectories must never
assemble the same prompt.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from config import settings
from interview_cli import _new_session
from services import session as session_service
from services.integrations import cv_parser, embeddings, rag
from services.interview import orchestration

KICKOFF = "Hello, I'm ready to begin the interview."

FIXTURES_DIR = Path(__file__).resolve().parent
CV_DIR = FIXTURES_DIR / "cvs"
RECORDINGS_DIR = FIXTURES_DIR / "recordings"


@dataclass(frozen=True)
class Scenario:
    name: str
    cv_file: str
    job_description: str
    num_questions: int
    # Consumed in order, one per turn after the kickoff. Sized with slack for
    # follow-up turns; unused entries are simply never sent.
    answers: tuple[str, ...]


SCENARIOS: tuple[Scenario, ...] = (
    # Strong candidate, substantive answers throughout — the happy path.
    Scenario(
        name="ml-engineer",
        cv_file="ml_engineer.txt",
        num_questions=3,
        job_description=(
            "Senior Machine Learning Engineer — Streamside Media (Stockholm).\n"
            "We run personalized ranking and recommendations for 20M weekly "
            "listeners. You will own ranking models end to end: feature "
            "pipelines, training, offline and online evaluation, deployment, "
            "and monitoring. Requirements: 5+ years of production ML, strong "
            "Python, experience with learning-to-rank or recommender systems, "
            "A/B testing at scale, and low-latency model serving. Nice to "
            "have: feature stores, counterfactual evaluation, Kubernetes."
        ),
        answers=(
            "In my last role I replaced a GBDT ranker with a two-tower "
            "retrieval model plus a LightGBM re-ranker. The two-tower gave us "
            "cheap candidate generation via approximate nearest neighbours, "
            "and the re-ranker kept feature-rich precision at the top of the "
            "list. We validated offline with NDCG on counterfactual replay of "
            "logged impressions before any online test, because naive offline "
            "metrics on logged data are biased toward the old policy.",
            "I'd start with drift monitoring on both inputs and outputs: PSI "
            "on feature distributions, and delayed-label AUC once ground "
            "truth arrives. The subtle failure mode is a silent upstream "
            "schema change — a feature going constant doesn't crash anything, "
            "it just quietly degrades ranking. We caught exactly that with a "
            "per-feature PSI alert within a day. I'd also canary new models "
            "on a small traffic slice and compare business metrics, not just "
            "model metrics.",
            "For latency I'd profile first — in my experience the bottleneck "
            "is usually feature hydration, not the model forward pass. We cut "
            "p99 from 240ms to 90ms mostly by moving features to a Redis "
            "feature store and precomputing user embeddings, and only then "
            "quantizing the retrieval tower to int8, which cost about 0.2% "
            "NDCG. The tradeoff I'd watch is cache staleness versus latency: "
            "stale user features hurt cold-start and fast-changing sessions.",
            "A/B tests need to run long enough to cover weekly seasonality, "
            "and the unit of randomization has to match the unit of the "
            "metric — user-level, not request-level, if the metric is "
            "retention. I'd also pre-register the decision metric to avoid "
            "cherry-picking among twenty dashboards after the fact.",
            "I'd use point-in-time-correct joins in the training pipeline so "
            "features reflect what was knowable at serving time; leakage from "
            "future data is the classic cause of great offline numbers that "
            "evaporate online.",
            "Honestly the biggest lesson was operational: models are easy, "
            "ownership is hard. The eval harness we built became the release "
            "gate, and that changed team behaviour more than any single model.",
            "I would keep the ensemble simple and invest in evaluation depth.",
            "That covers my experience, happy to go deeper on any part.",
        ),
    ),
    # Uneven candidate: one solid answer, one explicit "I don't know" (exercises
    # the no_answer -> simplify branch), one shallow answer (exercises the
    # probe-deeper follow-up branch).
    Scenario(
        name="backend-payments",
        cv_file="backend_engineer.txt",
        num_questions=3,
        job_description=(
            "Backend Engineer, Payments — Ledgerpoint (Manchester/hybrid).\n"
            "You will build and operate the services that move money: "
            "invoicing, payment webhooks, reconciliation. Correctness under "
            "concurrency matters more here than raw throughput. Requirements: "
            "4+ years backend experience with Python or Go, PostgreSQL, "
            "event-driven architectures (Kafka or similar), idempotency and "
            "exactly-once patterns, observability. Nice to have: strangler-fig "
            "migrations, property-based testing."
        ),
        answers=(
            "The core is an idempotency key per logical payment attempt, "
            "stored with the response in the same transaction as the side "
            "effect. On a retry you return the stored response instead of "
            "re-executing. The subtle part is scoping the key: it has to "
            "identify the business operation, not the HTTP request, otherwise "
            "a client retry with a fresh key double-charges. We also set a "
            "unique constraint so two concurrent requests race on the insert "
            "and exactly one wins.",
            "I don't know, to be honest — I haven't worked with that.",
            "We used Kafka for that.",
            "To expand: the outbox pattern was how we kept the database and "
            "Kafka consistent — write the event to an outbox table in the "
            "same transaction as the state change, then a relay publishes it. "
            "Consumers are idempotent, so at-least-once delivery is fine.",
            "For the migration we used a strangler fig: route a slice of "
            "traffic to the new service, dual-write, and run reconciliation "
            "jobs that compare both sides nightly until the diff is zero for "
            "a few weeks. Only then did we cut over writes.",
            "Property-based tests caught a rounding bug in money arithmetic "
            "that example-based tests missed — fractions of a cent leaking "
            "across currency conversions.",
            "I'd add tracing before adding retries; you can't tune what you "
            "can't see.",
            "That's the extent of my experience there.",
        ),
    ),
    # Short interview (2 questions), mixed quality — a second distinct FSM
    # trajectory with a partial answer in the mix.
    Scenario(
        name="data-streaming",
        cv_file="data_engineer.txt",
        num_questions=2,
        job_description=(
            "Data Engineer, Streaming Platform — Meridian Commerce "
            "(Bengaluru).\nOwn the event pipelines that feed analytics and ML: "
            "Kafka, Flink, Iceberg on S3, ~1B events/day. You will drive data "
            "contracts with producer teams and keep exactly-once guarantees "
            "honest. Requirements: 3+ years data engineering, strong SQL and "
            "Python, stream processing experience, lakehouse table formats. "
            "Nice to have: dbt, cost optimization on AWS."
        ),
        answers=(
            "Exactly-once in Flink is really exactly-once state plus "
            "transactional sinks: checkpointing gives you consistent state "
            "recovery, and the two-phase-commit sink ties the output commit "
            "to the checkpoint. The gotcha is that everything downstream must "
            "either participate in the transaction or tolerate duplicates — "
            "we made the Iceberg commit the transaction boundary and kept "
            "consumers idempotent as a belt-and-braces measure.",
            "Mostly it's about schemas, I think. We used Protobuf.",
            "To add detail: the contracts were Protobuf schemas checked in "
            "CI for backward compatibility, so a producer physically could "
            "not merge a breaking change without the analytics team's "
            "sign-off. Incidents went from monthly to zero in two quarters.",
            "For cost we moved the batch layer to spot instances on EKS and "
            "scheduled Iceberg compaction and snapshot expiry; storage-level "
            "maintenance mattered as much as compute pricing.",
            "That's all I have on that topic.",
            "I'd start with freshness and volume checks on the core marts.",
        ),
    ),
)


def scenario_by_name(name: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(f"No scenario named {name!r}")


async def _paced_embed(texts: list[str], input_type: str) -> None:
    """Embed with pacing for Voyage's free tier (3 requests/minute).

    Only the record path talks to the network, so replay runs skip the sleep.
    """
    if settings.transport_mode == "record":
        await asyncio.sleep(21)
    await embeddings.embed(texts, input_type=input_type)  # type: ignore[arg-type]


async def run_scenario(scenario: Scenario) -> dict:
    """Drive one scenario end to end and return its structured outputs.

    Deterministic under replay: the only nondeterminism (the provider responses)
    is served from cassettes, so identical cassettes yield an identical dict —
    which is what the golden-output and FSM-trajectory tests assert on.
    """
    profile = await session_service.build_profile(scenario.job_description)
    interview_plan = await session_service.build_plan(profile, scenario.num_questions)

    cv_path = CV_DIR / scenario.cv_file
    parsed = cv_parser.parse(cv_path.name, cv_path.read_bytes())

    # CV-ingestion embeddings: what the /cv upload route would run (chunk +
    # embed) plus one retrieval-query embed, so the Voyage seam has cassettes
    # too. The pgvector store itself is a database, not a model provider, and
    # is skipped here — these interviews use the full-text CV path.
    chunks = rag.chunk_cv(parsed.text)
    await _paced_embed([c.text for c in chunks], "document")
    await _paced_embed([profile.role], "query")

    session = _new_session(
        f"cassette-{scenario.name}",
        profile,
        scenario.num_questions,
        (parsed.filename, parsed.text),
        interview_plan,
    )

    transcript: list[dict] = []
    trajectory: list[str] = []
    answers = iter(scenario.answers)
    message = KICKOFF
    summary = None
    # Budget: each main question can add at most `max_followups_per_question`
    # extra turns, plus the kickoff and closing turns.
    for _ in range(scenario.num_questions * (1 + settings.max_followups_per_question) + 2):
        result = await orchestration.run_turn(session, message, profile)
        score = result.score_data
        transcript.append(
            {
                "candidate": message,
                "interviewer": result.reply,
                "mode": result.mode,
                "score": score.overall if score else None,
                "answer_type": score.answer_type if score else None,
                "follow_up_recommended": score.follow_up_recommended if score else None,
                # Per-competency scores and the evaluator's critique, pinned so
                # the golden test freezes the full scoring output, not just the
                # weighted overall.
                "dimensions": dict(score.dimensions) if score else None,
                "critique": score.critique if score else None,
            }
        )
        trajectory.append(result.mode)
        if result.summary is not None:
            summary = result.summary
            break
        try:
            message = next(answers)
        except StopIteration:
            raise RuntimeError(f"{scenario.name}: ran out of scripted answers") from None
    else:
        raise RuntimeError(f"{scenario.name}: interview did not complete within the turn budget")

    return {
        "scenario": scenario.name,
        "cv_file": scenario.cv_file,
        "num_questions": scenario.num_questions,
        "profile": profile.to_dict(),
        "plan": interview_plan.to_dict() if interview_plan else None,
        "trajectory": trajectory,
        "transcript": transcript,
        "scores": list(session.scores),
        "summary": summary,
    }
