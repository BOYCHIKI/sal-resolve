"""PayPal Sandbox spike for gate G1. Run steps in order: s1 -> s8.

    python spike.py s1                                  # OAuth
    python spike.py s2-order  --case SAL-INR-001        # create order, prints approve link
    python spike.py s2-capture                          # capture after buyer approves
    python spike.py s3 --buyer-txn <ID>                 # create INR dispute via API
    python spike.py s3-find                             # fallback: find dispute opened in sandbox UI
    python spike.py s3-manual --dispute-id <ID>         # fallback: link a dispute id by hand
    python spike.py s4                                  # list/show + compare with golden case
    python spike.py s5 --action SELLER_EVIDENCE --yes   # sandbox: move status
    python spike.py s6 --yes                            # provide evidence (PDFs from fixture)
    python spike.py escalate --yes                      # inquiry -> claim (UNDER_REVIEW)
    python spike.py s8 --outcome SELLER_FAVOR --yes     # sandbox: adjudicate
S7 (webhooks) lives in webhook.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone

from assertion import build_auth_assertion
from client import PayPalSandboxClient
from config import CONTRACTS_DIR, STATE_FILE, Config
from golden import load_seedable_case
from mapping import (INTERNAL_TO_REASON, compare_with_golden, requested_evidence_types,
                     single_evidence_payload, to_internal)
from pdf import render_evidence

LINKS_FILE = CONTRACTS_DIR.parent / "sandbox_links.csv"


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def require(state: dict, key: str, hint: str) -> str:
    if not state.get(key):
        raise SystemExit(f"No {key} in spike state - run {hint} first.")
    return state[key]


def confirm_write(args: argparse.Namespace, what: str) -> None:
    """Write calls change sandbox state; mirror SAL's rule that a human confirms them."""
    if not args.yes:
        raise SystemExit(f"{what} changes sandbox state. Re-run with --yes to confirm.")


def available_actions(dispute: dict) -> set[str]:
    return {l.get("rel") for l in dispute.get("links", [])}


def ensure_action(client, dispute_id: str, rel: str, record: str) -> dict:
    """Only attempt a write PayPal currently offers (HATEOAS). Prevents duplicate submissions."""
    dispute = report(client.request("GET", f"/v1/customer/disputes/{dispute_id}", record=record), {200})
    actions = available_actions(dispute)
    if rel not in actions:
        print(f"SKIP  '{rel}' is not available in status {dispute.get('status')}. Available: {sorted(actions)}")
        sys.exit(1)
    return dispute


def report(resp, ok_status: set[int]) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:500]}
    passed = resp.status_code in ok_status
    print(f"{'PASS' if passed else 'FAIL'}  HTTP {resp.status_code}  debug_id={resp.headers.get('paypal-debug-id')}")
    if not passed:
        print(json.dumps(body, indent=2)[:3000])
        sys.exit(1)
    return body


def append_link(state: dict) -> None:
    new_file = not LINKS_FILE.exists()
    LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LINKS_FILE.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["case_id", "sandbox_dispute_id", "order_id", "capture_id", "created_via", "linked_at"])
        writer.writerow([
            state.get("case_id"), state.get("dispute_id"), state.get("order_id"),
            state.get("capture_id"), state.get("created_via"), datetime.now(timezone.utc).isoformat(),
        ])


DISPUTE_SCOPES = {
    "https://uri.paypal.com/services/disputes/read-seller": "read disputes (seller)",
    "https://uri.paypal.com/services/disputes/update-seller": "respond to disputes (seller)",
    "https://uri.paypal.com/services/disputes/create": "create disputes via API (buyer, S3)",
}


def s1(client: PayPalSandboxClient, args, state) -> None:
    client.token()
    print("PASS  S1 OAuth token obtained (not printed).")
    for scope, label in DISPUTE_SCOPES.items():
        print(f"  {'yes' if scope in client.scopes else 'NO '}  {label}")
    if not any("disputes" in s for s in client.scopes):
        print("No dispute scopes: enable Features > Add-on services > Customer disputes in the sandbox app.")


def s2_order(client, args, state) -> None:
    case = load_seedable_case(client.config.golden_dir, args.case)
    d = case["dispute"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": case["case_id"],
            "custom_id": case["case_id"],
            "invoice_id": f"{case['case_id']}-{stamp}",
            "description": f"SAL synthetic test: {d['item']}",
            "amount": {
                "currency_code": d["amount"]["currency"], "value": d["amount"]["value"],
                "breakdown": {"item_total": {"currency_code": d["amount"]["currency"], "value": d["amount"]["value"]}},
            },
            # Without an explicit category PayPal classifies the item as DIGITAL_DOWNLOAD.
            "items": [{
                "name": f"SAL synthetic test: {d['item']}", "quantity": "1", "category": args.category,
                "sku": case["case_id"],
                "unit_amount": {"currency_code": d["amount"]["currency"], "value": d["amount"]["value"]},
            }],
        }],
        "payment_source": {"paypal": {"experience_context": {
            "return_url": "https://example.com/sal-spike/return",
            "cancel_url": "https://example.com/sal-spike/cancel",
            "user_action": "PAY_NOW",
        }}},
    }
    order = report(client.request("POST", "/v2/checkout/orders", record="s2_create_order", json_body=body), {200, 201})
    approve = next((l["href"] for l in order.get("links", []) if l["rel"] in ("payer-action", "approve")), None)
    state.update(case_id=case["case_id"], order_id=order["id"])
    save_state(state)
    print(f"Order {order['id']} for {case['case_id']} ({d['amount']['value']} {d['amount']['currency']}).")
    print("Open this link, log in as the SANDBOX BUYER, pay with the buyer's card, then run s2-capture:")
    print(approve)


def s2_capture(client, args, state) -> None:
    order_id = require(state, "order_id", "s2-order")
    body = report(client.request("POST", f"/v2/checkout/orders/{order_id}/capture",
                                 record="s2_capture", json_body={}), {200, 201})
    capture = body["purchase_units"][0]["payments"]["captures"][0]
    state["capture_id"] = capture["id"]
    save_state(state)
    print(f"Capture (seller transaction) id: {capture['id']}  status={capture['status']}")
    print("Note: S3 needs the BUYER-side transaction id (buyer account -> Activity -> transaction details).")


def s3(client, args, state) -> None:
    case = load_seedable_case(client.config.golden_dir, require(state, "case_id", "s2-order"))
    if not client.config.buyer_email:
        raise SystemExit("Set PAYPAL_SANDBOX_BUYER_EMAIL in .env for the auth assertion.")
    d = case["dispute"]
    payload = {
        "disputed_transactions": [{"buyer_transaction_id": args.buyer_txn}],
        "reason": INTERNAL_TO_REASON[d["reason"]],
        "dispute_amount": {"currency_code": d["amount"]["currency"], "value": d["amount"]["value"]},
        "extensions": {
            "merchant_contacted": True,
            "merchant_contacted_outcome": "NO_RESPONSE",
            "merchandize_dispute_properties": {"issue_type": "PRODUCT"},
        },
    }
    resp = client.request(
        "POST", "/v1/customer/disputes", record="s3_create_dispute",
        files=[("input", (None, json.dumps(payload), "application/json"))],
        headers={"PayPal-Auth-Assertion": build_auth_assertion(client.config.client_id, client.config.buyer_email)},
    )
    if resp.status_code in (401, 403):
        print("Create-dispute is a limited-release, buyer-scoped API. If this is a permission error,")
        print("open the INR dispute from the sandbox buyer's Resolution Center and run s3-manual.")
    body = report(resp, {200, 201})
    self_link = next((l["href"] for l in body.get("links", []) if l.get("rel") == "self"), "")
    state.update(dispute_id=self_link.rstrip("/").split("/")[-1], created_via="api", buyer_txn=args.buyer_txn)
    save_state(state)
    append_link(state)
    print(f"Dispute {state['dispute_id']} created. Wait a few minutes before s5/s6.")


def s3_manual(client, args, state) -> None:
    require(state, "case_id", "s2-order")
    state.update(dispute_id=args.dispute_id, created_via="sandbox_ui")
    save_state(state)
    append_link(state)
    print(f"Linked {state['case_id']} <-> {args.dispute_id}.")


def s3_find(client, args, state) -> None:
    """Find a dispute the buyer opened in the sandbox UI, by the seller capture id from S2."""
    capture_id = require(state, "capture_id", "s2-capture")
    body = report(client.request("GET", f"/v1/customer/disputes?disputed_transaction_id={capture_id}",
                                 record="s3_find_dispute"), {200})
    items = body.get("items", [])
    if not items:
        print(f"No dispute yet for transaction {capture_id}. Open it as the buyer in the sandbox")
        print("Resolution Center, wait a few minutes, then run s3-find again.")
        sys.exit(1)
    dispute = items[0]
    state.update(dispute_id=dispute["dispute_id"], created_via="sandbox_ui")
    save_state(state)
    append_link(state)
    print(f"Linked {state['case_id']} <-> {dispute['dispute_id']}  reason={dispute.get('reason')}  "
          f"status={dispute.get('status')}")


def s4(client, args, state) -> None:
    report(client.request("GET", "/v1/customer/disputes", record="s4_list_disputes"), {200})
    dispute_id = require(state, "dispute_id", "s3 or s3-manual")
    body = report(client.request("GET", f"/v1/customer/disputes/{dispute_id}", record="s4_show_dispute"), {200})
    internal = to_internal(body)
    print(json.dumps(internal, indent=2))
    links = sorted(l.get("rel") for l in body.get("links", []))
    print(f"Available actions (HATEOAS): {links}")
    case = load_seedable_case(client.config.golden_dir, state["case_id"])
    issues = compare_with_golden(internal, case)
    print("Golden sync check:", "OK" if not issues else "; ".join(issues))


def s5(client, args, state) -> None:
    confirm_write(args, "require-evidence")
    dispute_id = require(state, "dispute_id", "s3")
    report(client.request("POST", f"/v1/customer/disputes/{dispute_id}/require-evidence",
                          record="s5_require_evidence", json_body={"action": args.action}), {200, 201, 202})
    print("Run s4 to confirm the new status.")


def s6(client, args, state) -> None:
    confirm_write(args, "provide-evidence")
    dispute_id = require(state, "dispute_id", "s3")
    case = load_seedable_case(client.config.golden_dir, state["case_id"])
    dispute = ensure_action(client, dispute_id, "provide_evidence", "s6_show_before")
    requested = requested_evidence_types(dispute)
    evidence_type = args.evidence_type or (requested[0] if requested else "PROOF_OF_FULFILLMENT")
    print(f"PayPal requested: {requested or 'nothing explicit'} -> sending one {evidence_type} evidence")
    payload = single_evidence_payload(case, evidence_type, include_tracking=not args.no_tracking,
                                      carrier_name=args.carrier)
    files = [("input", (None, json.dumps(payload), "application/json"))]
    for ev in case["evidence"]:
        files.append((args.file_field, (f"{ev['evidence_id']}.pdf", render_evidence(ev), "application/pdf")))
    report(client.request("POST", f"/v1/customer/disputes/{dispute_id}/provide-evidence",
                          record="s6_provide_evidence", files=files), {200, 201, 202})
    print("Evidence accepted. Run s4 to see the new status.")


def s_escalate(client, args, state) -> None:
    """Seller escalates the inquiry to a claim so PayPal reviews it (status UNDER_REVIEW)."""
    confirm_write(args, "escalate")
    dispute_id = require(state, "dispute_id", "s3")
    ensure_action(client, dispute_id, "escalate", "escalate_show_before")
    note = "SYNTHETIC TEST: proof of fulfillment already provided; requesting PayPal review."
    report(client.request("POST", f"/v1/customer/disputes/{dispute_id}/escalate",
                          record="escalate", json_body={"note": note}), {200, 201, 202})
    print("Escalated. Wait a few minutes, run s4; s8 needs status UNDER_REVIEW.")


def s8(client, args, state) -> None:
    confirm_write(args, "adjudicate")
    dispute_id = require(state, "dispute_id", "s3")
    ensure_action(client, dispute_id, "adjudicate", "s8_show_before")
    report(client.request("POST", f"/v1/customer/disputes/{dispute_id}/adjudicate",
                          record="s8_adjudicate", json_body={"adjudication_outcome": args.outcome}), {200, 201, 202})
    print("Run s4 to confirm RESOLVED.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("s1")
    p2 = sub.add_parser("s2-order")
    p2.add_argument("--case", default="SAL-INR-001")
    p2.add_argument("--category", default="PHYSICAL_GOODS", choices=["PHYSICAL_GOODS", "DIGITAL_GOODS", "DONATION"])
    sub.add_parser("s2-capture")
    sub.add_parser("s3").add_argument("--buyer-txn", required=True)
    sub.add_parser("s3-manual").add_argument("--dispute-id", required=True)
    sub.add_parser("s3-find")
    sub.add_parser("s4")
    p5 = sub.add_parser("s5")
    p5.add_argument("--action", choices=["SELLER_EVIDENCE", "BUYER_EVIDENCE"], default="SELLER_EVIDENCE")
    p6 = sub.add_parser("s6")
    p6.add_argument("--carrier", default="OTHER", help="PayPal carrier enum, e.g. UPS, DHL, OTHER")
    p6.add_argument("--file-field", default="evidence-file", help="multipart part name for files")
    p6.add_argument("--evidence-type", help="override; default = what PayPal requested")
    p6.add_argument("--no-tracking", action="store_true", help="omit tracking_info (e.g. digital items)")
    pe = sub.add_parser("escalate")
    p8 = sub.add_parser("s8")
    p8.add_argument("--outcome", choices=["SELLER_FAVOR", "BUYER_FAVOR"], default="SELLER_FAVOR")
    for p in (p5, p6, pe, p8):
        p.add_argument("--yes", action="store_true", help="confirm a sandbox write")
    args = parser.parse_args()

    handlers = {"s1": s1, "s2-order": s2_order, "s2-capture": s2_capture, "s3": s3,
                "s3-manual": s3_manual, "s3-find": s3_find, "s4": s4, "s5": s5, "s6": s6, "escalate": s_escalate, "s8": s8}
    client = PayPalSandboxClient(Config.from_env())
    handlers[args.step](client, args, load_state())


if __name__ == "__main__":
    main()
