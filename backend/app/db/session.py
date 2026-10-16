"""Engine and session factory. All connections are pinned to the configured schema."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import SCHEMA_RE, Settings


def make_engine(settings: Settings) -> Engine:
    if not SCHEMA_RE.fullmatch(settings.db_schema):
        raise ValueError("unsafe schema name")
    url = make_url(settings.database_url.get_secret_value())
    return create_engine(
        url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": 10,
            # Pins search_path at connection start (works with Supabase session pooler).
            "options": f"-c search_path={settings.db_schema} -c timezone=UTC",
        },
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One session per request. Services commit explicitly; anything uncommitted rolls back."""
    with factory() as session:
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
