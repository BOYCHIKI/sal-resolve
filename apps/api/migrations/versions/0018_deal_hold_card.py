"""The REVIEW_DEAL_HOLD card.

Revision ID: 0018
"""
from pathlib import Path

from alembic import op

revision = "0018"
down_revision = "0017"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0018_deal_hold_card.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE agent_actions DROP CONSTRAINT agent_actions_kind_check")
    op.get_bind().exec_driver_sql(
        "ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_kind_check CHECK (kind IN ('SEND_EVIDENCE', "
        "'ADD_DOCUMENT', 'REPLY_BEFORE_DEADLINE', 'EXPLAIN_HELD_FUNDS', 'EXPLAIN_DISPUTE', 'OFFER_REFUND')) NOT VALID")
