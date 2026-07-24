"""Idempotent, forward-only schema statements.

`Base.metadata.create_all()` only creates missing tables — it never alters an
existing one. When a column is added to a model whose table already exists (e.g.
the CV columns added to `interview_sessions`), it must be added explicitly here.

Every statement is written to be safe to re-run, so startup can apply the whole
list unconditionally. `persistence.schema` owns *when* they run and serializes
them behind an advisory lock.
"""
from __future__ import annotations

from sqlalchemy import Connection, text

from interview_bot.logger import logger


def _to_timestamptz(table: str, column: str) -> str:
    """Convert a naive-UTC timestamp column to `timestamptz`, exactly once.

    Guarded on the column's current type rather than written as a bare `ALTER`:
    re-running the conversion on an already-converted column would re-interpret
    the stored instants in the server's local zone and silently shift them.
    """
    return f"""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = '{table}'
              AND column_name = '{column}'
              AND data_type = 'timestamp without time zone'
        ) THEN
            ALTER TABLE {table}
                ALTER COLUMN {column} TYPE TIMESTAMPTZ
                USING {column} AT TIME ZONE 'UTC';
        END IF;
    END $$;
    """


STATEMENTS: tuple[str, ...] = (
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
    "ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS candidate_name VARCHAR",
    # Timestamps are compared against `datetime.now(UTC)` (retention purge, CV
    # freshness), so they must carry a zone rather than rely on every writer
    # happening to pass naive UTC.
    _to_timestamptz("interview_sessions", "created_at"),
    _to_timestamptz("interview_sessions", "cv_indexed_at"),
    _to_timestamptz("cv_chunks", "created_at"),
    # The retention purge selects by age; without this it is a full table scan.
    "CREATE INDEX IF NOT EXISTS ix_interview_sessions_created_at "
    "ON interview_sessions (created_at)",
)


def apply(conn: Connection) -> None:
    """Apply every statement on the given connection. The caller owns the transaction."""
    for statement in STATEMENTS:
        conn.execute(text(statement))
    logger.info(f"Schema migrations applied | statements={len(STATEMENTS)}")
