"""Ops: queued-job index, worker heartbeats, LLM token usage.

Revision ID: 0007
"""
from pathlib import Path

from alembic import op

revision = "0007"
down_revision = "0006"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0007_ops.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE agent_runs DROP COLUMN llm_output_tokens;
        ALTER TABLE agent_runs DROP COLUMN llm_input_tokens;
        DROP TABLE worker_heartbeats;
        DROP INDEX jobs_queued_target_idx;
    """)
