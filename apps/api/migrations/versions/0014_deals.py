"""Deals and their checks.

Revision ID: 0014
"""
from pathlib import Path

from alembic import op

revision = "0014"
down_revision = "0013"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0014_deals.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE deal_checks")
    op.get_bind().exec_driver_sql("DROP TABLE deals")
