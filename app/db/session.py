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

# SQLite needs check_same_thread=False because FastAPI may touch the session
# from different threadpool threads. Harmless for other backends.
_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
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
