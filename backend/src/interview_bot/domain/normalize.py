"""Shared normalization for model-extracted string fields.

The profile and plan extractions both need to clean the model's free-form string
lists the same way, so that logic lives here once.
"""
from __future__ import annotations


def clean_optional(value) -> str | None:
    """A trimmed non-empty string, or None."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def dedupe_capped(value, limit: int) -> tuple[str, ...]:
    """Trim, drop blanks, dedupe case-insensitively, and cap to `limit` items."""
    if not isinstance(value, list):
        return ()
    seen: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text.lower() not in (s.lower() for s in seen):
            seen.append(text)
        if len(seen) >= limit:
            break
    return tuple(seen)
