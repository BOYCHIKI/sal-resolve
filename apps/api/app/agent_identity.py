"""Who an agent is. Each agent holds its own bearer token, tied to one merchant and one role.

    python -m app.agent_identity issue "buyer-agent:garage-01" BUYER_AGENT
    python -m app.agent_identity list
    python -m app.agent_identity revoke <credential id>

A token reads salagent.<merchant id>.<secret>. The merchant id only says which tenant to look in, so the lookup runs
under RLS like everything else; it proves nothing until the secret's hash is found there. The secret itself is
never stored, and `issue` prints it once. Commands act on the configured demo merchant.
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Engine, text

from app import repositories as repo
from app.db import tenant_session

TOKEN_PREFIX = "salagent"
MAX_FAILURES = 10
FAILURE_WINDOW_SECONDS = 60
MAX_TRACKED_ADDRESSES = 10_000


class AgentRole(StrEnum):
    BUYER_AGENT = "BUYER_AGENT"
    SELLER_AGENT = "SELLER_AGENT"


@dataclass(frozen=True)
class AgentIdentity:
    id: UUID
    merchant_id: UUID
    name: str
    role: AgentRole


class FailedAttempts:
    """Bad tokens per address in a sliding window. In-process: each API process counts for itself."""

    def __init__(self) -> None:
        self._seen: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, address: str, now: float) -> list[float]:
        return [t for t in self._seen.get(address, []) if now - t < FAILURE_WINDOW_SECONDS]

    def blocked(self, address: str) -> bool:
        with self._lock:
            return len(self._recent(address, time.monotonic())) >= MAX_FAILURES

    def record(self, address: str) -> None:
        with self._lock:
            now = time.monotonic()
            if len(self._seen) >= MAX_TRACKED_ADDRESSES:
                self._seen.clear()
            self._seen[address] = [*self._recent(address, now), now]

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


failed_attempts = FailedAttempts()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def issue(merchant_id: UUID, name: str, role: AgentRole, engine: Engine | None = None) -> str:
    secret = secrets.token_urlsafe(32)
    with tenant_session(merchant_id, engine) as s:
        s.execute(text("""INSERT INTO agent_credentials (merchant_id, name, role, token_hash)
                          VALUES (:m, :name, :role, :hash)"""),
                  {"m": merchant_id, "name": name, "role": role.value, "hash": _hash(secret)})
        repo.write_audit(s, merchant_id, "operator", "agent.credential_issued", target=name,
                         summary={"role": role.value})
    return f"{TOKEN_PREFIX}.{merchant_id}.{secret}"


def revoke(merchant_id: UUID, credential_id: UUID, engine: Engine | None = None) -> bool:
    with tenant_session(merchant_id, engine) as s:
        name = s.execute(text("""UPDATE agent_credentials SET revoked_at = now()
                                 WHERE id = :id AND revoked_at IS NULL RETURNING name"""),
                         {"id": credential_id}).scalar()
        if name is None:
            return False
        repo.write_audit(s, merchant_id, "operator", "agent.credential_revoked", target=name)
    return True


def authenticate(token: str, engine: Engine | None = None) -> AgentIdentity | None:
    """The agent behind a token, or None. Every failure looks the same to the caller."""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    try:
        merchant_id = UUID(parts[1])
    except ValueError:
        return None
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""SELECT id, merchant_id, name, role FROM agent_credentials
                                WHERE token_hash = :hash AND revoked_at IS NULL AND expires_at > now()"""),
                        {"hash": _hash(parts[2])}).first()
    return AgentIdentity(row.id, row.merchant_id, row.name, AgentRole(row.role)) if row else None


def main() -> None:
    from app.config import get_settings
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    issuing = commands.add_parser("issue")
    issuing.add_argument("name")
    issuing.add_argument("role", type=AgentRole, choices=list(AgentRole))
    commands.add_parser("list")
    commands.add_parser("revoke").add_argument("credential_id", type=UUID)
    args = parser.parse_args()
    merchant_id = get_settings().demo_merchant_id
    if merchant_id is None:
        raise SystemExit("SAL_DEMO_MERCHANT_ID is not set")
    if args.command == "issue":
        print(issue(merchant_id, args.name, args.role))
    elif args.command == "revoke":
        print("revoked" if revoke(merchant_id, args.credential_id) else "no active credential with that id")
    else:
        with tenant_session(merchant_id, None) as s:
            rows = s.execute(text("""SELECT id, name, role, expires_at, revoked_at FROM agent_credentials
                                     ORDER BY created_at""")).all()
        for row in rows:
            print(row.id, row.name, row.role, "revoked" if row.revoked_at else f"until {row.expires_at:%Y-%m-%d}")


if __name__ == "__main__":
    main()
