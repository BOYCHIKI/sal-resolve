"""Two AI agents, a buyer's and a seller's, that use SAL through its MCP server. Each runs on the OpenAI model in
SAL_LLM_MODEL, holds its own SAL credential and decides its own tool calls; nothing about their calls is scripted.

    python -m app.ai_agents

1. The buyer's agent turns an approved purchase into an order.
2. The seller's billing system sends an invoice with a wrong item code. This step is fixed on purpose, so the
   mistake is the same on every run.
3. SAL holds the deal. The seller's agent finds out why and sends a corrected invoice.
4. The buyer's agent reads the verdict and decides whether to pay.

Needs the API and the worker running, and SAL_LLM_API_KEY. Everything the agents send is invented.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4

from openai import OpenAI

from app import agent_identity
from app.agent_identity import AgentRole
from app.config import get_settings

MAX_TURNS = 8
BUYER_NAME = "buyer-agent:garage-01"
SELLER_NAME = "seller-agent:parts-supplier"


class McpClient:
    """Starts SAL's MCP server for one agent's token and talks to it over stdin/stdout."""

    def __init__(self, token: str) -> None:
        self._next_id = 0
        self._server = subprocess.Popen([sys.executable, "-m", "app.mcp_server"], text=True, encoding="utf-8",
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        env={**os.environ, "SAL_AGENT_TOKEN": token})
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "sal-demo-agent", "version": "1.0.0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.tools: list[dict[str, Any]] = self.request("tools/list", {})["tools"]

    def _send(self, message: dict[str, Any]) -> None:
        assert self._server.stdin is not None
        self._server.stdin.write(json.dumps(message) + "\n")
        self._server.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})
        assert self._server.stdout is not None
        reply = json.loads(self._server.stdout.readline() or "null")
        if not reply or "error" in reply:
            raise RuntimeError(f"MCP {method} failed: {reply}")
        return reply["result"]

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        return self.request("tools/call", {"name": name, "arguments": arguments})["content"][0]["text"]

    def close(self) -> None:
        if self._server.stdin is not None:
            self._server.stdin.close()
        self._server.wait(timeout=10)


def run_agent(llm: OpenAI, label: str, mcp: McpClient, instructions: str, task: str) -> str:
    """Let the model work the task with SAL's tools until it answers in plain text."""
    cfg = get_settings()
    options: dict[str, Any] = {}
    if cfg.llm_reasoning_effort:
        options["reasoning_effort"] = cfg.llm_reasoning_effort
    tools: Any = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                    "parameters": t["inputSchema"]}} for t in mcp.tools]
    messages: list[Any] = [{"role": "system", "content": instructions}, {"role": "user", "content": task}]
    for _ in range(MAX_TURNS):
        reply = llm.chat.completions.create(model=cfg.llm_model, messages=messages, tools=tools, **options)
        message = reply.choices[0].message
        messages.append(message)
        if not message.tool_calls:
            print(f"{label} says: {message.content}")
            return message.content or ""
        for tool_call in message.tool_calls:
            function = getattr(tool_call, "function", None)
            if function is None:
                continue
            result = mcp.call(function.name, json.loads(function.arguments or "{}"))
            print(f"{label} -> {function.name}  SAL: {_summary(result)}")
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
    raise SystemExit(f"{label} did not finish in {MAX_TURNS} turns")


def _summary(result: str) -> str:
    data = json.loads(result)
    if "error" in data:
        return f"refused, {data['error'][:160]}"
    codes = [f["code"] for f in data.get("findings", [])]
    return f"{data.get('status')} {codes}" if codes else str(data.get("status"))


SHARED_RULES = ("You act for a business through SAL Resolve, which checks invoices against purchase orders. "
                "Use the tools; never guess a value you can read. Amounts and quantities are decimal strings "
                "like '30.00'. Times carry a time zone. Today is 2026-11-04.")


def run(merchant_id: UUID, llm: OpenAI) -> str:
    ref = f"PO-{uuid4().hex[:6].upper()}"
    buyer_token = agent_identity.issue(merchant_id, BUYER_NAME, AgentRole.BUYER_AGENT)
    seller_token = agent_identity.issue(merchant_id, SELLER_NAME, AgentRole.SELLER_AGENT)
    buyer, seller = McpClient(buyer_token), McpClient(seller_token)
    try:
        print(f"1. Buyer's agent places order {ref}")
        run_agent(llm, "buyer agent ", buyer, SHARED_RULES + f" You are {BUYER_NAME}, a workshop's buyer.",
                  f"The workshop manager approved buying 40 brake pad sets, item code BP-2217-A, at 30.00 USD each, "
                  f"delivered to Perth, postal code 6000, Australia (AU). The approval allows at most 1300.00 USD "
                  f"and ends 2027-01-31T00:00:00Z. Record this as order {ref} with SAL, with approved_by set to "
                  f"exactly {BUYER_NAME}, then confirm in one line.")
        if "error" in json.loads(buyer.call("get_deal", {"deal_ref": ref})):
            raise SystemExit(f"The buyer's agent did not place order {ref}; stopping.")

        print("2. Seller's billing system sends an invoice with a wrong item code")
        wrong_invoice = {"deal_ref": ref, "invoice_ref": f"INV-{ref}", "issued_at": "2026-11-04T09:00:00+08:00",
                         "currency": "USD", "total": "1200.00",
                         "ship_to": {"country": "AU", "city": "Perth", "postal_code": "6000"},
                         "lines": [{"item_code": "BP-2217-B", "description": "Brake pad set", "quantity": "40",
                                    "unit_price": "30.00"}]}
        print(f"billing      -> send_invoice  SAL: {_summary(seller.call('send_invoice', wrong_invoice))}")

        print("3. Seller's agent fixes what SAL found")
        run_agent(llm, "seller agent", seller, SHARED_RULES + f" You are {SELLER_NAME}, a parts supplier's agent. "
                  "Fix only what SAL reports. Never raise a price or add an item the buyer did not order.",
                  f"SAL held invoice INV-{ref} for order {ref}. Read the deal, work out what differs from the "
                  f"order, and send a corrected invoice with invoice_ref INV-{ref}-R1. Report the result in one line.")

        print("4. Buyer's agent decides whether to pay")
        return run_agent(llm, "buyer agent ", buyer, SHARED_RULES + f" You are {BUYER_NAME}.",
                         f"Check order {ref} with SAL. Answer PAY only if SAL's status is CLEAR, otherwise WAIT, "
                         "followed by one sentence saying why.")
    finally:
        buyer.close()
        seller.close()
        for token in (buyer_token, seller_token):
            agent = agent_identity.authenticate(token)
            if agent is not None:
                agent_identity.revoke(merchant_id, agent.id)


def main() -> None:
    cfg = get_settings()
    if cfg.demo_merchant_id is None:
        raise SystemExit("SAL_DEMO_MERCHANT_ID is not set")
    if not (cfg.llm_api_key and cfg.llm_model):
        raise SystemExit("SAL_LLM_API_KEY and SAL_LLM_MODEL are needed in apps/api/.env")
    llm = OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url or None, max_retries=2, timeout=60)
    run(cfg.demo_merchant_id, llm)


if __name__ == "__main__":
    main()
