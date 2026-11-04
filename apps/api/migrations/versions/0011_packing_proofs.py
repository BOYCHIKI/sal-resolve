"""Packing proof vault (ADR-007).

Revision ID: 0011
"""
from pathlib import Path

from alembic import op

revision = "0011"
down_revision = "0010"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0011_packing_proofs.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE packing_files; DROP TABLE packing_proofs;")
