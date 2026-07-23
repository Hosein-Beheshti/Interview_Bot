"""Lightweight idempotent schema migrations.

`Base.metadata.create_all()` only creates missing tables — it never alters an
existing one. When new columns are added to a model that maps to a table that
already exists (e.g. the CV columns added to `interview_sessions`), those
columns must be added explicitly. These statements use `IF NOT EXISTS` so they
are safe to run on every startup.
"""
from __future__ import annotations

from sqlalchemy import text

from interview_bot.logger import logger
from interview_bot.persistence.database import engine

_MIGRATIONS = (
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS cv_filename VARCHAR",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS cv_indexed_at TIMESTAMP",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS cv_sections JSON",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS cv_full_text TEXT",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'created'",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS num_questions INTEGER NOT NULL DEFAULT 5",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS job_context TEXT",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS job_profile JSON",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS questions_asked INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS followups_on_current INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS scores JSON NOT NULL DEFAULT '[]'",
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS interview_plan JSON",
)


def run_migrations() -> None:
    """Apply idempotent column additions to pre-existing tables."""
    with engine.begin() as conn:
        for statement in _MIGRATIONS:
            conn.execute(text(statement))
    logger.info("Schema migrations applied")
