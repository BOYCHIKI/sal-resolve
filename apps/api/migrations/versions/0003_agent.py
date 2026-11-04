"""Agent runs, tool calls, analyses; evidence text; draft claims.

Revision ID: 0003
"""
from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0003_agent.sql"


def upgrade() -> None:
    driver = op.get_bind().connection.driver_connection   # psycopg runs the whole file, $$ blocks included
    assert driver is not None, "migrations need a live database connection"
    driver.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE drafts DROP CONSTRAINT IF EXISTS drafts_analysis_fk;
        ALTER TABLE drafts DROP COLUMN IF EXISTS analysis_id, DROP COLUMN IF EXISTS claims;
        DROP TABLE IF EXISTS analyses, tool_calls, agent_runs;
        ALTER TABLE evidence DROP COLUMN IF EXISTS doc_type, DROP COLUMN IF EXISTS content_lines,
                             DROP COLUMN IF EXISTS source_ref;
    """)
