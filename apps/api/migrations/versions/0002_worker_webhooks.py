"""PayPal connections, webhook routing errors, job results.

Revision ID: 0002
"""
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0002_worker_webhooks.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE jobs DROP COLUMN IF EXISTS result, DROP COLUMN IF EXISTS payload;
        ALTER TABLE webhook_events DROP COLUMN IF EXISTS error;
        DROP TABLE IF EXISTS paypal_connections;
    """)
