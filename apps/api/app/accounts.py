"""Seller accounts: sign-up, sign-in with an optional authenticator app, sessions and recovery codes (ADR-009).

    python -m app.accounts add-user <email>    # an account on the demo merchant; asks for the password

Rules that hold everywhere here:
- Passwords are stored as scrypt hashes; codes and tokens only as SHA-256. Nothing secret is logged.
- A wrong email, a wrong password and a locked account give the same answer and take about the same time, so the
  answer never says which emails have accounts.
- A session token reads salsess.<merchant id>.<secret>, like an agent token: the merchant id only picks the tenant,
  so the lookup runs under RLS, and it proves nothing until the secret's hash is found there.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import re
import secrets
import struct
import time
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app import repositories as repo
from app.agent_identity import FailedAttempts
from app.db import tenant_session

TOKEN_PREFIX = "salsess"
SESSION_HOURS = 12            # a session ends after this, however active
IDLE_MINUTES = 30             # and after this long without a request
MFA_PENDING_MINUTES = 5       # time to type the authenticator code after the password
LOCK_AFTER = 5                # wrong passwords or codes in a row before the account waits
MAX_LOCK_MINUTES = 60
MIN_PASSWORD, MAX_PASSWORD = 12, 128
RECOVERY_CODES = 10
TOTP_STEP_SECONDS, TOTP_DIGITS, TOTP_DRIFT_STEPS = 30, 6, 1
ISSUER = "SAL Resolve"

# scrypt, RFC 7914: about 64 MB and a tenth of a second per try on a laptop.
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_LEN = 2 ** 15, 8, 1, 32
_SCRYPT_MAXMEM = 128 * SCRYPT_R * SCRYPT_N * 2

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
# The most used passwords at 12+ characters. A short list on purpose: length does most of the work.
_COMMON = {"123456789012", "password1234", "qwertyuiopas", "111111111111", "passwordpassword", "iloveyou1234",
           "adminadminadmin", "welcome12345", "qwerty123456", "abc123456789", "000000000000", "letmein12345"}

# Per address: wrong sign-ins (20 a minute) and new accounts (5 an hour). Per process, like the agent limit.
login_failures = FailedAttempts(limit=20, window_seconds=60)
signups = FailedAttempts(limit=5, window_seconds=3600)


class SessionStage(StrEnum):
    MFA_PENDING = "MFA_PENDING"
    ACTIVE = "ACTIVE"


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


LOGIN_FAILED = "Email or password is wrong, or the account is waiting a few minutes after repeated tries."


@dataclass(frozen=True)
class Session:
    id: UUID
    merchant_id: UUID
    user_id: UUID
    stage: SessionStage


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN,
                            maxmem=_SCRYPT_MAXMEM)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        given = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                               dklen=len(expected), maxmem=128 * int(r) * int(n) * 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(given, expected)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Checked against when there is no account, so a missing account costs the same time as a wrong password."""
    return hash_password(secrets.token_urlsafe(16))


def password_problem(password: str, email: str) -> str | None:
    """Why a new password is refused, in words for the seller, or None."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters. A short sentence is easy to remember."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    local = email.split("@")[0].lower()
    if password.lower() in _COMMON or len(set(password)) < 4:
        return "This password is too easy to guess."
    if len(local) >= 3 and local in password.lower():
        return "Don’t use your email address in the password."
    return None


# ---------------------------------------------------------------- emails, tokens, codes
def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_hash(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _new_token(merchant_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    return f"{TOKEN_PREFIX}.{merchant_id}.{secret}", _sha256(secret)


def _parse_token(token: str) -> tuple[UUID, str] | None:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    try:
        return UUID(parts[1]), _sha256(parts[2])
    except ValueError:
        return None


# ---------------------------------------------------------------- authenticator codes (RFC 6238)
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()   # 32 characters, no padding


def totp_code(secret: str, step: int) -> str:
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // TOTP_STEP_SECONDS)


def check_totp(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """The time step a code belongs to, or None. A step at or before the last one used is refused (no replay)."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == TOTP_DIGITS):
        return None
    current = totp_step(now)
    for step in range(current - TOTP_DRIFT_STEPS, current + TOTP_DRIFT_STEPS + 1):
        if (last_step is None or step > last_step) and hmac.compare_digest(totp_code(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, email: str) -> str:
    label = quote(f"{ISSUER}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"


def _new_recovery_codes() -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(2)) for _ in range(RECOVERY_CODES)]


def _code_hash(code: str) -> str:
    return _sha256(code.strip().lower().replace(" ", ""))


# ---------------------------------------------------------------- sessions
def _open_session(s, merchant_id: UUID, user_id: UUID, stage: SessionStage, user_agent: str | None) -> str:
    token, token_hash = _new_token(merchant_id)
    life = timedelta(minutes=MFA_PENDING_MINUTES) if stage is SessionStage.MFA_PENDING else timedelta(hours=SESSION_HOURS)
    s.execute(text("""INSERT INTO user_sessions (merchant_id, user_id, token_hash, stage, user_agent, expires_at)
                      VALUES (:m, :u, :h, :stage, :ua, now() + :life)"""),
              {"m": merchant_id, "u": user_id, "h": token_hash, "stage": stage.value,
               "ua": (user_agent or "")[:300] or None, "life": life})
    return token


def authenticate(token: str, stage: SessionStage = SessionStage.ACTIVE, engine: Engine | None = None) -> Session | None:
    """The session behind a token, if it is open, of this stage, and not idle too long. Every failure looks the same."""
    parsed = _parse_token(token) if token else None
    if parsed is None:
        return None
    merchant_id, token_hash = parsed
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""UPDATE user_sessions SET last_seen_at = now()
                                WHERE token_hash = :h AND stage = :stage AND revoked_at IS NULL AND expires_at > now()
                                  AND last_seen_at > now() - :idle
                                RETURNING id, merchant_id, user_id, stage"""),
                        {"h": token_hash, "stage": stage.value, "idle": timedelta(minutes=IDLE_MINUTES)}).first()
    return Session(row.id, row.merchant_id, row.user_id, SessionStage(row.stage)) if row else None


def end_session(token: str, engine: Engine | None = None) -> None:
    parsed = _parse_token(token) if token else None
    if parsed is None:
        return
    merchant_id, token_hash = parsed
    with tenant_session(merchant_id, engine) as s:
        user_id = s.execute(text("""UPDATE user_sessions SET revoked_at = now()
                                    WHERE token_hash = :h AND revoked_at IS NULL RETURNING user_id"""),
                            {"h": token_hash}).scalar()
        if user_id:
            repo.write_audit(s, merchant_id, f"user:{user_id}", "auth.signed_out")


def end_other_sessions(session: Session, engine: Engine | None = None) -> int:
    with tenant_session(session.merchant_id, engine) as s:
        ended = s.execute(text("""UPDATE user_sessions SET revoked_at = now()
                                  WHERE user_id = :u AND id <> :id AND revoked_at IS NULL"""),
                          {"u": session.user_id, "id": session.id}).rowcount
        repo.write_audit(s, session.merchant_id, f"user:{session.user_id}", "auth.signed_out_elsewhere",
                         summary={"sessions": ended})
    return ended


# ---------------------------------------------------------------- sign-up and sign-in
def sign_up(business_name: str, email: str, password: str, user_agent: str | None = None,
            engine: Engine | None = None) -> str:
    """A new business with its first account, signed in. Returns the session token."""
    email, business_name = normalize_email(email), business_name.strip()
    if not 1 <= len(business_name) <= 120:
        raise AuthError(422, "BUSINESS_NAME_INVALID", "Enter your business name (up to 120 characters).")
    if not _EMAIL.match(email):
        raise AuthError(422, "EMAIL_INVALID", "Enter a valid email address.")
    if problem := password_problem(password, email):
        raise AuthError(422, "PASSWORD_WEAK", problem)
    merchant_id, user_id = uuid4(), uuid4()
    hashed = hash_password(password)
    taken = AuthError(409, "EMAIL_TAKEN", "An account with this email already exists. Sign in instead.")
    try:
        with tenant_session(merchant_id, engine) as s:
            if s.execute(text("SELECT 1 FROM auth_find_account(:h)"), {"h": email_hash(email)}).first():
                raise taken
            s.execute(text("SELECT auth_create_merchant(:m, :name)"), {"m": merchant_id, "name": business_name})
            s.execute(text("""INSERT INTO users (id, merchant_id, email, password_hash)
                              VALUES (:u, :m, :email, :hash)"""),
                      {"u": user_id, "m": merchant_id, "email": email, "hash": hashed})
            s.execute(text("SELECT auth_register_login(:h, :u)"), {"h": email_hash(email), "u": user_id})
            repo.write_audit(s, merchant_id, f"user:{user_id}", "auth.signed_up")
            return _open_session(s, merchant_id, user_id, SessionStage.ACTIVE, user_agent)
    except IntegrityError as exc:   # the same email signing up twice at once
        raise taken from exc


def add_user(merchant_id: UUID, email: str, password: str, engine: Engine | None = None) -> UUID:
    """An account on an existing business, for the operator (the demo merchant). Not reachable over HTTP."""
    email = normalize_email(email)
    if not _EMAIL.match(email):
        raise AuthError(422, "EMAIL_INVALID", "Enter a valid email address.")
    if problem := password_problem(password, email):
        raise AuthError(422, "PASSWORD_WEAK", problem)
    user_id = uuid4()
    with tenant_session(merchant_id, engine) as s:
        if s.execute(text("SELECT 1 FROM auth_find_account(:h)"), {"h": email_hash(email)}).first():
            raise AuthError(409, "EMAIL_TAKEN", "An account with this email already exists.")
        s.execute(text("INSERT INTO users (id, merchant_id, email, password_hash) VALUES (:u, :m, :e, :h)"),
                  {"u": user_id, "m": merchant_id, "e": email, "h": hash_password(password)})
        s.execute(text("SELECT auth_register_login(:h, :u)"), {"h": email_hash(email), "u": user_id})
        repo.write_audit(s, merchant_id, "operator", "auth.user_added", target=f"user:{user_id}")
    return user_id


def _find_account(email: str, engine: Engine | None) -> tuple[UUID, UUID] | None:
    """Uses a throwaway tenant id: the lookup function needs no tenant, and the session must have one set."""
    with tenant_session(uuid4(), engine) as s:
        row = s.execute(text("SELECT merchant_id, user_id FROM auth_find_account(:h)"), {"h": email_hash(email)}).first()
    return (row.merchant_id, row.user_id) if row else None


def _register_failure(s, merchant_id: UUID, user_id: UUID, failed: int) -> None:
    failed += 1
    lock = min(2 ** (failed - LOCK_AFTER), MAX_LOCK_MINUTES) if failed >= LOCK_AFTER else 0
    s.execute(text("""UPDATE users SET failed_logins = :f,
                             locked_until = CASE WHEN :lock > 0 THEN now() + make_interval(mins => :lock) ELSE locked_until END
                      WHERE id = :u"""), {"f": failed, "lock": lock, "u": user_id})
    repo.write_audit(s, merchant_id, f"user:{user_id}", "auth.sign_in_failed", summary={"in_a_row": failed})


def sign_in(email: str, password: str, user_agent: str | None = None, engine: Engine | None = None) -> tuple[SessionStage, str]:
    """A session token: ACTIVE, or MFA_PENDING when the account uses an authenticator app."""
    found = _find_account(normalize_email(email), engine)
    if found is None:
        verify_password(password, _dummy_hash())
        raise AuthError(401, "LOGIN_FAILED", LOGIN_FAILED)
    merchant_id, user_id = found
    with tenant_session(merchant_id, engine) as s:
        user = s.execute(text("""SELECT password_hash, totp_enabled, failed_logins,
                                        locked_until IS NOT NULL AND locked_until > now() AS locked
                                 FROM users WHERE id = :u FOR UPDATE"""), {"u": user_id}).first()
        if user is None:
            verify_password(password, _dummy_hash())
            raise AuthError(401, "LOGIN_FAILED", LOGIN_FAILED)
        right = verify_password(password, user.password_hash)   # checked even when locked: same time either way
        if user.locked or not right:
            if not user.locked:
                _register_failure(s, merchant_id, user_id, user.failed_logins)
        else:
            stage = SessionStage.MFA_PENDING if user.totp_enabled else SessionStage.ACTIVE
            if stage is SessionStage.ACTIVE:
                s.execute(text("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = :u"), {"u": user_id})
                repo.write_audit(s, merchant_id, f"user:{user_id}", "auth.signed_in")
            return stage, _open_session(s, merchant_id, user_id, stage, user_agent)
    raise AuthError(401, "LOGIN_FAILED", LOGIN_FAILED)


def finish_sign_in(pending_token: str, code: str, user_agent: str | None = None,
                   engine: Engine | None = None) -> str:
    """Trade a pending session and an authenticator or recovery code for an active session. The pending token is
    ended either way on success, and a new token is issued, so the token seen before the code is never the one used."""
    pending = authenticate(pending_token, SessionStage.MFA_PENDING, engine)
    if pending is None:
        raise AuthError(401, "MFA_EXPIRED", "That took too long. Sign in again.")
    with tenant_session(pending.merchant_id, engine) as s:
        user = s.execute(text("""SELECT totp_secret, totp_last_step, failed_logins,
                                        locked_until IS NOT NULL AND locked_until > now() AS locked
                                 FROM users WHERE id = :u FOR UPDATE"""), {"u": pending.user_id}).first()
        step = None if user.locked else check_totp(user.totp_secret, code, user.totp_last_step)
        used_recovery = False
        if step is None and not user.locked:
            used_recovery = s.execute(text("""UPDATE recovery_codes SET used_at = now()
                                              WHERE user_id = :u AND code_hash = :h AND used_at IS NULL RETURNING id"""),
                                      {"u": pending.user_id, "h": _code_hash(code)}).first() is not None
        if step is None and not used_recovery:
            if not user.locked:
                _register_failure(s, pending.merchant_id, pending.user_id, user.failed_logins)
            ok = False
        else:
            s.execute(text("""UPDATE users SET failed_logins = 0, locked_until = NULL,
                                     totp_last_step = COALESCE(:step, totp_last_step) WHERE id = :u"""),
                      {"step": step, "u": pending.user_id})
            s.execute(text("UPDATE user_sessions SET revoked_at = now() WHERE id = :id"), {"id": pending.id})
            repo.write_audit(s, pending.merchant_id, f"user:{pending.user_id}", "auth.signed_in",
                             summary={"second_step": "recovery_code" if used_recovery else "authenticator"})
            ok = True
            token = _open_session(s, pending.merchant_id, pending.user_id, SessionStage.ACTIVE, user_agent)
    if not ok:
        raise AuthError(401, "MFA_FAILED", "That code didn’t work. Check the time on your phone and try again.")
    return token


# ---------------------------------------------------------------- the account page
def account(session: Session, engine: Engine | None = None) -> dict:
    with tenant_session(session.merchant_id, engine) as s:
        user = s.execute(text("""SELECT u.email, u.totp_enabled, m.name AS business FROM users u
                                 JOIN merchants m ON m.id = u.merchant_id WHERE u.id = :u"""), {"u": session.user_id}).one()
        sessions = s.execute(text("""SELECT id, user_agent, created_at, last_seen_at FROM user_sessions
                                     WHERE user_id = :u AND stage = 'ACTIVE' AND revoked_at IS NULL AND expires_at > now()
                                       AND last_seen_at > now() - :idle ORDER BY last_seen_at DESC"""),
                             {"u": session.user_id, "idle": timedelta(minutes=IDLE_MINUTES)}).all()
        left = s.execute(text("SELECT count(*) FROM recovery_codes WHERE user_id = :u AND used_at IS NULL"),
                         {"u": session.user_id}).scalar()
    return {"email": user.email, "business": user.business, "totp_enabled": user.totp_enabled,
            "recovery_codes_left": left,
            "sessions": [{"id": str(r.id), "this_one": r.id == session.id, "user_agent": r.user_agent,
                          "signed_in_at": r.created_at.isoformat(), "last_seen_at": r.last_seen_at.isoformat()}
                         for r in sessions]}


def start_totp(session: Session, engine: Engine | None = None) -> dict:
    """A new secret, saved but not yet in use: it takes effect only once a code from it is confirmed."""
    secret = new_totp_secret()
    with tenant_session(session.merchant_id, engine) as s:
        row = s.execute(text("""UPDATE users SET totp_secret = :sec WHERE id = :u AND NOT totp_enabled
                                RETURNING email"""), {"sec": secret, "u": session.user_id}).first()
    if row is None:
        raise AuthError(409, "MFA_ALREADY_ON", "Two-step sign-in is already on.")
    return {"secret": secret, "otpauth_uri": otpauth_uri(secret, row.email)}


def confirm_totp(session: Session, code: str, engine: Engine | None = None) -> list[str]:
    """Turn two-step sign-in on with a first code, and hand out recovery codes (shown once, stored hashed)."""
    codes = _new_recovery_codes()
    with tenant_session(session.merchant_id, engine) as s:
        user = s.execute(text("SELECT totp_secret, totp_enabled FROM users WHERE id = :u FOR UPDATE"),
                         {"u": session.user_id}).one()
        if user.totp_enabled:
            raise AuthError(409, "MFA_ALREADY_ON", "Two-step sign-in is already on.")
        step = check_totp(user.totp_secret, code, None) if user.totp_secret else None
        if step is None:
            raise AuthError(422, "MFA_FAILED", "That code didn’t work. Check the time on your phone and try again.")
        s.execute(text("UPDATE users SET totp_enabled = true, totp_last_step = :step WHERE id = :u"),
                  {"step": step, "u": session.user_id})
        s.execute(text("DELETE FROM recovery_codes WHERE user_id = :u"), {"u": session.user_id})
        for c in codes:
            s.execute(text("INSERT INTO recovery_codes (merchant_id, user_id, code_hash) VALUES (:m, :u, :h)"),
                      {"m": session.merchant_id, "u": session.user_id, "h": _code_hash(c)})
        s.execute(text("""UPDATE user_sessions SET revoked_at = now()
                          WHERE user_id = :u AND id <> :id AND revoked_at IS NULL"""),
                  {"u": session.user_id, "id": session.id})
        repo.write_audit(s, session.merchant_id, f"user:{session.user_id}", "auth.mfa_enabled")
    return codes


def turn_off_totp(session: Session, password: str, code: str, engine: Engine | None = None) -> None:
    """Needs the password and a current code, so a stolen open session alone can't remove the second step."""
    with tenant_session(session.merchant_id, engine) as s:
        user = s.execute(text("SELECT password_hash, totp_secret, totp_last_step, totp_enabled FROM users WHERE id = :u FOR UPDATE"),
                         {"u": session.user_id}).one()
        step = check_totp(user.totp_secret, code, user.totp_last_step) if user.totp_enabled else None
        if not (verify_password(password, user.password_hash) and step is not None):
            raise AuthError(422, "CHECK_FAILED", "The password or the code is wrong.")
        s.execute(text("""UPDATE users SET totp_enabled = false, totp_secret = NULL, totp_last_step = NULL
                          WHERE id = :u"""), {"u": session.user_id})
        s.execute(text("DELETE FROM recovery_codes WHERE user_id = :u"), {"u": session.user_id})
        repo.write_audit(s, session.merchant_id, f"user:{session.user_id}", "auth.mfa_disabled")


def change_password(session: Session, current: str, new: str, engine: Engine | None = None) -> None:
    """Ends every other session, so a password changed because of a leak also closes the attacker's way in."""
    with tenant_session(session.merchant_id, engine) as s:
        user = s.execute(text("SELECT email, password_hash FROM users WHERE id = :u FOR UPDATE"),
                         {"u": session.user_id}).one()
        if not verify_password(current, user.password_hash):
            raise AuthError(422, "CHECK_FAILED", "Your current password is wrong.")
        if problem := password_problem(new, user.email):
            raise AuthError(422, "PASSWORD_WEAK", problem)
        s.execute(text("UPDATE users SET password_hash = :h, password_changed_at = now() WHERE id = :u"),
                  {"h": hash_password(new), "u": session.user_id})
        s.execute(text("""UPDATE user_sessions SET revoked_at = now()
                          WHERE user_id = :u AND id <> :id AND revoked_at IS NULL"""),
                  {"u": session.user_id, "id": session.id})
        repo.write_audit(s, session.merchant_id, f"user:{session.user_id}", "auth.password_changed")


def main() -> None:
    from app.config import get_settings
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("add-user").add_argument("email")
    args = parser.parse_args()
    merchant_id = get_settings().demo_merchant_id
    if merchant_id is None:
        raise SystemExit("SAL_DEMO_MERCHANT_ID is not set")
    password = getpass.getpass("Password for the new account (not shown): ")
    if password != getpass.getpass("Type it again: "):
        raise SystemExit("The two passwords differ.")
    try:
        print("account created:", add_user(merchant_id, args.email, password))
    except AuthError as exc:
        raise SystemExit(exc.message) from exc


if __name__ == "__main__":
    main()
