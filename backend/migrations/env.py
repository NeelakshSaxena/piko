"""Alembic environment: online-only, schema-pinned, using the application's engine factory."""

from alembic import context
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db.models import Base
from app.db.session import make_engine


def run() -> None:
    # Tests inject settings (isolated schema); normal runs read the environment.
    settings: Settings = context.config.attributes.get("settings") or get_settings()
    schema = settings.db_schema
    engine = make_engine(settings)
    with engine.connect() as connection:
        # `schema` is validated against SCHEMA_RE and the reserved list by Settings.
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported; run against a database")
run()
