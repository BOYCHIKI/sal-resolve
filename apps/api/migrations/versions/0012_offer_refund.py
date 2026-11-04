"""The OFFER_REFUND card.

Revision ID: 0012
"""
from pathlib import Path

from alembic import op

revision = "0012"
down_revision = "0011"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0012_offer_refund.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    # NOT VALID: cards written under 0012 stay readable; only new rows must meet the old rule again.
    op.get_bind().exec_driver_sql("""
        ALTER TABLE agent_actions DROP CONSTRAINT agent_actions_kind_check;
        ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_kind_check
          CHECK (kind IN ('SEND_EVIDENCE', 'ADD_DOCUMENT', 'REPLY_BEFORE_DEADLINE', 'EXPLAIN_HELD_FUNDS',
                          'EXPLAIN_DISPUTE')) NOT VALID;""")
