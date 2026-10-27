"""Indexes for the case page and the ops view.

Revision ID: 0008
"""
from pathlib import Path

from alembic import op

revision = "0008"
down_revision = "0007"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0008_query_indexes.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP INDEX jobs_failed_recent_idx; DROP INDEX drafts_analysis_idx;")
