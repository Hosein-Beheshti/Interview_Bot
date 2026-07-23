"""Offline evaluation harness for the answer scorer.

Runs the production scoring path (`services.interview.orchestration.score`) over a
human-reviewed golden set and reports calibration metrics: how often the overall
score lands in the expected band, mean absolute error vs. the band midpoint,
answer-type accuracy (with a confusion matrix), and per-dimension band checks.

Adversarial items (prompt-injection, confidently-wrong) get a hard gate: if any of
them score at or above ``--adversarial-max``, the run fails regardless of the
aggregate numbers — those must never be inflated.

The process exit code is non-zero when any quality gate fails, so this is
CI-runnable. Prompts/models are not code; this is how a prompt or model change is
measured rather than guessed.

Usage:
    python -m evals.run_eval                 # score the full set via the live API
    python -m evals.run_eval --limit 5       # first 5 items only (cheap smoke test)
    python -m evals.run_eval --dry-run       # no API calls; self-test the harness
    python -m evals.run_eval --json-out report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

from interview_bot.domain.evaluation import ScoreData
from interview_bot.domain.job_profile import minimal
from interview_bot.domain.rubric import DEFAULT_RUBRIC
from interview_bot.pipeline import orchestration

GOLDEN_SET = Path(__file__).parent / "golden_set.json"

# Default quality gates (override on the CLI). Bands are wide and scoring is
# subjective, so these are deliberately lenient — they catch regressions, not
# every off-by-one.
DEFAULT_MIN_IN_BAND = 0.70
DEFAULT_MIN_ANSWER_TYPE_ACC = 0.75
DEFAULT_ADVERSARIAL_MAX = 6  # an adversarial answer scoring above this is a hard fail


@dataclass
class ItemResult:
    id: str
    tags: list[str]
    expected: dict
    score: ScoreData | None
    in_band: bool = False
    answer_type_ok: bool = False
    dims_ok: bool = True
    follow_up_ok: bool = True
    hard_fail: bool = False
    abs_error: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.score is not None
            and self.in_band
            and self.answer_type_ok
            and self.dims_ok
            and not self.hard_fail
        )


def evaluate_item(item: dict, score: ScoreData | None, adversarial_max: int) -> ItemResult:
    exp = item["expected"]
    tags = item.get("tags", [])
    result = ItemResult(id=item["id"], tags=tags, expected=exp, score=score)

    if score is None:
        result.notes.append("scoring returned None (API or parse failure)")
        return result

    lo, hi = exp["overall_range"]
    result.in_band = lo <= score.overall <= hi
    result.abs_error = abs(score.overall - (lo + hi) / 2)
    if not result.in_band:
        result.notes.append(f"overall {score.overall} outside [{lo}, {hi}]")

    result.answer_type_ok = score.answer_type == exp["answer_type"]
    if not result.answer_type_ok:
        result.notes.append(
            f"answer_type '{score.answer_type}' != expected '{exp['answer_type']}'"
        )

    for key, (dlo, dhi) in exp.get("dimensions", {}).items():
        value = score.dimensions.get(key)
        if value is None or not (dlo <= value <= dhi):
            result.dims_ok = False
            result.notes.append(f"{key}={value} outside [{dlo}, {dhi}]")

    # Follow-up is a noisy, subjective signal: report mismatches but don't fail on them.
    if "follow_up_recommended" in exp:
        result.follow_up_ok = score.follow_up_recommended == exp["follow_up_recommended"]
        if not result.follow_up_ok:
            result.notes.append(
                f"follow_up {score.follow_up_recommended} != {exp['follow_up_recommended']} (soft)"
            )

    if "adversarial" in tags and score.overall > adversarial_max:
        result.hard_fail = True
        result.notes.append(
            f"ADVERSARIAL INFLATION: overall {score.overall} > {adversarial_max}"
        )

    return result


def _fake_score(item: dict) -> ScoreData:
    """A perfect-by-construction score for --dry-run, to self-test the harness."""
    exp = item["expected"]
    lo, hi = exp["overall_range"]
    mid = round((lo + hi) / 2)
    dims = {d.key: mid for d in DEFAULT_RUBRIC}
    for key, (dlo, dhi) in exp.get("dimensions", {}).items():
        dims[key] = round((dlo + dhi) / 2)
    return ScoreData(
        overall=mid,
        dimensions=dims,
        strengths=[],
        improvements=[],
        answer_type=exp["answer_type"],
        follow_up_recommended=exp.get("follow_up_recommended", False),
    )


async def _score_item(item: dict, semaphore: asyncio.Semaphore, dry_run: bool) -> ScoreData | None:
    if dry_run:
        return _fake_score(item)
    async with semaphore:
        profile = minimal(item["role"])
        # `score` never raises — it returns None on any failure, including a
        # transient API error (rate limit / overload) that exhausted its retries.
        # Retry once so an infra blip on a single item doesn't red the gate; a
        # persistent parse bug or sustained outage still fails on the second miss.
        score = await orchestration.score(profile, item["question"], item["answer"])
        if score is None:
            score = await orchestration.score(profile, item["question"], item["answer"])
        return score


async def run(items: list[dict], concurrency: int, dry_run: bool, adversarial_max: int) -> list[ItemResult]:
    semaphore = asyncio.Semaphore(concurrency)
    scores = await asyncio.gather(*(_score_item(i, semaphore, dry_run) for i in items))
    return [evaluate_item(item, score, adversarial_max) for item, score in zip(items, scores, strict=False)]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _confusion_matrix(results: list[ItemResult]) -> str:
    types = [d for d in ("substantive", "partial", "no_answer")]
    rows = {exp: {pred: 0 for pred in types} for exp in types}
    for r in results:
        if r.score is None:
            continue
        exp = r.expected["answer_type"]
        pred = r.score.answer_type
        if exp in rows and pred in rows[exp]:
            rows[exp][pred] += 1
    header = "  expected \\ predicted | " + " | ".join(f"{t[:11]:>11}" for t in types)
    lines = ["  answer_type confusion matrix:", header, "  " + "-" * (len(header) - 2)]
    for exp in types:
        cells = " | ".join(f"{rows[exp][pred]:>11}" for pred in types)
        lines.append(f"  {exp:>21} | {cells}")
    return "\n".join(lines)


def report(results: list[ItemResult], gates: dict) -> bool:
    print("\n" + "=" * 78)
    print("SCORER EVALUATION")
    print("=" * 78)

    for r in results:
        status = "PASS" if r.passed else ("HARD-FAIL" if r.hard_fail else "FAIL")
        overall = r.score.overall if r.score else "-"
        lo, hi = r.expected["overall_range"]
        print(f"  [{status:>9}] {r.id:<34} overall={overall!s:>3}  expected=[{lo},{hi}]")
        for note in r.notes:
            print(f"               - {note}")

    scored = [r for r in results if r.score is not None]
    errors = len(results) - len(scored)
    in_band_rate = sum(r.in_band for r in scored) / len(results) if results else 0.0
    at_acc = sum(r.answer_type_ok for r in scored) / len(results) if results else 0.0
    mae = statistics.mean([r.abs_error for r in scored]) if scored else 0.0
    hard_fails = [r for r in results if r.hard_fail]

    print("\n" + "-" * 78)
    print(_confusion_matrix(results))
    print("-" * 78)
    print(f"  items                : {len(results)}")
    print(f"  scoring errors       : {errors}")
    print(f"  in-band rate         : {in_band_rate:.0%}   (gate >= {gates['min_in_band']:.0%})")
    print(f"  answer_type accuracy : {at_acc:.0%}   (gate >= {gates['min_at_acc']:.0%})")
    print(f"  overall MAE          : {mae:.2f} points (vs. band midpoint)")
    print(f"  adversarial hard-fails: {len(hard_fails)}   (gate = 0)")

    gate_failures = []
    if in_band_rate < gates["min_in_band"]:
        gate_failures.append(f"in-band rate {in_band_rate:.0%} < {gates['min_in_band']:.0%}")
    if at_acc < gates["min_at_acc"]:
        gate_failures.append(f"answer_type accuracy {at_acc:.0%} < {gates['min_at_acc']:.0%}")
    if hard_fails:
        gate_failures.append(f"{len(hard_fails)} adversarial item(s) inflated")
    if errors:
        gate_failures.append(f"{errors} scoring error(s)")

    print("-" * 78)
    if gate_failures:
        print("  RESULT: FAIL")
        for f in gate_failures:
            print(f"          - {f}")
    else:
        print("  RESULT: PASS")
    print("=" * 78 + "\n")
    return not gate_failures


def _write_json(results: list[ItemResult], path: Path) -> None:
    payload = [
        {
            "id": r.id,
            "tags": r.tags,
            "passed": r.passed,
            "hard_fail": r.hard_fail,
            "expected": r.expected,
            "score": (
                {
                    "overall": r.score.overall,
                    "answer_type": r.score.answer_type,
                    "dimensions": r.score.dimensions,
                    "follow_up_recommended": r.score.follow_up_recommended,
                }
                if r.score
                else None
            ),
            "abs_error": r.abs_error,
            "notes": r.notes,
        }
        for r in results
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  wrote JSON report -> {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the answer scorer against the golden set.")
    parser.add_argument("--limit", type=int, default=None, help="Score only the first N items.")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent scoring calls.")
    parser.add_argument("--dry-run", action="store_true", help="No API calls; self-test the harness.")
    parser.add_argument("--min-in-band", type=float, default=DEFAULT_MIN_IN_BAND)
    parser.add_argument("--min-answer-type-acc", type=float, default=DEFAULT_MIN_ANSWER_TYPE_ACC)
    parser.add_argument("--adversarial-max", type=int, default=DEFAULT_ADVERSARIAL_MAX)
    parser.add_argument("--json-out", type=Path, default=None, help="Write a per-item JSON report.")
    args = parser.parse_args()

    data = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    items = data["items"][: args.limit] if args.limit else data["items"]

    if args.dry_run:
        print("(dry run - using fabricated in-band scores, no API calls)")

    results = asyncio.run(
        run(items, args.concurrency, args.dry_run, args.adversarial_max)
    )

    gates = {"min_in_band": args.min_in_band, "min_at_acc": args.min_answer_type_acc}
    passed = report(results, gates)

    if args.json_out:
        _write_json(results, args.json_out)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
