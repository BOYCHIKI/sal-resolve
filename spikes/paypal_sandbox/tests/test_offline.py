"""Offline tests — no network, no credentials. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assertion import build_auth_assertion  # noqa: E402
from client import redact  # noqa: E402
from config import DEFAULT_GOLDEN_DIR, SANDBOX_BASE_URL, Config  # noqa: E402
from golden import load_case, load_seedable_case  # noqa: E402
from mapping import (compare_with_golden, evidence_payload, provider_status, requested_evidence_types,
                     single_evidence_payload, to_internal)  # noqa: E402
from pdf import render_evidence  # noqa: E402

SAMPLE_DISPUTE = {
    "dispute_id": "PP-D-TEST",
    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "dispute_life_cycle_stage": "INQUIRY",
    "dispute_amount": {"currency_code": "USD", "value": "45.00"},
    "disputed_transactions": [{"seller_transaction_id": "SELLERTXN", "buyer_transaction_id": "BUYERTXN"}],
}


class MappingTests(unittest.TestCase):
    def test_reason_and_amount_normalized(self):
        internal = to_internal(SAMPLE_DISPUTE)
        self.assertEqual(internal["reason"], "ITEM_NOT_RECEIVED")
        self.assertEqual(internal["amount"], {"value": "45.00", "currency": "USD"})
        self.assertEqual(internal["origin"], "PAYPAL_SANDBOX")

    def test_unknown_status_is_other(self):
        self.assertEqual(provider_status("SOMETHING_NEW"), "OTHER")

    def test_golden_sync_check(self):
        case = load_case(DEFAULT_GOLDEN_DIR, "SAL-INR-001")
        self.assertEqual(compare_with_golden(to_internal(SAMPLE_DISPUTE), case), [])
        wrong = dict(SAMPLE_DISPUTE, dispute_amount={"currency_code": "USD", "value": "44.99"})
        self.assertTrue(compare_with_golden(to_internal(wrong), case))

    def test_evidence_payload_has_tracking(self):
        payload = evidence_payload(load_case(DEFAULT_GOLDEN_DIR, "SAL-INR-001"))
        tracked = [e for e in payload["evidences"] if "evidence_info" in e]
        info = tracked[0]["evidence_info"]["tracking_info"][0]
        self.assertEqual(info["tracking_number"], "TRK-SYN-70000")
        self.assertEqual(info["carrier_name"], "OTHER")
        self.assertIn("carrier_name_other", info)


class ProviderRequestTests(unittest.TestCase):
    def test_requested_evidence_read_from_dispute(self):
        dispute = dict(SAMPLE_DISPUTE, evidences=[
            {"evidence_type": "CREATE", "source": "SUBMITTED_BY_BUYER"},
            {"evidence_type": "PROOF_OF_FULFILLMENT", "source": "REQUESTED_FROM_SELLER"},
        ])
        self.assertEqual(requested_evidence_types(dispute), ["PROOF_OF_FULFILLMENT"])

    def test_single_evidence_payload(self):
        case = load_case(DEFAULT_GOLDEN_DIR, "SAL-INR-001")
        payload = single_evidence_payload(case, "PROOF_OF_FULFILLMENT")
        self.assertEqual(len(payload["evidences"]), 1)
        self.assertIn("tracking_info", payload["evidences"][0]["evidence_info"])
        bare = single_evidence_payload(case, "PROOF_OF_FULFILLMENT", include_tracking=False)
        self.assertNotIn("evidence_info", bare["evidences"][0])


class GuardTests(unittest.TestCase):
    def test_holdout_never_seedable(self):
        for split in ("holdout", "calibration"):
            path = DEFAULT_GOLDEN_DIR / split / "cases.jsonl"
            case_id = json.loads(path.read_text(encoding="utf-8").splitlines()[0])["case_id"]
            with self.assertRaises(SystemExit):
                load_seedable_case(DEFAULT_GOLDEN_DIR, case_id)

    def test_development_seedable(self):
        self.assertEqual(load_seedable_case(DEFAULT_GOLDEN_DIR, "SAL-INR-001")["split"], "development")

    def test_live_base_url_refused(self):
        import os
        os.environ.update(PAYPAL_BASE_URL="https://api-m.paypal.com",
                          PAYPAL_CLIENT_ID="x", PAYPAL_CLIENT_SECRET="y")
        try:
            with self.assertRaises(SystemExit):
                Config.from_env()
        finally:
            os.environ.pop("PAYPAL_BASE_URL")
        self.assertEqual(Config.from_env().base_url, SANDBOX_BASE_URL)

    def test_redaction(self):
        out = redact({"access_token": "abc", "payer": {"email_address": "buyer@example.com"}})
        self.assertEqual(out["access_token"], "[REDACTED]")
        self.assertEqual(out["payer"]["email_address"], "[PII]")
        self.assertEqual(redact({"note": "mail me at a@b.com"})["note"], "mail me at [EMAIL]")
        self.assertEqual(redact({"payer_id": "TEBRG", "name": {"given_name": "John"}})["name"]["given_name"], "[PII]")


class DatasetIntegrityTests(unittest.TestCase):
    def test_golden_v1_unchanged(self):
        """The golden dataset is frozen; any edit must become a new version folder."""
        import hashlib
        for line in (DEFAULT_GOLDEN_DIR / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
            digest, rel = line.split(maxsplit=1)
            actual = hashlib.sha256((DEFAULT_GOLDEN_DIR / rel.lstrip("*")).read_bytes()).hexdigest()
            self.assertEqual(actual, digest, f"{rel} changed - create data/golden/v1.1.0 instead")


class ArtifactTests(unittest.TestCase):
    def test_pdf_is_valid_and_small(self):
        case = load_case(DEFAULT_GOLDEN_DIR, "SAL-INR-001")
        data = render_evidence(case["evidence"][0])
        self.assertTrue(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"ORD-SYN-4000", data)
        self.assertLess(len(data), 10 * 1024 * 1024)

    def test_assertion_shape(self):
        token = build_auth_assertion("CLIENT", "buyer@example.com")
        header, payload, sig = token.split(".")
        self.assertEqual(sig, "")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(header))), {"alg": "none"})
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(payload)))["email"], "buyer@example.com")


if __name__ == "__main__":
    unittest.main()
