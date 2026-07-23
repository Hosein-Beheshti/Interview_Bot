"""Pure calibration metrics for the eval harness.

No I/O, no LLM — just statistics over already-collected scores, so they are unit
tested directly (see tests/test_eval_metrics.py). Kept dependency-free (no numpy
/scipy) so the eval harness stays lightweight.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def pstdev(xs: Sequence[float]) -> float:
    """Population standard deviation (0 for <2 points)."""
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _ranks(xs: Sequence[float]) -> list[float]:
    """Fractional ranks, averaging ties (1-based)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # average 1-based rank over the tie block
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation; 0.0 when either series is constant or too short."""
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation = Pearson on ranks."""
    return pearson(_ranks(xs), _ranks(ys))


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two raters' categorical labels.

    Returns 1.0 for perfect agreement, 0.0 for chance-level. When both raters are
    perfectly and identically constant, agreement is total, so returns 1.0.
    """
    if len(a) != len(b) or not a:
        return 0.0
    n = len(a)
    po = sum(1 for x, y in zip(a, b, strict=False) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def mode_fraction(labels: Sequence[str]) -> float:
    """Fraction of labels equal to the most common one (per-item stability)."""
    if not labels:
        return 0.0
    return Counter(labels).most_common(1)[0][1] / len(labels)
