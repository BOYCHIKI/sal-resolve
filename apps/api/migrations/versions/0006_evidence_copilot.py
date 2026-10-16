"""Evidence origin and the ASSESS result (ADR-005).

Revision ID: 0006
"""
from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0006_evidence_copilot.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    # PayPal-fetched documents have no file; they cannot survive a NOT NULL object_key.
    op.get_bind().exec_driver_sql("""
        ALTER TABLE evidence NO FORCE ROW LEVEL SECURITY;
        DELETE FROM evidence WHERE object_key IS NULL;
        ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
        ALTER TABLE analyses DROP COLUMN assessment;
        ALTER TABLE evidence ALTER COLUMN object_key SET NOT NULL;
        ALTER TABLE evidence DROP COLUMN origin;
    """)
