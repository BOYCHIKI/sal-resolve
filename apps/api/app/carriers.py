"""Which courier shipped the parcel, as a PayPal tracking carrier code.

PayPal can only follow a tracking number when it knows the carrier. Sending every parcel as "OTHER" makes
tracking unreadable to PayPal, so a JNE or USPS parcel loses the faster release and the delivery check it
would otherwise get. The courier is read from the merchant's own tracking document (grounded: the name
must appear on a line), then mapped to PayPal's code.

Codes are from PayPal's carrier reference (developer.paypal.com/track-orders/carriers, checked 2026-10-24).
They follow no pattern (J&T Malaysia is bare JTEXPRESS, Thai Ninja Van is NINJAVAN_THAI), so this is a
lookup table, never a guess. More specific names come first (Speedpost before SingPost).

Couriers PayPal has no code for, or whose country we cannot tell (J&T Indonesia, SiCepat, LBC, a bare
"J&T" or "Ninja Van"), go as OTHER with their real name, which still beats an anonymous "Carrier on file".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

OTHER = "OTHER"
UNKNOWN_NAME = "Carrier on file"


@dataclass(frozen=True)
class Carrier:
    code: str          # PayPal carrier enum, or OTHER
    name: str | None   # carrier_name_other when code is OTHER
    line: str | None   # the document line the name was read from


_I = re.IGNORECASE
# (PayPal code, display name, pattern). Order matters: specific before general.
KNOWN: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # Indonesia
    ("IDN_JNE", "JNE", re.compile(r"\bJNE\b", _I)),
    ("IDN_POS", "Pos Indonesia", re.compile(r"\bPos\s+Indonesia\b|\bEMS\s+Pos\b", _I)),
    ("TIKI_ID", "TIKI", re.compile(r"\bTIKI\b")),
    ("ANTERAJA", "AnterAja", re.compile(r"\bAnter\s?Aja\b", _I)),
    ("LION_PARCEL", "Lion Parcel", re.compile(r"\bLion\s+Parcel\b", _I)),
    ("IDEXPRESS_ID", "ID Express", re.compile(r"\bID\s?Express\b", _I)),
    ("WAHANA_ID", "Wahana", re.compile(r"\bWahana\b", _I)),
    ("SAP_EXPRESS", "SAP Express", re.compile(r"\bSAP\s+Express\b", _I)),
    # Philippines
    ("JTEXPRESS_PH", "J&T Express Philippines", re.compile(r"\bJ\s?&\s?T\b.*\bPhilippines\b", _I)),
    ("PHILIPPINE_POST", "PHLPost", re.compile(r"\bPHL\s?Post\b|\bPhilippine\s+Post(al)?\b", _I)),
    ("TWO_GO", "2GO", re.compile(r"\b2GO\b", _I)),
    ("AIR_21", "Air21", re.compile(r"\bAir\s?21\b", _I)),
    # Vietnam
    ("JTEXPRESS_VN", "J&T Express Vietnam", re.compile(r"\bJ\s?&\s?T\b.*\bViet\s?nam\b", _I)),
    ("VNM_VIETTELPOST", "Viettel Post", re.compile(r"\bViettel\s?Post\b", _I)),
    ("VNM_VIETNAM_POST", "Vietnam Post", re.compile(r"\bViet\s?nam\s+Post\b|\bVNPost\b", _I)),
    ("GIAO_HANG", "Giao Hang Nhanh", re.compile(r"\bGiao\s+H[aà]ng\s+Nhanh\b|\bGHN\b", _I)),
    # Thailand
    ("THA_THAILAND_POST", "Thailand Post", re.compile(r"\bThailand\s+Post\b", _I)),
    ("THA_KERRY", "Kerry Express", re.compile(r"\bKerry\s+Express\b", _I)),
    # Malaysia
    ("JTEXPRESS", "J&T Express Malaysia", re.compile(r"\bJ\s?&\s?T\b.*\bMalaysia\b", _I)),
    ("MYS_EMS", "Pos Laju", re.compile(r"\bPos\s?Laju\b", _I)),
    ("MYS_MYS_POST", "Pos Malaysia", re.compile(r"\bPos\s+Malaysia\b", _I)),
    ("MYS_GDEX", "GDEX", re.compile(r"\bGDEX\b", _I)),
    ("CITYLINK_MY", "City-Link Express", re.compile(r"\bCity-?\s?Link\b", _I)),
    # Singapore
    ("JTEXPRESS_SG", "J&T Express Singapore", re.compile(r"\bJ\s?&\s?T\b.*\bSingapore\b", _I)),
    ("SG_SPEEDPOST", "Speedpost", re.compile(r"\bSpeed\s?post\b", _I)),
    ("SG_SG_POST", "SingPost", re.compile(r"\bSing\s?Post\b|\bSingapore\s+Post\b", _I)),
    ("JANIO", "Janio", re.compile(r"\bJanio\b", _I)),
    # International
    ("USPS", "USPS", re.compile(r"\bUSPS\b|\bUnited\s+States\s+Postal\s+Service\b", _I)),
    ("FEDEX", "FedEx", re.compile(r"\bFed\s?Ex\b", _I)),
    ("UPS", "UPS", re.compile(r"\bUPS\b")),  # upper-case only: "ups" is an ordinary word
    ("DHL", "DHL", re.compile(r"\bDHL\b", _I)),
    ("TNT", "TNT", re.compile(r"\bTNT\b")),
    ("ARAMEX", "Aramex", re.compile(r"\bAramex\b", _I)),
    ("ROYAL_MAIL", "Royal Mail", re.compile(r"\bRoyal\s+Mail\b", _I)),
)

# Real couriers PayPal has no code for, or whose country a bare name doesn't tell us.
NAMED_OTHER: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("J&T Express", re.compile(r"\bJ\s?&\s?T\b", _I)),
    ("SiCepat", re.compile(r"\bSi\s?Cepat\b", _I)),
    ("LBC Express", re.compile(r"\bLBC\b")),
    ("Ninja Van", re.compile(r"\bNinja\s?(Van|Xpress)\b", _I)),
    ("Flash Express", re.compile(r"\bFlash\s+Express\b", _I)),
    ("GHTK", re.compile(r"\bGHTK\b|\bGiao\s+H[aà]ng\s+Ti[eế]t\s+Ki[eệ]m\b", _I)),
    ("Shopee Express", re.compile(r"\bShopee\s+X?press\b|\bSPX\b", _I)),
    ("Lazada Express", re.compile(r"\bLazada\s+(Express|Logistics)\b|\bLEX\b")),
    ("Paxel", re.compile(r"\bPaxel\b", _I)),
    ("GoSend", re.compile(r"\bGo\s?Send\b", _I)),
    ("GrabExpress", re.compile(r"\bGrab\s?Express\b", _I)),
    ("Lalamove", re.compile(r"\bLalamove\b", _I)),
)


# A line that says which courier it is ("Courier: JNE", "Kurir: J&T") beats a name in passing (an address
# near "Kantor Pos Indonesia", a footer mentioning DHL).
LABELLED = re.compile(r"^\s*(carrier|courier|kurir|ekspedisi|jasa\s+kirim|shipped\s+(with|via)|shipping\s+method)\b",
                      _I)


def _match(lines: list[str]) -> Carrier | None:
    # Known codes win over named OTHERs: "J&T Express ... handed to USPS" goes as USPS, which delivers it.
    for code, _name, pattern in KNOWN:
        for line in lines:
            if pattern.search(line):
                return Carrier(code, None, line)
    for name, pattern in NAMED_OTHER:
        for line in lines:
            if pattern.search(line):
                return Carrier(OTHER, name, line)
    return None


def carrier_for(lines: list[str]) -> Carrier:
    """The courier named on the merchant's tracking document, labelled lines first."""
    labelled = [line for line in lines if LABELLED.search(line)]
    return _match(labelled) or _match(lines) or Carrier(OTHER, UNKNOWN_NAME, None)


def tracking_info(tracking_number: str, carrier: Carrier) -> dict[str, str]:
    """One entry of PayPal provide-evidence `evidence_info.tracking_info`."""
    info = {"carrier_name": carrier.code, "tracking_number": tracking_number}
    if carrier.code == OTHER:
        info["carrier_name_other"] = carrier.name or UNKNOWN_NAME
    return info
