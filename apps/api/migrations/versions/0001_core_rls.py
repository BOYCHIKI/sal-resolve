"""Core schema, row-level security, grants.

Revision ID: 0001
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0001_core_rls.sql"


def upgrade() -> None:
    # Raw psycopg execute without params: '%' in PL/pgSQL RAISE is not treated as a placeholder.
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        DROP TABLE IF EXISTS webhook_events, jobs, audit_logs, approvals, drafts, evidence, disputes, merchants;
        DROP FUNCTION IF EXISTS forbid_mutation(), current_merchant_id();
    """)
