"""SAL's MCP server: the protocol handshake, the tool list, and that every call goes through the agent API with the
agent's own token. The API is faked; its own rules are tested in test_deals_api."""
from __future__ import annotations

import json
from typing import Any

import httpx

from app import mcp_server
from app.deals import Invoice, PurchaseOrder

ORDER = {"deal_ref": "PO-MCP-1", "category": "GOODS", "currency": "USD", "max_total": "1300.00",
         "approved_by": "buyer-agent:test", "expires_at": "2027-01-31T00:00:00Z",
         "ship_to": {"country": "AU", "city": "Perth", "postal_code": "6000"},
         "lines": [{"item_code": "BP-1", "description": "Brake pad set", "quantity": "40", "unit_price": "30.00"}]}
INVOICE = {"deal_ref": "PO-MCP-1", "invoice_ref": "INV-1", "issued_at": "2026-11-04T09:00:00+08:00",
           "currency": "USD", "total": "1200.00", "ship_to": ORDER["ship_to"], "lines": ORDER["lines"]}


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(base_url="http://sal.test", headers={"authorization": "Bearer salagent.x.y"},
                        transport=httpx.MockTransport(handler))


def _call(client: httpx.Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    reply = mcp_server.handle(client, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                       "params": {"name": name, "arguments": arguments}})
    assert reply is not None and reply["id"] == 7
    return reply["result"]


def test_handshake_and_tool_list() -> None:
    with _client(lambda request: httpx.Response(500)) as client:
        init = mcp_server.handle(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init is not None and init["result"]["capabilities"] == {"tools": {}}
        assert mcp_server.handle(client, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
        listed = mcp_server.handle(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed is not None
        assert [t["name"] for t in listed["result"]["tools"]] == ["create_order", "send_invoice", "get_deal"]
        unknown = mcp_server.handle(client, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
        assert unknown is not None and unknown["error"]["code"] == -32601


def test_tool_schemas_name_exactly_the_model_fields() -> None:
    schemas = {t["name"]: t["inputSchema"] for t in mcp_server.TOOLS}
    assert set(schemas["create_order"]["properties"]) == set(PurchaseOrder.model_fields)
    assert set(schemas["send_invoice"]["properties"]) == set(Invoice.model_fields) | {"deal_ref"}
    PurchaseOrder.model_validate(ORDER)          # the examples the schemas describe are valid orders and invoices
    Invoice.model_validate({k: v for k, v in INVOICE.items() if k != "deal_ref"})


def test_create_order_posts_the_arguments_with_the_agents_token() -> None:
    seen: list[httpx.Request] = []

    def api(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"deal_ref": "PO-MCP-1", "status": "WAITING_INVOICE"})

    with _client(api) as client:
        result = _call(client, "create_order", ORDER)
    assert result["isError"] is False
    assert seen[0].method == "POST" and seen[0].url.path == "/agent/v1/deals"
    assert seen[0].headers["authorization"] == "Bearer salagent.x.y"
    assert json.loads(seen[0].content) == ORDER


def test_send_invoice_strips_the_deal_ref_and_waits_for_the_verdict() -> None:
    reads = iter(["CHECKING", "HOLD"])
    put_body: list[dict[str, Any]] = []

    def api(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            assert request.url.path == "/agent/v1/deals/PO-MCP-1/invoice"
            put_body.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "CHECKING"})
        return httpx.Response(200, json={"status": next(reads), "findings": [{"code": "QUANTITY_DIFFERS"}]})

    with _client(api) as client:
        result = _call(client, "send_invoice", INVOICE)
    assert "deal_ref" not in put_body[0]
    assert json.loads(result["content"][0]["text"])["status"] == "HOLD"


def test_a_refusal_goes_back_to_the_agent_as_a_tool_error() -> None:
    def api(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": {"code": "AGENT_ROLE_FORBIDDEN"}})

    with _client(api) as client:
        result = _call(client, "create_order", ORDER)
        unknown = _call(client, "delete_everything", {})
    assert result["isError"] is True and "AGENT_ROLE_FORBIDDEN" in result["content"][0]["text"]
    assert unknown["isError"] is True
