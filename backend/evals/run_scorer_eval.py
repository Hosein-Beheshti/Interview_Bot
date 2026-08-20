"""Offline evaluation harness for the answer scorer.

Runs the production scoring path (`interview_bot.pipeline.scoring.score`) over a
human-reviewed golden set and reports calibration metrics: how often the overall
score lands in the expected band, mean absolute error vs. the band midpoint,
answer-type accuracy (with a confusion matrix), and per-dimension band checks.

Adversarial items (prompt-injection, confidently-wrong) get a hard gate: if any of
them score at or above ``--adversarial-max``, the run fails regardless of the
aggregate numbers — those must never be inflated.

The process exit code is non-zero when any quality gate fails, so this is
CI-runnable. Prompts/models are not code; this is how a prompt or model change is
measured rather than guessed.

A single run reports levels; `--baseline` prints each headline metric with its
movement since a previous report, and warns when the two runs were produced under
different prompt/rubric/model provenance — across those, results are not
comparable at all (see `evals/baseline.py`).

Usage:
    python -m evals.run_scorer_eval                 # score the full set via the live API
    python -m evals.run_scorer_eval --limit 5       # first 5 items only (cheap smoke test)
    python -m evals.run_scorer_eval --dry-run       # no API calls; self-test the harness
    python -m evals.run_scorer_eval --json-out report.json
    python -m evals.run_scorer_eval --baseline reports/scorer_report.json

Companion to `run_generator_eval.py`, which covers question/reply generation
instead of scoring.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from evals import baseline as baseline_module
from evals import metrics
from interview_bot import llm
from interview_bot.config import settings
from interview_bot.domain.profile import minimal
from interview_bot.domain.rubric import DEFAULT_RUBRIC, RUBRIC_VERSION
from interview_bot.domain.scoring import ScoreData
from interview_bot.pipeline import scoring
from interview_bot.prompts.scoring import PROMPT_VERSION
from interview_bot.telemetry import capture_generation_usage

GOLDEN_SET = Path(__file__).parent / "scorer_golden_set.json"


def run_meta() -> dict:
    """Provenance stamped onto every results artifact — the versions a score is
    only comparable within, plus the model that produced it.
    """
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": settings.llm_provider,
        "model": llm.active_model(),
        "prompt_version": PROMPT_VERSION,
        "rubric_version": RUBRIC_VERSION,
        # The golden bands are human-authored; this run uses no LLM-generated
        # reference key points, so nothing synthetic acts as ground truth here.
        "ground_truth": "human-reviewed golden set (scorer_golden_set.json)",
        "reference_key_points": "none (not used in eval scoring)",
    }

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
    # Cost/latency provenance, captured per item (None under --dry-run).
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

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


@dataclass
class _Scored:
    score: ScoreData | None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


async def _score_item(item: dict, semaphore: asyncio.Semaphore, dry_run: bool) -> _Scored:
    if dry_run:
        return _Scored(score=_fake_score(item))
    async with semaphore:
        profile = minimal(item["role"])
        # `score` never raises — it returns None on any failure, including a
        # transient API error (rate limit / overload) that exhausted its retries.
        # Retry once so an infra blip on a single item doesn't red the gate; a
        # persistent parse bug or sustained outage still fails on the second miss.
        # `capture_generation_usage` mirrors the provider's token report so the
        # results artifact carries real cost data, not estimates.
        with capture_generation_usage() as usage:
            started = time.perf_counter()
            score = await scoring.score(profile, item["question"], item["answer"])
            if score is None:
                score = await scoring.score(profile, item["question"], item["answer"])
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return _Scored(
            score=score,
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


async def run(items: list[dict], concurrency: int, dry_run: bool, adversarial_max: int) -> list[ItemResult]:
    semaphore = asyncio.Semaphore(concurrency)
    scored = await asyncio.gather(*(_score_item(i, semaphore, dry_run) for i in items))
    results = []
    for item, s in zip(items, scored, strict=False):
        r = evaluate_item(item, s.score, adversarial_max)
        r.latency_ms, r.input_tokens, r.output_tokens = s.latency_ms, s.input_tokens, s.output_tokens
        results.append(r)
    return results


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


def _tag_breakdown(results: list[ItemResult]) -> str:
    """Per-tag in-band rate, so a tag-level regression (e.g. one buzzword-heavy
    category getting over-scored) is visible instead of buried in per-item notes.
    """
    scored = [r for r in results if r.score is not None]
    by_tag: dict[str, list[ItemResult]] = {}
    for r in scored:
        for tag in r.tags:
            by_tag.setdefault(tag, []).append(r)
    lines = ["  in-band rate by tag:"]
    for tag in sorted(by_tag):
        items = by_tag[tag]
        rate = sum(r.in_band for r in items) / len(items)
        lines.append(f"    {tag:<20} {rate:>4.0%}  (n={len(items)})")
    return "\n".join(lines)


def summarize(results: list[ItemResult]) -> dict:
    """Flat headline metrics: what gets printed, persisted, and compared.

    One function so the numbers in the artifact are literally the numbers on
    screen — a baseline comparison is only trustworthy if the metric it reads was
    not recomputed by a second, subtly different expression.
    """
    scored = [r for r in results if r.score is not None]
    fu_checked = [r for r in scored if "follow_up_recommended" in r.expected]
    return {
        "items": len(results),
        "errors": len(results) - len(scored),
        "in_band_rate": sum(r.in_band for r in scored) / len(results) if results else 0.0,
        "answer_type_accuracy": (
            sum(r.answer_type_ok for r in scored) / len(results) if results else 0.0
        ),
        "mae": statistics.mean([r.abs_error for r in scored]) if scored else 0.0,
        "adversarial_hard_fails": sum(1 for r in results if r.hard_fail),
        "follow_up_accuracy": (
            sum(r.follow_up_ok for r in fu_checked) / len(fu_checked) if fu_checked else None
        ),
    }


def report(results: list[ItemResult], gates: dict, baseline: dict | None = None) -> bool:
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

    summary = summarize(results)
    base = baseline or {}
    errors = summary["errors"]
    in_band_rate = summary["in_band_rate"]
    at_acc = summary["answer_type_accuracy"]
    mae = summary["mae"]
    hard_fails = [r for r in results if r.hard_fail]
    fu_checked = [r for r in results if r.score is not None and "follow_up_recommended" in r.expected]
    fu_acc = summary["follow_up_accuracy"]

    print("\n" + "-" * 78)
    print(_confusion_matrix(results))
    print("-" * 78)
    print(_tag_breakdown(results))
    print("-" * 78)
    baseline_module.report_drift(run_meta(), base)
    def d(current: float | None, key: str, fmt: str = "{:+.0%}") -> str:
        # No baseline at all is silence, not "(new)" — that marker means the
        # baseline exists but predates this metric, which is worth seeing.
        if not base:
            return ""
        return baseline_module.delta(
            current, baseline_module.summary_value(base, key), fmt=fmt
        )

    print(f"  items                : {len(results)}")
    print(f"  scoring errors       : {errors}{d(errors, 'errors', '{:+d}')}")
    print(
        f"  in-band rate         : {in_band_rate:.0%}   (gate >= {gates['min_in_band']:.0%})"
        f"{d(in_band_rate, 'in_band_rate')}"
    )
    print(
        f"  answer_type accuracy : {at_acc:.0%}   (gate >= {gates['min_at_acc']:.0%})"
        f"{d(at_acc, 'answer_type_accuracy')}"
    )
    print(
        f"  overall MAE          : {mae:.2f} points (vs. band midpoint)"
        f"{d(mae, 'mae', '{:+.2f}')}"
    )
    print(f"  adversarial hard-fails: {len(hard_fails)}   (gate = 0)")
    if fu_acc is not None:
        print(f"  follow_up accuracy   : {fu_acc:.0%}   (n={len(fu_checked)}, soft signal, not gated)")

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
    """Write a versioned, diffable results artifact: provenance + per-item rows."""
    payload = {
        "meta": run_meta(),
        "summary": summarize(results),
        "items": [
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
                "latency_ms": r.latency_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "notes": r.notes,
            }
            for r in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote JSON report -> {path}")


# ---------------------------------------------------------------------------
# Judge calibration: run the scorer N times over the set and measure how
# consistent it is with itself, and how well it agrees with the human bands.
# ---------------------------------------------------------------------------

async def calibrate(items: list[dict], runs: int, concurrency: int, dry_run: bool) -> dict:
    """Score every item `runs` times; return self-consistency + agreement stats."""
    passes = [
        await run(items, concurrency, dry_run, DEFAULT_ADVERSARIAL_MAX) for _ in range(runs)
    ]
    per_item = []
    for idx, item in enumerate(items):
        overalls = [p[idx].score.overall for p in passes if p[idx].score]
        types = [p[idx].score.answer_type for p in passes if p[idx].score]
        lo, hi = item["expected"]["overall_range"]
        per_item.append(
            {
                "id": item["id"],
                "overall_stdev": round(metrics.pstdev(overalls), 2),
                "overall_mean": round(metrics.mean(overalls), 2),
                "answer_type_stability": round(metrics.mode_fraction(types), 2),
                "band_midpoint": (lo + hi) / 2,
                "expected_answer_type": item["expected"]["answer_type"],
            }
        )

    scored = [r for r in per_item if r["overall_mean"] is not None]
    means = [r["overall_mean"] for r in scored]
    mids = [r["band_midpoint"] for r in scored]
    # Modal answer_type per item vs. the human label.
    modal_types = []
    for idx in range(len(items)):
        types = [p[idx].score.answer_type for p in passes if p[idx].score]
        modal_types.append(max(set(types), key=types.count) if types else "")
    expected_types = [item["expected"]["answer_type"] for item in items]

    return {
        "meta": {**run_meta(), "runs": runs},
        "self_consistency": {
            "mean_overall_stdev": round(metrics.mean([r["overall_stdev"] for r in per_item]), 3),
            "mean_answer_type_stability": round(
                metrics.mean([r["answer_type_stability"] for r in per_item]), 3
            ),
        },
        "agreement_vs_human": {
            "spearman_overall_vs_midpoint": round(metrics.spearman(means, mids), 3),
            "cohen_kappa_answer_type": round(metrics.cohen_kappa(modal_types, expected_types), 3),
        },
        "per_item": per_item,
    }


def _report_calibration(report: dict) -> None:
    sc = report["self_consistency"]
    ag = report["agreement_vs_human"]
    print("\n" + "=" * 78)
    print(f"JUDGE CALIBRATION  ({report['meta']['runs']} runs, "
          f"prompt {report['meta']['prompt_version']}, rubric {report['meta']['rubric_version']})")
    print("=" * 78)
    print("  self-consistency (lower stdev / higher stability = more reproducible):")
    print(f"    mean overall stdev        : {sc['mean_overall_stdev']} points")
    print(f"    mean answer_type stability: {sc['mean_answer_type_stability']:.0%}")
    print("  agreement vs. human bands:")
    print(f"    Spearman (overall~midpoint): {ag['spearman_overall_vs_midpoint']}")
    print(f"    Cohen's kappa (answer_type): {ag['cohen_kappa_answer_type']}")
    print("=" * 78 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the answer scorer against the golden set.")
    parser.add_argument("--limit", type=int, default=None, help="Score only the first N items.")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent scoring calls.")
    parser.add_argument("--dry-run", action="store_true", help="No API calls; self-test the harness.")
    parser.add_argument("--min-in-band", type=float, default=DEFAULT_MIN_IN_BAND)
    parser.add_argument("--min-answer-type-acc", type=float, default=DEFAULT_MIN_ANSWER_TYPE_ACC)
    parser.add_argument("--adversarial-max", type=int, default=DEFAULT_ADVERSARIAL_MAX)
    parser.add_argument("--json-out", type=Path, default=None, help="Write a per-item JSON report.")
    parser.add_argument(
        "--baseline", type=Path, default=None,
        help="A previous --json-out report; headline metrics print with their movement since it. "
             "A missing file is treated as no baseline.",
    )
    parser.add_argument(
        "--calibrate", type=int, metavar="N", default=None,
        help="Judge-calibration mode: score the set N times and report self-consistency "
             "and agreement with the human bands (Spearman, Cohen's kappa).",
    )
    args = parser.parse_args()

    data = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    items = data["items"][: args.limit] if args.limit else data["items"]

    if args.dry_run:
        print("(dry run - using fabricated in-band scores, no API calls)")

    if args.calibrate:
        report_data = asyncio.run(
            calibrate(items, args.calibrate, args.concurrency, args.dry_run)
        )
        _report_calibration(report_data)
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(report_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"  wrote calibration report -> {args.json_out}")
        return 0

    results = asyncio.run(
        run(items, args.concurrency, args.dry_run, args.adversarial_max)
    )

    gates = {"min_in_band": args.min_in_band, "min_at_acc": args.min_answer_type_acc}
    baseline = baseline_module.load(args.baseline) if args.baseline else {}
    passed = report(results, gates, baseline)

    if args.json_out:
        _write_json(results, args.json_out)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
