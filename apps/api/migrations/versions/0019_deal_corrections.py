"""Correction requests for held deals.

Revision ID: 0019
"""
from pathlib import Path

from alembic import op

revision = "0019"
down_revision = "0018"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0019_deal_corrections.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE deal_corrections")
