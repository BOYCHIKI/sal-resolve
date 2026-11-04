"""Agent credentials, and who sent each side of a deal.

Revision ID: 0016
"""
from pathlib import Path

from alembic import op

revision = "0016"
down_revision = "0015"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0016_agent_credentials.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE deals DROP COLUMN ordered_by, DROP COLUMN invoiced_by")
    op.get_bind().exec_driver_sql("DROP TABLE agent_credentials")
