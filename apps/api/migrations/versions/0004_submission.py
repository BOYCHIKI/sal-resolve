"""Draft submission states.

Revision ID: 0004
"""
from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0004_submission.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    # NOT VALID: rows already in the new states must not block a downgrade (tests reset the schema).
    op.get_bind().exec_driver_sql("""
        ALTER TABLE drafts DROP CONSTRAINT drafts_status_check;
        ALTER TABLE drafts ADD CONSTRAINT drafts_status_check CHECK (status IN ('DRAFT', 'APPROVED', 'SUPERSEDED')) NOT VALID;
        ALTER TABLE disputes DROP CONSTRAINT disputes_internal_state_check;
        ALTER TABLE disputes ADD CONSTRAINT disputes_internal_state_check CHECK (internal_state IN
          ('NEW', 'COLLECTING_EVIDENCE', 'ANALYZING', 'NEEDS_REVIEW', 'APPROVED', 'FAILED')) NOT VALID;
    """)
