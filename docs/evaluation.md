# Evaluation

Prompts and models are not code; changes to them are **measured, not guessed**.
`backend/evals/` holds two golden-set harnesses, named symmetrically as
`run_{X}_eval.py` + `{X}_golden_set.json`:

- **Scorer** (`run_scorer_eval.py` + `scorer_golden_set.json`) — the answer-scoring
  path (`pipeline.scoring.score`). Covered below.
- **Generator** (`run_generator_eval.py` + `generator_golden_set.json`) — the
  question/reply generation + judge path
  (`pipeline.interview.build_turn_prompt` + `pipeline.judge.judge_turn`). Same
  shape (tagged items, human-authored `expected`, adversarial hard-gate,
  `--dry-run`/`--json-out`); run with `make eval-generator` or
  `python -m evals.run_generator_eval`.

Both report CI-runnable quality gates. The rest of this page covers the scorer
harness in detail.

## Running it

```bash
cd backend
make eval                                       # full golden set (REQUIRES provider keys)
python -m evals.run_scorer_eval --limit 5              # cheap smoke test
python -m evals.run_scorer_eval --dry-run              # offline self-test of the harness
python -m evals.run_scorer_eval --json-out report.json # versioned, diffable results artifact
python -m evals.run_scorer_eval --calibrate 5 --json-out cal.json   # judge calibration
```

## What's measured

**Scoring accuracy** (per item, vs. human-authored bands):
- **In-band rate** — fraction whose overall lands in the expected range. Gate: ≥70%.
- **`answer_type` accuracy** — `substantive` / `partial` / `no_answer` classification,
  with a confusion matrix. Gate: ≥75%.
- **Overall MAE** vs. band midpoint; per-dimension band checks.
- **Adversarial hard-gate** — prompt-injection and confidently-wrong items must
  *not* score above `--adversarial-max` (default 6). Any inflation fails the run
  regardless of the aggregates. Gate: 0 hard-fails.

The golden set (`evals/scorer_golden_set.json`, 38 items) is tagged across strong /
good / partial / no-answer tiers, confidently-wrong answers, prompt-injection
attempts, dimension-divergence edge cases, relevance-only diagnostics, and
answer-type boundary cases.

**Judge calibration** (`--calibrate N`): scores the set N times and reports
- **Self-consistency** — mean per-item score standard deviation and mean
  `answer_type` stability (how often the modal label recurs). Lower stdev / higher
  stability ⇒ more reproducible judgments.
- **Agreement with humans** — Spearman rank correlation between the mean overall
  and the band midpoint, and Cohen's kappa between the modal `answer_type` and the
  human label.

The calibration metrics (`evals/metrics.py`) are pure and unit-tested
(`tests/test_eval_metrics.py`) — no numpy/scipy dependency.

## The results artifact

Every `--json-out` run is a versioned, diffable artifact. Its `meta` block records
provenance a score is only comparable within:

```json
{
  "meta": {
    "generated_at": "…Z", "provider": "anthropic", "model": "claude-haiku-4-5-…",
    "prompt_version": "…", "rubric_version": "…",
    "ground_truth": "human-reviewed golden set (scorer_golden_set.json)",
    "reference_key_points": "none (not used in eval scoring)"
  },
  "items": [ { "id": …, "score": {…}, "latency_ms": …, "input_tokens": …, "output_tokens": … } ]
}
```

Per item it records the score, absolute error, latency, and token counts (captured
from the provider's own usage report via the telemetry hook — real cost, not
estimates).

## Known limits

- **Subjective ground truth.** The bands are human-authored but scoring is
  inherently subjective; gates are deliberately lenient (they catch regressions,
  not every off-by-one).
- **Synthetic reference points.** In the *live* interview, a planned question's
  key points are LLM-generated and used to ground scoring. The eval does **not**
  use them — it scores against human bands only — and the artifact marks
  `reference_key_points: none` so unlabeled synthetic ground truth never silently
  acts as truth. If you extend the eval to exercise reference-guided scoring, mark
  those reference points as synthetic in both the code and the artifact.
- **Small set.** 38 items is enough for regression signal, not for tight
  confidence intervals on absolute quality.
- **CI cadence.** The eval needs provider keys, so it runs on manual dispatch or
  the nightly schedule — never on the per-push fast tier.
