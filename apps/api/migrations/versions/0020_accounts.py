"""Seller accounts, sessions and two-step sign-in.

Revision ID: 0020
"""
from pathlib import Path

from alembic import op

revision = "0020"
down_revision = "0019"

SQL = Path(__file__).resolve().parents[1] / "sql" / "0020_accounts.sql"


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DROP FUNCTION auth_find_account(text), auth_create_merchant(uuid, text), auth_register_login(text, uuid);"
        "DROP TABLE login_emails, recovery_codes, user_sessions, users")
