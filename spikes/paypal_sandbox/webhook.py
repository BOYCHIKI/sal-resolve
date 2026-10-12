"""S7: local webhook receiver. Verifies each event with PayPal, dedupes by event id, records it.

    python webhook.py --port 8787
Expose it with a tunnel (e.g. `cloudflared tunnel --url http://localhost:8787`), register
<tunnel-url>/webhooks/paypal in the sandbox app for CUSTOMER.DISPUTE.CREATED/UPDATED/RESOLVED,
and put the resulting webhook id in PAYPAL_WEBHOOK_ID.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from client import PayPalSandboxClient
from config import Config

MAX_BODY = 1_000_000
seen_event_ids: set[str] = set()


def make_handler(client: PayPalSandboxClient):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/webhooks/paypal":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                self.send_response(413)
                self.end_headers()
                return
            event = json.loads(self.rfile.read(length) or b"{}")
            verification = {
                "auth_algo": self.headers.get("PAYPAL-AUTH-ALGO"),
                "cert_url": self.headers.get("PAYPAL-CERT-URL"),
                "transmission_id": self.headers.get("PAYPAL-TRANSMISSION-ID"),
                "transmission_sig": self.headers.get("PAYPAL-TRANSMISSION-SIG"),
                "transmission_time": self.headers.get("PAYPAL-TRANSMISSION-TIME"),
                "webhook_id": client.config.webhook_id,
                "webhook_event": event,
            }
            resp = client.request("POST", "/v1/notifications/verify-webhook-signature",
                                  record="s7_verify_webhook", json_body=verification)
            status = resp.json().get("verification_status") if resp.status_code == 200 else None
            event_id = event.get("id", "")
            if status != "SUCCESS":
                print(f"REJECT  {event.get('event_type')} {event_id}: verification={status}")
                self.send_response(400)
            elif event_id in seen_event_ids:
                print(f"DUPLICATE  {event.get('event_type')} {event_id} (ignored)")
                self.send_response(200)
            else:
                seen_event_ids.add(event_id)
                print(f"ACCEPT  {event.get('event_type')} {event_id}")
                self.send_response(200)
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    config = Config.from_env()
    if not config.webhook_id:
        raise SystemExit("Set PAYPAL_WEBHOOK_ID in .env (from the sandbox app's webhook settings).")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(PayPalSandboxClient(config)))
    print(f"Listening on http://127.0.0.1:{args.port}/webhooks/paypal")
    server.serve_forever()


if __name__ == "__main__":
    main()
