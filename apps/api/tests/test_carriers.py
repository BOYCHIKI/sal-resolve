"""The courier on the merchant's tracking document becomes PayPal's carrier code, so PayPal can follow the
parcel. Codes checked against developer.paypal.com/track-orders/carriers (2026-10-24)."""
from __future__ import annotations

import pytest

from app import carriers
from app.submission import _payload


@pytest.mark.parametrize("line, code", [
    ("Kurir: JNE REG", "IDN_JNE"),
    ("Courier: Pos Indonesia (EMS)", "IDN_POS"),
    ("Shipped via USPS First-Class Package International", "USPS"),
    ("Carrier: FedEx International Priority", "FEDEX"),
    ("Carrier: DHL Express", "DHL"),
    ("Courier: J&T Express Philippines", "JTEXPRESS_PH"),
    ("Courier: J&T Express Malaysia", "JTEXPRESS"),        # no country suffix in PayPal's list
    ("Courier: Ninja Van", carriers.OTHER),                 # country unknown: no guessed code
    ("Carrier: Speedpost Priority", "SG_SPEEDPOST"),        # not SG_SG_POST
    ("Courier: Pos Laju", "MYS_EMS"),                        # not MYS_MYS_POST
    ("Carrier: Kerry Express", "THA_KERRY"),
    ("Courier: Viettel Post", "VNM_VIETTELPOST"),
])
def test_known_couriers_get_paypal_codes(line, code):
    assert carriers.carrier_for([line]).code == code


@pytest.mark.parametrize("line, name", [
    ("Kurir: J&T Express", "J&T Express"),   # J&T Indonesia has no PayPal code
    ("Kurir: SiCepat HALU", "SiCepat"),
    ("Courier: LBC Express", "LBC Express"),
])
def test_couriers_paypal_lacks_go_as_other_with_their_real_name(line, name):
    c = carriers.carrier_for([line])
    assert (c.code, c.name) == (carriers.OTHER, name)
    assert carriers.tracking_info("JX123", c) == {"carrier_name": "OTHER", "carrier_name_other": name,
                                                  "tracking_number": "JX123"}


def test_labelled_line_beats_a_name_in_passing():
    lines = ["Alamat: Jl. Merdeka 1, dekat Kantor Pos Indonesia", "Kurir: JNE YES", "Status: DELIVERED"]
    c = carriers.carrier_for(lines)
    assert c.code == "IDN_JNE" and c.line == "Kurir: JNE YES"


def test_handover_to_a_known_network_is_sent_as_that_network():
    lines = ["Courier: J&T Express", "Handed over to USPS for final delivery"]
    assert carriers.carrier_for(lines).code == carriers.OTHER  # the labelled line wins first...
    assert carriers.carrier_for(lines[1:]).code == "USPS"        # ...and a bare handover line still maps


def test_lower_case_ups_is_an_ordinary_word():
    assert carriers.carrier_for(["Parcel picked ups and downs"]).code == carriers.OTHER
    assert carriers.carrier_for(["Carrier: UPS Worldwide Saver"]).code == "UPS"


def test_no_courier_named_keeps_the_old_fallback():
    c = carriers.carrier_for(["SYNTHETIC TRACKING | TRK-SYN-70000", "Carrier status: DELIVERED"])
    assert (c.code, c.name, c.line) == (carriers.OTHER, carriers.UNKNOWN_NAME, None)


def test_payload_sends_the_courier_code_with_the_tracking_number():
    facts = [{"field": "tracking_id", "value": "JNE0012345", "status": "supported"}]
    claims = [{"text": "We shipped the order with tracking number JNE0012345.", "fact_fields": ["tracking_id"]}]
    payload = _payload(claims, facts, [], ["Kurir: JNE REG", "Resi: JNE0012345"])
    assert payload["evidences"][0]["evidence_info"]["tracking_info"] == [
        {"carrier_name": "IDN_JNE", "tracking_number": "JNE0012345"}]
