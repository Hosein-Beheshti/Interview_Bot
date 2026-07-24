"""Interview result aggregation.

All scoring roll-up lives here (and on the server), never in the client: the
overall score, the per-answer breakdown with display labels, the deduplicated
strengths/improvements, and the plain-text export. The frontend only renders
what this produces.

A score record (one per answered turn, persisted on the session) has the shape::

    {"q": int, "follow_up": bool, "score": int,
     "strengths": list[str], "improvements": list[str]}
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


def build_summary(role: str, scores: list[dict]) -> dict:
    """Aggregate per-answer score records into the interview result summary."""
    overall = round(sum(r["score"] for r in scores) / len(scores), 1) if scores else 0.0
    breakdown = [{"label": _label(r), "score": r["score"]} for r in scores]
    strengths = _dedup([s for r in scores for s in r.get("strengths", [])])
    improvements = _dedup([s for r in scores for s in r.get("improvements", [])])

    return {
        "role": role,
        "overall": overall,
        "breakdown": breakdown,
        "strengths": strengths,
        "improvements": improvements,
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


def _copy_text(role: str, overall: float, scores: list[dict]) -> str:
    lines = [
        f"AI Interview Results — {role}",
        f"Overall Score: {overall}/10",
        "",
    ]
    for r in scores:
        lines.append(f"{_label(r)}: {r['score']}/10")
        if r.get("strengths"):
            lines.append(f"  + {', '.join(r['strengths'])}")
        if r.get("improvements"):
            lines.append(f"  › {', '.join(r['improvements'])}")
    return "\n".join(lines)
