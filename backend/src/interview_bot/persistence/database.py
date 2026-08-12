from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from interview_bot.config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    # Managed Postgres drops idle connections without telling the pool, so a
    # checkout can hand out a dead socket. Pre-ping validates on the way out and
    # reconnects transparently; recycle retires connections before the server's
    # own idle timeout can reach them. See the notes in config.py.
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
