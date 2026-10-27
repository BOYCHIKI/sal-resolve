"""Seller-entered tracking numbers and the EXPLAIN_DISPUTE card.

Revision ID: 0010
"""
from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0010_seller_tracking.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    # NOT VALID: rows written under 0010 stay readable; only new rows must meet the old rules again.
    op.get_bind().exec_driver_sql("""
        ALTER TABLE evidence DROP CONSTRAINT evidence_origin_check;
        ALTER TABLE evidence ADD CONSTRAINT evidence_origin_check
          CHECK (origin IN ('UPLOAD', 'PAYPAL_API', 'SEED')) NOT VALID;
        ALTER TABLE evidence DROP CONSTRAINT evidence_mime_check;
        ALTER TABLE evidence ADD CONSTRAINT evidence_mime_check
          CHECK (mime IN ('application/pdf', 'image/jpeg', 'image/png', 'image/gif')) NOT VALID;
        ALTER TABLE agent_actions DROP CONSTRAINT agent_actions_kind_check;
        ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_kind_check
          CHECK (kind IN ('SEND_EVIDENCE', 'ADD_DOCUMENT', 'REPLY_BEFORE_DEADLINE', 'EXPLAIN_HELD_FUNDS')) NOT VALID;""")
