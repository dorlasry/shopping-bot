"""Database engine and session management (synchronous SQLAlchemy 2.0).

Why sync (not async): for a chat bot with modest concurrency, sync SQLAlchemy is
simpler, has fewer foot-guns (no session-per-task lifecycle bugs), and is trivial
to reason about during a live demo. FastAPI runs sync handlers in a threadpool,
so this does not block the event loop. Moving to async later is a contained change.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

def _normalize_db_url(url: str) -> str:
    """Make managed-Postgres URLs work with the psycopg (v3) driver.

    Hosts like Railway/Render/Heroku hand out `postgres://` or `postgresql://`
    URLs, but SQLAlchemy needs the driver spelled out for psycopg 3:
    `postgresql+psycopg://`. Normalizing here means the platform's DATABASE_URL
    works as-is with no manual editing.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_db_url = _normalize_db_url(settings.database_url)

# SQLite needs check_same_thread=False because FastAPI may touch the session
# from different threadpool threads. Harmless/irrelevant for Postgres.
_connect_args = {"check_same_thread": False} if _db_url.startswith("sqlite") else {}

engine = create_engine(
    _db_url,
    echo=False,
    future=True,
    pool_pre_ping=True,  # transparently recover dropped Postgres connections
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create tables if they don't exist.

    Fine for the MVP. For production, replace with Alembic migrations so schema
    changes are versioned and reversible.
    """
    from app.domain import models  # noqa: F401  (ensure models are imported/registered)

    models.Base.metadata.create_all(bind=engine)
