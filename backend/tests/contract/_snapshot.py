"""Minimal file-backed snapshot assertions — no third-party dependency.

A snapshot is a committed fixture under `tests/contract/snapshots/`. The test
asserts the current value equals the stored one byte-for-byte. To intentionally
update snapshots after a reviewed change, run:

    UPDATE_SNAPSHOTS=1 python -m pytest backend/tests/contract

We roll our own (rather than add `syrupy`) because the need is ~15 lines and a
plain diffable `.txt`/`.json` file is the most legible thing a reviewer can read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
_UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"


def _check(name: str, actual: str, suffix: str) -> None:
    path = _SNAPSHOT_DIR / f"{name}{suffix}"
    if _UPDATE or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        if not _UPDATE:
            # First-ever run for this snapshot: written, nothing to compare to.
            return
        return
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"Snapshot mismatch for {path.name}.\n"
        f"If this change is intentional, re-run with UPDATE_SNAPSHOTS=1 and "
        f"review the diff — an UNINTENDED prompt/output change is exactly what "
        f"this test must catch."
    )


def assert_snapshot(name: str, text: str) -> None:
    """Assert `text` matches the committed text snapshot `<name>.txt`."""
    _check(name, text, ".txt")


def assert_json_snapshot(name: str, obj) -> None:
    """Assert `obj` matches the committed JSON snapshot `<name>.json`.

    Serialized with sorted keys and indentation so the stored file is stable and
    diff-friendly regardless of dict construction order.
    """
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    _check(name, text, ".json")
