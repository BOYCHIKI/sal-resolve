"""PayPal-Auth-Assertion builder for buyer-side sandbox calls.

Unsigned JWT ({"alg": "none"}) identifying the buyer by email, as shown in PayPal's sandbox
dispute samples. The construction is not formally documented on the test page — S3 verifies it.
"""
from __future__ import annotations

import base64
import json


def _b64url(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def build_auth_assertion(client_id: str, buyer_email: str) -> str:
    return f"{_b64url({'alg': 'none'})}.{_b64url({'iss': client_id, 'email': buyer_email})}."
