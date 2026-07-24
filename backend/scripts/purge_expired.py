"""Erase interview sessions past the retention window.

Meant to run on a schedule (a platform cron job, or `docker compose run`), not
from inside the API process: a background thread in a web worker would run once
per replica, compete with request traffic, and stop silently the moment a deploy
restarted the container.

    python scripts/purge_expired.py                 # use settings.session_retention_days
    python scripts/purge_expired.py --days 7
    python scripts/purge_expired.py --dry-run       # report only, delete nothing
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from interview_bot.config import settings
from interview_bot.persistence import sessions as session_store
from interview_bot.persistence import usage
from interview_bot.persistence.database import SessionLocal
from interview_bot.persistence.models import InterviewSession

# Rate-limit windows are at most a day, so counters older than this are closed
# and only take up space.
_COUNTER_RETENTION = timedelta(days=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete sessions past the retention window.")
    parser.add_argument(
        "--days",
        type=int,
        default=settings.session_retention_days,
        help="Retention window in days (default: settings.session_retention_days).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without deleting it.",
    )
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be at least 1")

    cutoff = datetime.now(UTC) - timedelta(days=args.days)

    with SessionLocal() as db:
        if args.dry_run:
            doomed = db.execute(
                select(func.count())
                .select_from(InterviewSession)
                .where(InterviewSession.created_at < cutoff)
            ).scalar_one()
            print(f"Would delete {doomed} session(s) created before {cutoff.isoformat()}.")
            return
        deleted = session_store.delete_created_before(db, cutoff)
        print(f"Deleted {deleted} session(s) created before {cutoff.isoformat()}.")

    counters = usage.delete_windows_before(datetime.now(UTC) - _COUNTER_RETENTION)
    print(f"Deleted {counters} closed rate-limit counter(s).")


if __name__ == "__main__":
    main()
