"""Simulated buyer and seller agents for the demo. They talk to SAL through the agent API, each with its own
credential, which is issued for the run and revoked after it.

    python -m app.simulate_agents           # one order, a wrong invoice, then the corrected invoice
    python -m app.simulate_agents --service # the same for a services deal

These are scripts, not real agents, and everything they send is invented.
"""
from __future__ import annotations

import argparse
import time
from typing import Any
from uuid import uuid4

import httpx

from app import agent_identity
from app.agent_identity import AgentRole
from app.config import get_settings

API_URL = "http://127.0.0.1:8000"
AGENT_DEALS = "/agent/v1/deals"
WAIT_SECONDS = 15


def _goods_deal(ref: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ship_to = {"country": "AU", "city": "Perth", "postal_code": "6000"}
    line = {"item_code": "BP-2217-A", "description": "Brake pad set", "quantity": "40", "unit_price": "30.00"}
    order = {"deal_ref": ref, "category": "GOODS", "currency": "USD", "max_total": "1300.00",
             "approved_by": "buyer-agent:garage-01", "expires_at": "2027-01-31T00:00:00Z", "ship_to": ship_to,
             "lines": [line]}
    invoice = {"invoice_ref": f"INV-{ref}", "issued_at": "2026-11-03T09:00:00+07:00", "currency": "USD",
               "total": "1200.00", "ship_to": ship_to, "lines": [line]}
    return order, {**invoice, "lines": [{**line, "item_code": "BP-2217-B"}]}, invoice


def _service_deal(ref: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    line = {"item_code": "SITE-AUDIT", "description": "Website audit", "quantity": "10", "unit_price": "80.00"}
    order = {"deal_ref": ref, "category": "SERVICE", "currency": "USD", "max_total": "800.00",
             "approved_by": "buyer-agent:procurement-02", "expires_at": "2027-01-31T00:00:00Z", "lines": [line]}
    invoice = {"invoice_ref": f"INV-{ref}", "issued_at": "2026-11-03T09:00:00+07:00", "currency": "USD",
               "total": "800.00", "lines": [line]}
    return order, {**invoice, "total": "960.00", "lines": [{**line, "quantity": "12"}]}, invoice


def _wait_for_verdict(client: httpx.Client, ref: str) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        deal = client.get(f"{AGENT_DEALS}/{ref}").raise_for_status().json()
        if deal["status"] in ("HOLD", "CLEAR"):
            return deal
        time.sleep(0.5)
    raise SystemExit("No verdict in time. Is the worker running?")


def _client(token: str) -> httpx.Client:
    return httpx.Client(base_url=API_URL, headers={"authorization": f"Bearer {token}"}, timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="store_true")
    args = parser.parse_args()
    merchant_id = get_settings().demo_merchant_id
    if merchant_id is None:
        raise SystemExit("SAL_DEMO_MERCHANT_ID is not set")
    ref = f"PO-{uuid4().hex[:6].upper()}"
    order, wrong_invoice, right_invoice = (_service_deal if args.service else _goods_deal)(ref)
    tokens = (agent_identity.issue(merchant_id, order["approved_by"], AgentRole.BUYER_AGENT),
              agent_identity.issue(merchant_id, "seller-agent:demo", AgentRole.SELLER_AGENT))
    try:
        with _client(tokens[0]) as buyer, _client(tokens[1]) as seller:
            print(f"buyer agent  -> order {ref}")
            buyer.post(AGENT_DEALS, json=order).raise_for_status()
            for label, invoice in (("wrong invoice", wrong_invoice), ("corrected invoice", right_invoice)):
                print(f"seller agent -> {label}")
                seller.put(f"{AGENT_DEALS}/{ref}/invoice", json=invoice).raise_for_status()
                deal = _wait_for_verdict(buyer, ref)
                print(f"SAL          <- {deal['status']} {[f['code'] for f in deal['findings']]}")
    finally:
        for token in tokens:
            agent = agent_identity.authenticate(token)
            if agent is not None:
                agent_identity.revoke(merchant_id, agent.id)


if __name__ == "__main__":
    main()
