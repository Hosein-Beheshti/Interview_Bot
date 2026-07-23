"""Record (or replay-verify) the cassette fixture set.

Drives the shared interview scenarios (`fixtures/scenarios.py`) through the real
pipeline — job-profile extraction -> interview plan -> FSM interview loop with
per-answer scoring -> final summary — all through the transport waist
(`services.integrations.transport`).

    TRANSPORT_MODE=record python scripts/record_cassettes.py   # hits real APIs
    TRANSPORT_MODE=replay python scripts/record_cassettes.py   # offline, no keys

Every scenario's final outputs are written to fixtures/recordings/<name>.json
and a content digest is printed, so a record run followed by a replay run can be
compared byte-for-byte: identical digests prove the replay path reproduces the
live run exactly. The contract tests import the same `run_scenario`, so they
freeze exactly what this script records.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from config import settings  # noqa: E402
from fixtures.scenarios import RECORDINGS_DIR, SCENARIOS, run_scenario  # noqa: E402
from services.observability import shutdown as observability_shutdown  # noqa: E402


async def main() -> None:
    mode = settings.transport_mode
    if mode not in ("record", "replay"):
        sys.exit(
            "Refusing to run with transport_mode='live': this script exists to "
            "record or verify cassettes. Set TRANSPORT_MODE=record or TRANSPORT_MODE=replay."
        )
    print(f"transport_mode={mode} | provider={settings.llm_provider}")

    if mode == "record":
        # A record run replaces the whole fixture set: stale cassettes from an
        # earlier or aborted run would otherwise linger as orphans (each run
        # samples different interviewer turns, so hashes rarely collide).
        from services.integrations.transport import cassette_dir

        for stale in cassette_dir().glob("*.json"):
            stale.unlink()
        if RECORDINGS_DIR.is_dir():
            for stale in RECORDINGS_DIR.glob("*.json"):
                stale.unlink()

    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for scenario in SCENARIOS:
        print(f"\n=== {scenario.name} ===")
        output = await run_scenario(scenario)
        blob = json.dumps(output, sort_keys=True, ensure_ascii=False, indent=2)
        (RECORDINGS_DIR / f"{scenario.name}.json").write_text(blob + "\n", encoding="utf-8")
        digests[scenario.name] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        print(f"  trajectory: {' -> '.join(output['trajectory'])}")
        print(f"  digest:     {digests[scenario.name]}")

    print("\nRun digests (a record run and a replay run must match exactly):")
    print(json.dumps(digests, sort_keys=True, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        observability_shutdown()
