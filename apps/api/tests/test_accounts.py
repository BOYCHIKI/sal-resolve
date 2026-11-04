"""Seller accounts (ADR-009): passwords, sign-in with an authenticator app, sessions, lockout and tenant isolation."""
from __future__ import annotations

import base64
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app import accounts
from app.accounts import AuthError, SessionStage
from app.db import tenant_session

PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _schema(request):
    if "db" in request.keywords:
        request.getfixturevalue("migrated_db")


def signed_in(token: str, engine) -> accounts.Session:
    """The open session behind a token; the test fails here, plainly, if there is none."""
    session = accounts.authenticate(token, engine=engine)
    assert session is not None, "expected an open session"
    return session


def email() -> str:
    return f"seller-{uuid4().hex[:8]}@example.com"


# ---------------------------------------------------------------- pure parts
def test_a_password_hash_checks_only_the_same_password():
    stored = accounts.hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert accounts.verify_password(PASSWORD, stored)
    assert not accounts.verify_password(PASSWORD + "!", stored)
    assert not accounts.verify_password(PASSWORD, "not a hash")
    assert accounts.hash_password(PASSWORD) != stored   # a fresh salt every time


@pytest.mark.parametrize("weak", ["short", "123456789012", "aaaaaaaaaaaaaaaa", "maya.lin-reads-ledgers"])
def test_weak_passwords_are_refused(weak):
    assert accounts.password_problem(weak, "maya.lin@example.com") is not None


def test_a_long_passphrase_is_accepted():
    assert accounts.password_problem(PASSWORD, "maya.lin@example.com") is None


def test_authenticator_codes_match_rfc_6238_and_are_not_replayed():
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert accounts.totp_code(secret, 59 // 30) == "287082"              # RFC 6238 appendix B, last 6 digits
    step = accounts.check_totp(secret, "287082", None, now=59)
    assert step == 1
    assert accounts.check_totp(secret, "287082", step, now=59) is None     # the same code twice
    assert accounts.check_totp(secret, "000000", None, now=59) is None
    assert accounts.check_totp(secret, "28708", None, now=59) is None


# ---------------------------------------------------------------- sign-up and sign-in
@pytest.mark.db
def test_sign_up_opens_a_session_for_a_new_business(app_engine):
    token = accounts.sign_up("Harbor Supply", email(), PASSWORD, engine=app_engine)
    session = signed_in(token, engine=app_engine)
    assert session is not None and session.stage is SessionStage.ACTIVE
    assert accounts.account(session, engine=app_engine)["business"] == "Harbor Supply"


@pytest.mark.db
def test_an_email_has_one_account_and_weak_passwords_are_refused(app_engine):
    address = email()
    accounts.sign_up("First", address, PASSWORD, engine=app_engine)
    with pytest.raises(AuthError) as taken:
        accounts.sign_up("Second", address.upper(), PASSWORD, engine=app_engine)
    assert taken.value.code == "EMAIL_TAKEN"
    with pytest.raises(AuthError) as weak:
        accounts.sign_up("Third", email(), "short", engine=app_engine)
    assert weak.value.code == "PASSWORD_WEAK"


@pytest.mark.db
def test_wrong_password_and_unknown_email_look_the_same(app_engine):
    address = email()
    accounts.sign_up("Shop", address, PASSWORD, engine=app_engine)
    with pytest.raises(AuthError) as wrong:
        accounts.sign_in(address, "not the password at all", engine=app_engine)
    with pytest.raises(AuthError) as unknown:
        accounts.sign_in(email(), PASSWORD, engine=app_engine)
    assert (wrong.value.status, wrong.value.code, wrong.value.message) == \
        (unknown.value.status, unknown.value.code, unknown.value.message)


@pytest.mark.db
def test_repeated_wrong_passwords_lock_the_account_even_for_the_right_one(app_engine):
    address = email()
    accounts.sign_up("Shop", address, PASSWORD, engine=app_engine)
    for _ in range(accounts.LOCK_AFTER):
        with pytest.raises(AuthError):
            accounts.sign_in(address, "wrong password here", engine=app_engine)
    with pytest.raises(AuthError) as locked:
        accounts.sign_in(address, PASSWORD, engine=app_engine)
    assert locked.value.code == "LOGIN_FAILED"   # same answer as a wrong password


@pytest.mark.db
def test_the_right_password_resets_the_count(app_engine):
    address = email()
    accounts.sign_up("Shop", address, PASSWORD, engine=app_engine)
    for _ in range(accounts.LOCK_AFTER - 1):
        with pytest.raises(AuthError):
            accounts.sign_in(address, "wrong password here", engine=app_engine)
    assert accounts.sign_in(address, PASSWORD, engine=app_engine)[0] is SessionStage.ACTIVE
    with pytest.raises(AuthError):
        accounts.sign_in(address, "wrong password here", engine=app_engine)
    assert accounts.sign_in(address, PASSWORD, engine=app_engine)[0] is SessionStage.ACTIVE


# ---------------------------------------------------------------- two-step sign-in
def _with_authenticator(app_engine) -> tuple[str, str, list[str]]:
    address = email()
    session = signed_in(accounts.sign_up("Shop", address, PASSWORD, engine=app_engine), engine=app_engine)
    secret = accounts.start_totp(session, engine=app_engine)["secret"]
    codes = accounts.confirm_totp(session, accounts.totp_code(secret, accounts.totp_step()), engine=app_engine)
    return address, secret, codes


@pytest.mark.db
def test_with_an_authenticator_the_password_alone_opens_nothing(app_engine):
    address, secret, codes = _with_authenticator(app_engine)
    assert len(codes) == accounts.RECOVERY_CODES
    stage, pending = accounts.sign_in(address, PASSWORD, engine=app_engine)
    assert stage is SessionStage.MFA_PENDING
    assert accounts.authenticate(pending, engine=app_engine) is None   # a pending session can't reach the app
    with pytest.raises(AuthError):
        accounts.finish_sign_in(pending, "000000", engine=app_engine)
    token = accounts.finish_sign_in(pending, accounts.totp_code(secret, accounts.totp_step() + 1), engine=app_engine)
    assert token != pending and accounts.authenticate(token, engine=app_engine) is not None
    assert accounts.authenticate(pending, SessionStage.MFA_PENDING, engine=app_engine) is None   # used up


@pytest.mark.db
def test_a_recovery_code_works_once(app_engine):
    address, _, codes = _with_authenticator(app_engine)
    _, pending = accounts.sign_in(address, PASSWORD, engine=app_engine)
    assert accounts.finish_sign_in(pending, codes[0].upper(), engine=app_engine)
    _, pending = accounts.sign_in(address, PASSWORD, engine=app_engine)
    with pytest.raises(AuthError):
        accounts.finish_sign_in(pending, codes[0], engine=app_engine)


@pytest.mark.db
def test_turning_the_authenticator_off_needs_password_and_code(app_engine):
    address, secret, _ = _with_authenticator(app_engine)
    _, pending = accounts.sign_in(address, PASSWORD, engine=app_engine)
    session = signed_in(
        accounts.finish_sign_in(pending, accounts.totp_code(secret, accounts.totp_step() + 1), engine=app_engine),
        engine=app_engine)
    with pytest.raises(AuthError):
        accounts.turn_off_totp(session, "wrong password here", accounts.totp_code(secret, accounts.totp_step()),
                               engine=app_engine)
    with tenant_session(session.merchant_id, app_engine) as s:   # as if a minute had passed since the last code
        s.execute(text("UPDATE users SET totp_last_step = :step WHERE id = :u"),
                  {"step": accounts.totp_step() - 2, "u": session.user_id})
    accounts.turn_off_totp(session, PASSWORD, accounts.totp_code(secret, accounts.totp_step()), engine=app_engine)
    assert accounts.sign_in(address, PASSWORD, engine=app_engine)[0] is SessionStage.ACTIVE


# ---------------------------------------------------------------- sessions
@pytest.mark.db
def test_signing_out_and_going_idle_end_a_session(app_engine):
    token = accounts.sign_up("Shop", email(), PASSWORD, engine=app_engine)
    session = signed_in(token, engine=app_engine)
    with tenant_session(session.merchant_id, app_engine) as s:
        s.execute(text("UPDATE user_sessions SET last_seen_at = now() - interval '31 minutes' WHERE id = :id"),
                  {"id": session.id})
    assert accounts.authenticate(token, engine=app_engine) is None
    second = accounts.sign_in(accounts.account(session, engine=app_engine)["email"], PASSWORD, engine=app_engine)[1]
    accounts.end_session(second, engine=app_engine)
    assert accounts.authenticate(second, engine=app_engine) is None


@pytest.mark.db
def test_a_forged_or_cross_tenant_token_opens_nothing(app_engine):
    token = accounts.sign_up("Shop", email(), PASSWORD, engine=app_engine)
    _, merchant, secret = token.split(".")
    other = accounts.sign_up("Other", email(), PASSWORD, engine=app_engine).split(".")[1]
    assert accounts.authenticate(f"salsess.{other}.{secret}", engine=app_engine) is None
    assert accounts.authenticate(f"salsess.{merchant}.{secret}x", engine=app_engine) is None
    assert accounts.authenticate("salagent.x.y", engine=app_engine) is None


@pytest.mark.db
def test_changing_the_password_ends_every_other_session(app_engine):
    address = email()
    first = accounts.sign_up("Shop", address, PASSWORD, engine=app_engine)
    second = accounts.sign_in(address, PASSWORD, engine=app_engine)[1]
    session = signed_in(first, engine=app_engine)
    accounts.change_password(session, PASSWORD, "a different long passphrase", engine=app_engine)
    assert accounts.authenticate(second, engine=app_engine) is None
    assert accounts.authenticate(first, engine=app_engine) is not None
    assert accounts.sign_in(address, "a different long passphrase", engine=app_engine)[0] is SessionStage.ACTIVE


# ---------------------------------------------------------------- tenant isolation
@pytest.mark.db
def test_accounts_stay_inside_their_tenant(app_engine):
    token = accounts.sign_up("Shop", email(), PASSWORD, engine=app_engine)
    with tenant_session(uuid4(), app_engine) as s:
        assert s.execute(text("SELECT count(*) FROM users")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM user_sessions")).scalar() == 0
    merchant = token.split(".")[1]
    with tenant_session(uuid4(), app_engine) as s:   # the lookup table itself is out of reach
        with pytest.raises(ProgrammingError):
            s.execute(text("SELECT * FROM login_emails"))
    with tenant_session(uuid4(), app_engine) as s:   # and a new business only for the tenant already set
        with pytest.raises(DBAPIError):
            s.execute(text("SELECT auth_create_merchant(:m, 'Takeover')"), {"m": merchant})


# ---------------------------------------------------------------- over HTTP
@pytest.fixture
def http(migrated_db):
    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides.clear()
    return TestClient(app)


@pytest.mark.db
def test_business_routes_need_a_signed_in_session(http):
    assert http.get("/api/deals").status_code == 401
    assert http.get("/api/deals", headers={"x-sal-session": "salsess.x.y"}).status_code == 401


@pytest.mark.db
def test_sign_up_sign_in_and_reach_only_your_own_data(http):
    address = email()
    r = http.post("/api/auth/signup", json={"business_name": "Harbor Supply", "email": address, "password": PASSWORD})
    assert r.status_code == 201
    token = r.json()["token"]
    me = http.get("/api/auth/me", headers={"x-sal-session": token}).json()
    assert me["email"] == address and me["totp_enabled"] is False and "password" not in str(me)
    assert http.get("/api/deals", headers={"x-sal-session": token}).json()["items"] == []
    r = http.post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["stage"] == "ACTIVE"
    http.post("/api/auth/logout", headers={"x-sal-session": token})
    assert http.get("/api/auth/me", headers={"x-sal-session": token}).status_code == 401


@pytest.mark.db
def test_guessing_passwords_from_one_address_is_slowed_down(http):
    for _ in range(accounts.login_failures.limit):
        assert http.post("/api/auth/login", json={"email": email(), "password": "nope nope nope"}).status_code == 401
    r = http.post("/api/auth/login", json={"email": email(), "password": "nope nope nope"})
    assert r.status_code == 429 and "Retry-After" in r.headers


@pytest.mark.db
def test_two_step_setup_returns_a_qr_and_recovery_codes_once(http):
    token = http.post("/api/auth/signup",
                      json={"business_name": "Shop", "email": email(), "password": PASSWORD}).json()["token"]
    h = {"x-sal-session": token}
    setup = http.post("/api/auth/mfa/setup", headers=h).json()
    assert setup["qr_svg"].startswith("data:image/svg+xml") and setup["otpauth_uri"].startswith("otpauth://totp/")
    code = accounts.totp_code(setup["secret"], accounts.totp_step())
    codes = http.post("/api/auth/mfa/enable", headers=h, json={"code": code}).json()["recovery_codes"]
    assert len(codes) == accounts.RECOVERY_CODES
    assert http.get("/api/auth/me", headers=h).json()["recovery_codes_left"] == accounts.RECOVERY_CODES
