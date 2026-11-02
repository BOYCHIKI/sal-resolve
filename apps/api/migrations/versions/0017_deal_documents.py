"""PO and invoice files.

Revision ID: 0017
"""
from pathlib import Path

from alembic import op

revision = "0017"
down_revision = "0016"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0017_deal_documents.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE deal_documents")
