"""SQLAlchemy engine, session factory and declarative base."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

# On serverless (Vercel), each invocation may run in a fresh, short-lived
# container. NullPool opens a connection per request and closes it afterwards,
# avoiding stale/leaked connections held across cold starts. Pair this with a
# *pooled* connection string (e.g. Neon/Supabase PgBouncer) for best results.
# Force UTF-8 client encoding. Without this, psycopg negotiates the encoding
# from the OS locale, which is "C"/POSIX on many serverless runtimes (Vercel)
# and minimal containers -> SQL_ASCII, which makes psycopg return text as raw
# bytes and breaks SQLAlchemy's server-version detection. Pinning utf-8 makes
# the connection behave identically everywhere.
engine = create_engine(
    settings.database_url,
    poolclass=NullPool,
    pool_pre_ping=True,
    future=True,
    connect_args={"client_encoding": "utf-8"},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Imported models register themselves on Base.metadata."""
    from app import models  # noqa: F401  (ensures models are imported)

    Base.metadata.create_all(bind=engine)
