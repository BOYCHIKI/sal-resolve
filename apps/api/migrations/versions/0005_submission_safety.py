"""Approval bound to evidence; data for reconciling interrupted sends.

Revision ID: 0005
"""
from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0005_submission_safety.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE drafts DROP COLUMN submit_note;
        ALTER TABLE drafts DROP COLUMN submit_started_at;
        ALTER TABLE approvals DROP COLUMN evidence_hash;
    """)
