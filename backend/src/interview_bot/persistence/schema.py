"""Startup schema preparation — the one place that issues DDL.

Enabling the pgvector extension, creating missing tables, and applying the
idempotent column migrations all mutate the schema. Replicas booting
simultaneously would race: concurrent `CREATE TABLE IF NOT EXISTS` and `ALTER
TABLE` on the same relation deadlock or fail outright. A transaction-scoped
Postgres advisory lock serializes them — the first process does the work, the
rest wait and then find nothing left to do.

Called once per process from the API lifespan, and exposed as a module entry
point (`python -m interview_bot.persistence.schema`) so the same work can run as
a pre-deploy release step instead.
"""
from __future__ import annotations

from sqlalchemy import text

from interview_bot.logger import logger
from interview_bot.persistence import migrations
from interview_bot.persistence.database import engine
from interview_bot.persistence.models import Base

# Fixed, arbitrary application-wide key. Transaction-scoped (`_xact_`), so the
# lock is always released when the transaction ends — including on failure.
_ADVISORY_LOCK_KEY = 8_274_193_055


def initialize() -> None:
    """Bring the database schema up to date. Idempotent and replica-safe."""
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(bind=conn)
        migrations.apply(conn)
    logger.info("Database schema ready")


if __name__ == "__main__":
    initialize()
