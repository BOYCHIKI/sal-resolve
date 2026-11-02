"""One open send per dispute.

Revision ID: 0015
"""
from pathlib import Path

from alembic import op

revision = "0015"
down_revision = "0014"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0015_one_send_per_dispute.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP INDEX drafts_one_send_per_dispute")
