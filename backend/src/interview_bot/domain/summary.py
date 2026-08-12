"""Interview result aggregation.

All scoring roll-up lives here (and on the server), never in the client: the
overall score, the per-answer breakdown with display labels, the deduplicated
strengths/improvements, and the plain-text export. The frontend only renders
what this produces.

A score record (one per answered turn, persisted on the session) has the shape::

    {"q": int, "follow_up": bool, "score": int,
     "strengths": list[str], "improvements": list[str]}

An answer the evaluator could not grade is recorded instead as::

    {"q": int, "follow_up": bool, "unscored": True}

so it is visible as a gap in the result rather than vanishing from it. Only
graded records contribute to the overall score and the breakdown; the count of
ungraded ones is reported alongside, because an average over 4 of 5 answers
presented as if it were the whole interview is a misleading result.
"""
from __future__ import annotations


def _label(record: dict) -> str:
    base = f"Q{record['q']}"
    return f"{base} follow-up" if record.get("follow_up") else base


def _dedup(values: list[str], limit: int = 4) -> list[str]:
    """Order-preserving de-duplication, capped at `limit` items."""
    seen: dict[str, None] = {}
    for v in values:
        if v not in seen:
            seen[v] = None
    return list(seen)[:limit]


def graded(scores: list[dict]) -> list[dict]:
    """The records that carry a real grade (see the module docstring)."""
    return [r for r in scores if not r.get("unscored")]


def build_summary(role: str, scores: list[dict]) -> dict:
    """Aggregate per-answer score records into the interview result summary."""
    scored = graded(scores)
    unscored = len(scores) - len(scored)
    overall = round(sum(r["score"] for r in scored) / len(scored), 1) if scored else 0.0
    breakdown = [{"label": _label(r), "score": r["score"]} for r in scored]
    strengths = _dedup([s for r in scored for s in r.get("strengths", [])])
    improvements = _dedup([s for r in scored for s in r.get("improvements", [])])

    return {
        "role": role,
        "overall": overall,
        "breakdown": breakdown,
        "strengths": strengths,
        "improvements": improvements,
        "unscored": unscored,
        "copy_text": _copy_text(role, overall, scores),
    }


def closing_message(summary: dict) -> str:
    """The interviewer's final wrap-up, rendered deterministically from results.

    The server owns the closing entirely — it is never a model turn — so it can
    neither ask a further question nor be derailed by an instruction embedded in a
    candidate's answer. Derived from `build_summary` output.
    """
    parts = [
        f"That wraps up the interview for the {summary['role']} role — thank you "
        f"for your time.",
        f"Your overall score was {summary['overall']}/10.",
    ]
    if summary.get("unscored"):
        parts.append(_unscored_note(summary["unscored"]))
    if summary["strengths"]:
        parts.append(f"A highlight: {_as_sentence(summary['strengths'][0])}")
    if summary["improvements"]:
        parts.append(f"Something to build on: {_as_sentence(summary['improvements'][0])}")
    parts.append("Wishing you the best.")
    return " ".join(parts)


def _as_sentence(text: str) -> str:
    """Trim and ensure the item ends with sentence punctuation (it may already)."""
    text = text.rstrip()
    return text if text[-1:] in ".?!" else text + "."


def _unscored_note(count: int) -> str:
    """Say plainly that the average does not cover every answer."""
    answers = "answer" if count == 1 else "answers"
    return (
        f"Note: {count} {answers} could not be evaluated, so the score above "
        f"reflects the rest of the interview."
    )


def _copy_text(role: str, overall: float, scores: list[dict]) -> str:
    lines = [
        f"AI Interview Results — {role}",
        f"Overall Score: {overall}/10",
        "",
    ]
    for r in scores:
        if r.get("unscored"):
            lines.append(f"{_label(r)}: not evaluated")
            continue
        lines.append(f"{_label(r)}: {r['score']}/10")
        if r.get("strengths"):
            lines.append(f"  + {', '.join(r['strengths'])}")
        if r.get("improvements"):
            lines.append(f"  › {', '.join(r['improvements'])}")
    return "\n".join(lines)
