"""The document set each analysis read.

Revision ID: 0013
"""
from pathlib import Path

from alembic import op

revision = "0013"
down_revision = "0012"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0013_analysis_evidence_hash.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE analyses DROP COLUMN evidence_hash")
