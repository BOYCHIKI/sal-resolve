"""SAL's agent API as an MCP server, so any MCP-capable AI agent can place orders, send invoices and read verdicts.

    SAL_AGENT_TOKEN=salagent.... python -m app.mcp_server     # speaks MCP over stdin/stdout

The server holds no rights of its own: every call goes to /agent/v1/ with the agent's token, and the API decides what
that token may do. A buyer's token can only order and read its own deals; a seller's token can only invoice.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-06-18"
API_URL = os.environ.get("SAL_API_URL", "http://127.0.0.1:8000")
AGENT_DEALS = "/agent/v1/deals"
VERDICT_WAIT_SECONDS = 20

_DECIMAL = {"type": "string", "pattern": r"^\d+(\.\d+)?$", "description": "A decimal string such as '1200.00'"}
_ADDRESS = {
    "type": "object", "additionalProperties": False, "required": ["country", "city"],
    "properties": {"country": {"type": "string", "pattern": "^[A-Z]{2}$", "description": "ISO country code"},
                   "city": {"type": "string"}, "postal_code": {"type": "string"}},
}
_LINES = {
    "type": "array", "minItems": 1,
    "items": {"type": "object", "additionalProperties": False,
              "required": ["item_code", "description", "quantity", "unit_price"],
              "properties": {"item_code": {"type": "string"}, "description": {"type": "string"},
                             "quantity": _DECIMAL, "unit_price": _DECIMAL}},
}
_DEAL_REF = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$"}

TOOLS: list[dict[str, Any]] = [
    {"name": "create_order",
     "description": "Buyer only. Record an approved purchase order with SAL. SAL checks the seller's invoice "
                    "against it and holds the deal on any difference.",
     "inputSchema": {
         "type": "object", "additionalProperties": False,
         "required": ["deal_ref", "category", "currency", "max_total", "approved_by", "expires_at", "lines"],
         "properties": {
             "deal_ref": _DEAL_REF,
             "category": {"type": "string", "enum": ["GOODS", "SERVICE", "DIGITAL"]},
             "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
             "max_total": {**_DECIMAL, "description": "The most the approver allowed, shipping and tax included"},
             "approved_by": {"type": "string", "description": "Must be this agent's own name"},
             "expires_at": {"type": "string", "format": "date-time", "description": "With a time zone"},
             "ship_to": {**_ADDRESS, "description": "Required for GOODS"},
             "lines": _LINES}}},
    {"name": "send_invoice",
     "description": "Seller only. Send the invoice for an order. Waits for SAL's verdict and returns the deal: "
                    "CLEAR means it matches the order, HOLD lists each difference in findings.",
     "inputSchema": {
         "type": "object", "additionalProperties": False,
         "required": ["deal_ref", "invoice_ref", "issued_at", "currency", "total", "lines"],
         "properties": {
             "deal_ref": _DEAL_REF,
             "invoice_ref": _DEAL_REF,
             "issued_at": {"type": "string", "format": "date-time", "description": "With a time zone"},
             "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
             "total": {**_DECIMAL, "description": "Lines plus shipping plus tax"},
             "shipping": _DECIMAL, "tax": _DECIMAL,
             "ship_to": _ADDRESS,
             "lines": _LINES,
             "paypal_transaction_id": {"type": "string", "pattern": "^[A-Z0-9]{17}$",
                                       "description": "The PayPal payment, so a later dispute finds this deal"}}}},
    {"name": "get_deal",
     "description": "Read a deal: the order, the latest invoice, SAL's status (CHECKING, HOLD, CLEAR) and findings.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["deal_ref"],
                     "properties": {"deal_ref": _DEAL_REF}}},
]


class ToolFailed(Exception):
    """SAL refused the call; the message goes back to the agent so it can correct itself."""


def _checked(response: httpx.Response) -> dict[str, Any]:
    if response.is_success:
        return response.json()
    raise ToolFailed(f"SAL answered {response.status_code}: {response.text[:1000]}")


def _wait_for_verdict(client: httpx.Client, deal_ref: str) -> dict[str, Any]:
    deadline = time.monotonic() + VERDICT_WAIT_SECONDS
    deal = _checked(client.get(f"{AGENT_DEALS}/{deal_ref}"))
    while deal["status"] not in ("HOLD", "CLEAR") and time.monotonic() < deadline:
        time.sleep(0.5)
        deal = _checked(client.get(f"{AGENT_DEALS}/{deal_ref}"))
    return deal


def call_tool(client: httpx.Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "create_order":
        return _checked(client.post(AGENT_DEALS, json=arguments))
    if name == "send_invoice":
        invoice = dict(arguments)
        deal_ref = str(invoice.pop("deal_ref", ""))
        _checked(client.put(f"{AGENT_DEALS}/{deal_ref}/invoice", json=invoice))
        return _wait_for_verdict(client, deal_ref)
    if name == "get_deal":
        return _checked(client.get(f"{AGENT_DEALS}/{arguments.get('deal_ref', '')}"))
    raise ToolFailed(f"unknown tool {name}")


def handle(client: httpx.Client, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, its reply out. Notifications get no reply."""
    method, params = message.get("method"), message.get("params") or {}
    if "id" not in message:
        return None
    reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
    if method == "initialize":
        reply["result"] = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                           "serverInfo": {"name": "sal-resolve", "version": "1.0.0"}}
    elif method == "ping":
        reply["result"] = {}
    elif method == "tools/list":
        reply["result"] = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            result, failed = call_tool(client, params.get("name", ""), params.get("arguments") or {}), False
        except (ToolFailed, httpx.HTTPError) as exc:
            result, failed = {"error": str(exc)}, True
        reply["result"] = {"content": [{"type": "text", "text": json.dumps(result)}], "isError": failed}
    else:
        reply["error"] = {"code": -32601, "message": f"method not found: {method}"}
    return reply


def serve(token: str) -> None:
    headers = {"authorization": f"Bearer {token}"}
    with httpx.Client(base_url=API_URL, headers=headers, timeout=15) as client:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None,
                                                "error": {"code": -32700, "message": "parse error"}}
            else:
                reply = handle(client, message)
            if reply is not None:
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()


def main() -> None:
    token = os.environ.get("SAL_AGENT_TOKEN", "")
    if not token:
        raise SystemExit("SAL_AGENT_TOKEN is not set: issue one with python -m app.agent_identity issue")
    serve(token)


if __name__ == "__main__":
    main()
