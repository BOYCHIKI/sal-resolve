"""Account routes (ADR-009): sign-up, sign-in, the second step, sessions and the account page's settings.

Called only by the SAL web server, which keeps the session token in an httpOnly cookie and sends it as x-sal-session.
Every reply that starts a session carries the token once; nothing else ever returns it.
"""
from __future__ import annotations

import segno
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app import accounts, agent_identity
from app.config import get_settings

router = APIRouter()


def current_session(x_sal_session: str = Header("")) -> accounts.Session:
    """The signed-in seller (ADR-009). The merchant comes from the session, never from the request."""
    session = accounts.authenticate(x_sal_session)
    if session is None:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "retryable": False})
    return session


def client_address(request: Request) -> str:
    """The browser's address for rate limits. The web server forwards it; trusted only when the internal token
    proves the caller is that server."""
    forwarded = request.headers.get("x-sal-client-ip", "")
    if get_settings().internal_token and forwarded:
        return forwarded[:64]
    return request.client.host if request.client else "unknown"


class SignUpBody(BaseModel):
    model_config = {"extra": "forbid"}
    business_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)


class SignInBody(BaseModel):
    model_config = {"extra": "forbid"}
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)


class CodeBody(BaseModel):
    model_config = {"extra": "forbid"}
    code: str = Field(min_length=6, max_length=20)


class PasswordBody(BaseModel):
    model_config = {"extra": "forbid"}
    current: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)
    new: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)


class TotpOffBody(BaseModel):
    model_config = {"extra": "forbid"}
    password: str = Field(min_length=1, max_length=accounts.MAX_PASSWORD)
    code: str = Field(min_length=6, max_length=20)


def _auth_error(exc: accounts.AuthError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message, "retryable": False})


def _limited(limiter: agent_identity.FailedAttempts, address: str) -> None:
    if limiter.blocked(address):
        raise HTTPException(429, detail={"code": "TOO_MANY_TRIES",
                                         "message": "Too many tries. Wait a minute and try again.",
                                         "retryable": True}, headers={"Retry-After": str(limiter.window_seconds)})


@router.post("/api/auth/signup", status_code=201)
def sign_up(body: SignUpBody, request: Request, user_agent: str = Header("")) -> dict:
    address = client_address(request)
    _limited(accounts.signups, address)
    accounts.signups.record(address)
    try:
        return {"stage": accounts.SessionStage.ACTIVE.value,
                "token": accounts.sign_up(body.business_name, body.email, body.password, user_agent)}
    except accounts.AuthError as exc:
        raise _auth_error(exc) from None


@router.post("/api/auth/login")
def sign_in(body: SignInBody, request: Request, user_agent: str = Header("")) -> dict:
    address = client_address(request)
    _limited(accounts.login_failures, address)
    try:
        stage, token = accounts.sign_in(body.email, body.password, user_agent)
    except accounts.AuthError as exc:
        accounts.login_failures.record(address)
        raise _auth_error(exc) from None
    return {"stage": stage.value, "token": token}


@router.post("/api/auth/mfa")
def finish_sign_in(body: CodeBody, request: Request, x_sal_session: str = Header(""),
                   user_agent: str = Header("")) -> dict:
    """The second step: the pending session's token and a code from the authenticator app or a recovery code."""
    address = client_address(request)
    _limited(accounts.login_failures, address)
    try:
        return {"stage": accounts.SessionStage.ACTIVE.value,
                "token": accounts.finish_sign_in(x_sal_session, body.code, user_agent)}
    except accounts.AuthError as exc:
        accounts.login_failures.record(address)
        raise _auth_error(exc) from None


@router.post("/api/auth/logout")
def sign_out(x_sal_session: str = Header("")) -> dict:
    accounts.end_session(x_sal_session)
    return {"signed_out": True}


@router.post("/api/auth/logout-others")
def sign_out_elsewhere(session: accounts.Session = Depends(current_session)) -> dict:
    return {"signed_out": accounts.end_other_sessions(session)}


@router.get("/api/auth/me")
def me(session: accounts.Session = Depends(current_session)) -> dict:
    return accounts.account(session)


@router.post("/api/auth/password")
def change_password(body: PasswordBody, session: accounts.Session = Depends(current_session)) -> dict:
    try:
        accounts.change_password(session, body.current, body.new)
    except accounts.AuthError as exc:
        raise _auth_error(exc) from None
    return {"changed": True}


@router.post("/api/auth/mfa/setup")
def start_two_step(session: accounts.Session = Depends(current_session)) -> dict:
    """A new authenticator secret as a QR code. It counts only after confirm_two_step accepts a code from it."""
    try:
        started = accounts.start_totp(session)
    except accounts.AuthError as exc:
        raise _auth_error(exc) from None
    return {**started, "qr_svg": segno.make(started["otpauth_uri"], error="m").svg_data_uri(scale=5)}


@router.post("/api/auth/mfa/enable")
def confirm_two_step(body: CodeBody, session: accounts.Session = Depends(current_session)) -> dict:
    """Recovery codes come back here once and are never shown again."""
    try:
        return {"recovery_codes": accounts.confirm_totp(session, body.code)}
    except accounts.AuthError as exc:
        raise _auth_error(exc) from None


@router.post("/api/auth/mfa/disable")
def turn_off_two_step(body: TotpOffBody, session: accounts.Session = Depends(current_session)) -> dict:
    try:
        accounts.turn_off_totp(session, body.password, body.code)
    except accounts.AuthError as exc:
        raise _auth_error(exc) from None
    return {"two_step": False}
