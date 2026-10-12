"""Thin PayPal Sandbox REST client that records every exchange as a redacted contract fixture."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from config import CONTRACTS_DIR, SANDBOX_BASE_URL, Config

SECRET_HEADERS = {"authorization", "paypal-auth-assertion"}
SECRET_KEYS = {"access_token", "client_secret", "nonce", "app_id"}
# Account identifiers and personal data are stripped too: recordings go into a public repo.
PII_KEYS = {
    "payer_id", "account_id", "merchant_id", "email_address", "given_name", "surname", "full_name",
    "national_number", "phone_number", "address_line_1", "address_line_2", "postal_code", "admin_area_1",
    "admin_area_2",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redact(value: Any) -> Any:
    """Strip tokens and email addresses before anything is written to disk."""
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if k.lower() in SECRET_KEYS else "[PII]" if k.lower() in PII_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return EMAIL_RE.sub("[EMAIL]", value)
    return value


class PayPalSandboxClient:
    def __init__(self, config: Config, contracts_dir: Path = CONTRACTS_DIR) -> None:
        if config.base_url != SANDBOX_BASE_URL:
            raise ValueError("PayPalSandboxClient only talks to the sandbox host.")
        self.config = config
        self.contracts_dir = contracts_dir
        self._http = httpx.Client(base_url=config.base_url, timeout=30.0)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self.scopes: set[str] = set()

    def token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = self._http.post(
            "/v1/oauth2/token",
            auth=(self.config.client_id, self.config.client_secret),
            data={"grant_type": "client_credentials"},
        )
        self._record("s1_oauth_token", "POST", "/v1/oauth2/token", None, resp)
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self.scopes = set(body.get("scope", "").split())
        self._token_expires_at = time.time() + int(body.get("expires_in", 0))
        return self._token

    def request(
        self,
        method: str,
        path: str,
        *,
        record: str,
        json_body: Any = None,
        files: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        all_headers = {"Authorization": f"Bearer {self.token()}", **(headers or {})}
        if json_body is not None:
            all_headers.setdefault("Content-Type", "application/json")
        resp = self._http.request(
            method, path, headers=all_headers, json=json_body, files=files, data=data
        )
        request_summary = json_body if json_body is not None else data
        if files:
            request_summary = {"form": data, "files": [f[0] if isinstance(f, tuple) else f for f in files]}
        self._record(record, method, path, request_summary, resp)
        return resp

    def _record(self, name: str, method: str, path: str, body: Any, resp: httpx.Response) -> None:
        self.contracts_dir.mkdir(parents=True, exist_ok=True)
        try:
            resp_body: Any = resp.json()
        except ValueError:
            resp_body = resp.text[:2000]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fixture = {
            "recorded_at": stamp,
            "environment": "sandbox",
            "request": {"method": method, "path": path, "body": redact(body)},
            "response": {
                "status": resp.status_code,
                "debug_id": resp.headers.get("paypal-debug-id"),
                "body": redact(resp_body),
            },
        }
        out = self.contracts_dir / f"{stamp}_{name}.json"
        out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
