"""Offline evaluation harness for the interviewer's turn generator.

Companion to `run_scorer_eval.py` (which evaluates the answer scorer): this evaluates
`interview_bot.pipeline.interview.build_turn_prompt` — the interviewer's own main
questions and follow-ups — against a human-reviewed golden set of generation
inputs (`generator_golden_set.json`).

For most items this runs the real production path end to end:

    build_turn_prompt(...) -> llm.generate(...) -> check_format(...) -> judge_turn(...)

`check_format` is a Tier-1, no-LLM string assertion (the "Question N:" label
contract) and is a hard gate: the FSM depends on it, so any miss fails the run
regardless of aggregates. Every other criterion (on_topic, grounded,
turn_type_correct, greets_when_expected, resisted_injection) has no cheaper
ground truth than the judge itself, so the same (judge_verdict, expected) pairs
serve two purposes from one run:

  - regression pass rate: fraction where the judge's verdict on the real,
    freshly-generated reply matches the human-authored `expected` label
  - judge calibration: Cohen's kappa between judge verdicts and `expected`,
    i.e. whether the judge itself can be trusted, not just the generator

A live model given a correct prompt is well-behaved almost by construction, so
generation alone can't produce reliable NEGATIVE (expected=False) examples --
and without any, Cohen's kappa is mathematically degenerate (see
`generator_golden_set.json`'s notes). Items may instead set `fixed_reply`: a
hand-authored reply text that is judged directly, skipping `build_turn_prompt`
+ `llm.generate`. This is still one dataset, still one harness run, still
"real code, real API call" for the part under test (the judge) -- it just
lets the judge be shown a reply we know in advance is bad, which is the only
way to prove it can tell good from bad rather than just agreeing with
whatever the (usually-good) live generator produces.

Adversarial items get the same hard gate as the scorer eval: any adversarial
item whose `resisted_injection` verdict is not True fails the run outright.

Usage:
    python -m evals.run_generator_eval                # full set, live API
    python -m evals.run_generator_eval --limit 5       # cheap smoke test
    python -m evals.run_generator_eval --dry-run       # no API calls, self-test
    python -m evals.run_generator_eval --json-out report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from evals import metrics
from interview_bot import llm
from interview_bot.config import settings
from interview_bot.domain import turn_quality
from interview_bot.domain.judgement import JudgeResult
from interview_bot.domain.plan import PlanSlot
from interview_bot.domain.profile import JobProfile
from interview_bot.domain.progression import MODE_FOLLOW_UP, MODE_MAIN
from interview_bot.domain.transcript import last_assistant
from interview_bot.domain.turn_quality import CRITERIA_VERSION
from interview_bot.pipeline import judge as judge_pipeline
from interview_bot.pipeline.interview import build_turn_prompt
from interview_bot.prompts.judge import JUDGE_PROMPT_VERSION
from interview_bot.telemetry import capture_generation_usage

GOLDEN_SET = Path(__file__).parent / "generator_golden_set.json"

# Any adversarial item whose resisted_injection verdict isn't True fails the run
# outright, regardless of aggregate pass rates — the boolean analog of run_scorer_eval.py's
# DEFAULT_ADVERSARIAL_MAX.
ADVERSARIAL_CRITERION = "resisted_injection"

# Landis & Koch (1977) bands, external convention (not encoded anywhere else in
# this codebase) — below this, a criterion's judge verdicts are advisory only,
# never gating, because the judge hasn't been shown reliable on that criterion.
KAPPA_SUBSTANTIAL_AGREEMENT = 0.6


def run_meta() -> dict:
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": settings.llm_provider,
        # The generator under test and the judge grading it need not be the same
        # model (see `settings.generator_model`), so both are recorded.
        "model": llm.generation_model(),
        "judge_model": llm.active_model(),
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "criteria_version": CRITERIA_VERSION,
        "ground_truth": "human-reviewed golden set (generator_golden_set.json)",
    }


def _profile_from(item: dict) -> JobProfile:
    p = item["profile"]
    return JobProfile(
        role=p["role"],
        company=p.get("company"),
        seniority=p.get("seniority"),
        key_skills=tuple(p.get("key_skills", [])),
        focus_areas=tuple(p.get("focus_areas", [])),
    )


def _slot_from(item: dict) -> PlanSlot | None:
    s = item.get("slot")
    return PlanSlot(skill=s["skill"], intent=s["intent"], difficulty=s["difficulty"]) if s else None


def _prior_answer_from(messages: list[dict]) -> str | None:
    return next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)


@dataclass
class ItemResult:
    id: str
    tags: list[str]
    mode: str
    adversarial: bool
    is_fixture: bool
    applicable: list[str]
    expected: dict[str, bool]
    format_ok: bool
    reply: str | None
    judgement: JudgeResult | None
    notes: list[str] = field(default_factory=list)
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def format_hard_fail(self) -> bool:
        return not self.format_ok

    @property
    def adversarial_hard_fail(self) -> bool:
        if not self.adversarial or ADVERSARIAL_CRITERION not in self.applicable:
            return False
        verdict = self.judgement.criteria.get(ADVERSARIAL_CRITERION) if self.judgement else None
        return verdict is not True

    @property
    def hard_fail(self) -> bool:
        return self.format_hard_fail or self.adversarial_hard_fail

    @property
    def matches(self) -> dict[str, bool]:
        """Per-criterion (judge == expected) for every applicable criterion the
        judge actually returned a verdict for."""
        if self.judgement is None:
            return {}
        return {
            key: self.judgement.criteria[key] == self.expected[key]
            for key in self.applicable
            if key in self.judgement.criteria
        }

    @property
    def passed(self) -> bool:
        return (
            self.judgement is not None
            and not self.hard_fail
            and all(self.matches.get(key, False) for key in self.applicable)
        )


def _fake_reply(mode: str, question_number: int) -> str:
    """A structurally-correct, perfect-by-construction reply for --dry-run."""
    if mode == MODE_MAIN:
        return f"Question {question_number}: Tell me about a time you handled this."
    if mode == MODE_FOLLOW_UP:
        return "Following up on that — could you go a bit deeper on that point?"
    return ""


def _fake_judgement(expected: dict[str, bool], criteria: tuple) -> JudgeResult:
    return JudgeResult(
        criteria={c.key: expected[c.key] for c in criteria},
        critique="dry-run: fabricated verdict matching expected",
    )


@dataclass
class _Generated:
    reply: str | None
    judgement: JudgeResult | None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


async def _run_item(item: dict, semaphore: asyncio.Semaphore, dry_run: bool) -> _Generated:
    profile = _profile_from(item)
    slot = _slot_from(item)
    messages = item["messages"]
    current_topic = last_assistant(messages)
    fixed_reply = item.get("fixed_reply")
    criteria = turn_quality.applicable_criteria(
        item["mode"],
        question_number=item["question_number"],
        candidate_name=item["candidate_name"],
    )

    if dry_run:
        reply = fixed_reply if fixed_reply is not None else _fake_reply(item["mode"], item["question_number"])
        judgement: JudgeResult | None = _fake_judgement(item["expected"], criteria)
        return _Generated(reply=reply, judgement=judgement)

    async with semaphore:
        with capture_generation_usage() as usage:
            started = time.perf_counter()
            if fixed_reply is not None:
                # Judge-only fixture: a hand-authored reply, skipping generation
                # entirely so the judge can be shown a known-bad case on demand.
                reply = fixed_reply
            else:
                prompt = build_turn_prompt(
                    profile,
                    item["mode"],
                    item["follow_up_kind"],
                    slot=slot,
                    current_topic=current_topic,
                    candidate_name=item["candidate_name"],
                    cv_context=item["cv_context"],
                    question_number=item["question_number"],
                    num_questions=item["num_questions"],
                )
                reply = await llm.generate(
                    messages, prompt.instruction,
                    cache_prefix=prompt.cache_prefix, operation="generator_eval",
                )
            judgement = await judge_pipeline.judge_turn(
                profile,
                item["mode"],
                reply,
                slot=slot,
                current_topic=current_topic,
                prior_answer=_prior_answer_from(messages),
                cv_context=item["cv_context"],
                candidate_name=item["candidate_name"],
                question_number=item["question_number"],
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return _Generated(
            reply=reply,
            judgement=judgement,
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


def _evaluate(item: dict, gen: _Generated) -> ItemResult:
    criteria = turn_quality.applicable_criteria(
        item["mode"], question_number=item["question_number"], candidate_name=item["candidate_name"],
    )
    applicable = [c.key for c in criteria]
    format_ok = (
        turn_quality.check_format(item["mode"], item["question_number"], gen.reply)
        if gen.reply is not None
        else False
    )
    result = ItemResult(
        id=item["id"],
        tags=item.get("tags", []),
        mode=item["mode"],
        adversarial=item.get("adversarial", False),
        is_fixture="fixed_reply" in item,
        applicable=applicable,
        expected=item["expected"],
        format_ok=format_ok,
        reply=gen.reply,
        judgement=gen.judgement,
        latency_ms=gen.latency_ms,
        input_tokens=gen.input_tokens,
        output_tokens=gen.output_tokens,
    )
    if not format_ok:
        result.notes.append("format_correct: FAILED the 'Question N:' label contract")
    if gen.judgement is None:
        result.notes.append("judging returned None (API or parse failure)")
    else:
        for key in applicable:
            verdict = gen.judgement.criteria.get(key)
            if verdict != item["expected"].get(key):
                result.notes.append(f"{key}: judge={verdict} != expected={item['expected'].get(key)}")
    if result.adversarial_hard_fail:
        result.notes.append("ADVERSARIAL: resisted_injection did not verify True — hard fail")
    return result


async def run(items: list[dict], concurrency: int, dry_run: bool) -> list[ItemResult]:
    semaphore = asyncio.Semaphore(concurrency)
    generated = await asyncio.gather(*(_run_item(i, semaphore, dry_run) for i in items))
    return [_evaluate(item, gen) for item, gen in zip(items, generated, strict=False)]


# ---------------------------------------------------------------------------
# Reporting: per-criterion pass rate (regression gate) + Cohen's kappa (judge
# calibration), both derived from the same (judge_verdict, expected) pairs.
# ---------------------------------------------------------------------------

def _per_criterion_stats(results: list[ItemResult]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for key in (c.key for c in turn_quality.CRITERIA):
        judged = [
            (r.judgement.criteria[key], r.expected[key])
            for r in results
            if key in r.applicable and r.judgement is not None and key in r.judgement.criteria
        ]
        if not judged:
            continue
        judge_labels = [str(v) for v, _ in judged]
        expected_labels = [str(e) for _, e in judged]
        matches = sum(1 for v, e in judged if v == e)
        kappa = metrics.cohen_kappa(judge_labels, expected_labels)
        stats[key] = {
            "n": len(judged),
            "pass_rate": matches / len(judged),
            "kappa": kappa,
            "trusted": kappa >= KAPPA_SUBSTANTIAL_AGREEMENT,
        }
    return stats


def report(results: list[ItemResult]) -> bool:
    print("\n" + "=" * 78)
    print("GENERATOR EVALUATION")
    print("=" * 78)

    for r in results:
        status = "PASS" if r.passed else ("HARD-FAIL" if r.hard_fail else "FAIL")
        src = "fixture" if r.is_fixture else "live-gen"
        print(f"  [{status:>9}] {r.id:<32} mode={r.mode:<13} src={src:<8} format={'ok' if r.format_ok else 'BAD'}")
        for note in r.notes:
            print(f"               - {note}")

    stats = _per_criterion_stats(results)
    format_failures = [r for r in results if r.format_hard_fail]
    adversarial_failures = [r for r in results if r.adversarial_hard_fail]
    judging_errors = [r for r in results if r.judgement is None]

    print("\n" + "-" * 78)
    print("  per-criterion regression pass rate / judge calibration (kappa):")
    for key, s in stats.items():
        trust = "trusted" if s["trusted"] else "ADVISORY ONLY (kappa < 0.6)"
        print(f"    {key:<22} n={s['n']:<3} pass_rate={s['pass_rate']:.0%}   kappa={s['kappa']:.2f}  ({trust})")
    print("-" * 78)
    print(f"  items                  : {len(results)}")
    print(f"  format hard-fails      : {len(format_failures)}   (gate = 0)")
    print(f"  adversarial hard-fails : {len(adversarial_failures)}   (gate = 0)")
    print(f"  judging errors         : {len(judging_errors)}")

    gate_failures = []
    if format_failures:
        gate_failures.append(f"{len(format_failures)} item(s) failed the format contract")
    if adversarial_failures:
        gate_failures.append(f"{len(adversarial_failures)} adversarial item(s) did not resist injection")
    if judging_errors:
        gate_failures.append(f"{len(judging_errors)} judging error(s)")
    untrusted = [k for k, s in stats.items() if not s["trusted"]]
    if untrusted:
        print(f"  NOTE: judge not yet calibrated on: {', '.join(untrusted)} — advisory only, not gating.")

    print("-" * 78)
    if gate_failures:
        print("  RESULT: FAIL")
        for f in gate_failures:
            print(f"          - {f}")
    else:
        print("  RESULT: PASS")
    print("=" * 78 + "\n")
    return not gate_failures


def _write_json(results: list[ItemResult], stats: dict, path: Path) -> None:
    payload = {
        "meta": run_meta(),
        "per_criterion": stats,
        "items": [
            {
                "id": r.id,
                "tags": r.tags,
                "mode": r.mode,
                "adversarial": r.adversarial,
                "is_fixture": r.is_fixture,
                "passed": r.passed,
                "hard_fail": r.hard_fail,
                "format_ok": r.format_ok,
                "expected": r.expected,
                "judgement": (
                    {"criteria": r.judgement.criteria, "critique": r.judgement.critique}
                    if r.judgement
                    else None
                ),
                "reply": r.reply,
                "latency_ms": r.latency_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "notes": r.notes,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote JSON report -> {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the interviewer turn generator + judge.")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N items.")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent generate+judge calls.")
    parser.add_argument("--dry-run", action="store_true", help="No API calls; self-test the harness.")
    parser.add_argument("--json-out", type=Path, default=None, help="Write a per-item JSON report.")
    args = parser.parse_args()

    data = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    items = data["items"][: args.limit] if args.limit else data["items"]

    if args.dry_run:
        print("(dry run - using fabricated in-spec replies and verdicts, no API calls)")

    results = asyncio.run(run(items, args.concurrency, args.dry_run))
    passed = report(results)

    if args.json_out:
        _write_json(results, _per_criterion_stats(results), args.json_out)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
