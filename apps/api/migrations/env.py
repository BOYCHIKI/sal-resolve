"""Alembic runs DDL as sal_migrator only."""
from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings

engine = create_engine(get_settings().migrator_database_url)
with engine.connect() as connection:
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
