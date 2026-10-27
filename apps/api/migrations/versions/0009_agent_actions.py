"""Agent action proposals (ADR-006).

Revision ID: 0009
"""
from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0009_agent_actions.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE agent_actions; DROP FUNCTION IF EXISTS agent_actions_app_guard();")
