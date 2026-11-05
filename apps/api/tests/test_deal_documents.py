"""PO and invoice files: SAL reads them, proves each value against the page, and a person confirms before a deal exists."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from openai import LengthFinishReasonError
from openai.types.chat import ChatCompletion
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import deal_documents, worker
from app.db import tenant_session
from app.deal_documents import DocumentKind, DocumentStatus, ReadDocument, ReadItem, ReadValue, ground_document
from app.evidence_pdf import render_text_pdf
from app.main import app, current_merchant
from app.seed import create_merchant
from tests.test_deals import invoice_body, order_body
from tests.fakes import NO_PAYPAL, openai

PAGE = ["PURCHASE ORDER PO-7781", "Buyer: Perth Brake Garage", "Date: 3 November 2026",
        "Ship to: Perth 6000 AU", "BP-2217-A Brake pad set 40 30.00", "Total USD 1,200.00"]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def v(value: str | None, line: int | None) -> ReadValue:
    return ReadValue(value=value, line=line)


def read_page(**overrides) -> ReadDocument:
    fields = {"reference": v("PO-7781", 1), "party": v("Perth Brake Garage", 2), "issued_on": v("2026-11-03", 3),
              "currency": v("USD", 6), "total": v("1200.00", 6), "shipping": v(None, None), "tax": v(None, None),
              "ship_country": v("AU", 4), "ship_city": v("Perth", 4), "ship_postal_code": v("6000", 4),
              "items": [ReadItem(item_code=v("BP-2217-A", 5), description=v("Brake pad set", 5),
                                 quantity=v("40", 5), unit_price=v("30.00", 5))]}
    return ReadDocument(**{**fields, **overrides})


class FakeReader:
    def __init__(self, page: list[str] = PAGE, read: ReadDocument | None = None,
                 fails: Exception | None = None) -> None:
        self.page, self.result, self.fails, self.transcribed = page, read or read_page(), fails, 0

    def transcribe(self, data, mime):
        self.transcribed += 1
        return self.page

    def read(self, kind, lines):
        if self.fails:
            raise self.fails
        return self.result


# --------------------------------------------------------------- proving each value against the page
def test_every_value_found_on_its_line_is_kept():
    proposal = ground_document(read_page(), PAGE)
    assert proposal["total"] == {"value": "1200.00", "line": 6}
    assert proposal["items"][0]["quantity"] == {"value": "40", "line": 5}
    assert proposal["issued_on"]["value"] == "2026-11-03"


@pytest.mark.parametrize(("field", "wrong"), [
    ("total", v("1300.00", 6)),        # a number that is not on the line
    ("total", v("1200.00", 5)),        # the right number, cited on the wrong line
    ("reference", v("PO-7782", 1)),    # one character off
    ("currency", v("EUR", 6)),
    ("issued_on", v("2026-11-30", 3)),
    ("total", v("1200.00", 99)),       # a line that does not exist
    ("total", v("twelve hundred", 6)),
])
def test_a_value_not_on_the_cited_line_is_left_blank(field, wrong):
    assert ground_document(read_page(**{field: wrong}), PAGE)[field] == {"value": None, "line": None}


def test_a_made_up_item_is_blanked_field_by_field():
    item = ReadItem(item_code=v("BP-9999-Z", 5), description=v("Brake pad set", 5), quantity=v("41", 5),
                    unit_price=v("30.00", 5))
    read = ground_document(read_page(items=[item]), PAGE)["items"][0]
    assert read["item_code"]["value"] is None and read["quantity"]["value"] is None
    assert read["unit_price"]["value"] == "30.00"


def test_a_second_read_fills_a_blank_but_never_changes_a_proven_value():
    first = ground_document(read_page(total=v("", 6)), PAGE)
    second = ground_document(read_page(reference=v("PO-7781", 1), total=v("1200.00", 6), party=v("Buyer", 2)), PAGE)
    second["reference"] = {"value": "OTHER", "line": 1}
    merged = deal_documents.fill_blanks(first, second)
    assert merged["total"]["value"] == "1200.00" and merged["reference"]["value"] == "PO-7781"


def test_an_invoice_number_that_is_the_orders_po_number_is_dropped():
    # Seen live: the model took "For purchase order: PO-DEMO-1001" as the invoice number.
    proposal = ground_document(read_page(), PAGE)   # reads "PO-7781" from line 1
    as_invoice = deal_documents.without_order_number(proposal, DocumentKind.INVOICE, "po-7781 ")
    assert as_invoice["reference"] == {"value": None, "line": None}
    assert as_invoice["total"] == proposal["total"]     # nothing else is touched
    # A purchase order's own number, or an invoice for another order, is kept.
    assert deal_documents.without_order_number(proposal, DocumentKind.PURCHASE_ORDER, "PO-7781") == proposal
    assert deal_documents.without_order_number(proposal, DocumentKind.INVOICE, "PO-9999") == proposal
    assert deal_documents.without_order_number(proposal, DocumentKind.INVOICE, None) == proposal


def test_only_required_fields_count_as_blanks():
    proposal = ground_document(read_page(), PAGE)
    assert not deal_documents.has_blanks(proposal)     # no shipping or tax on this page, and that is fine
    assert deal_documents.has_blanks(ground_document(read_page(total=v("", 6)), PAGE))


def test_kinds_and_statuses_match_the_database_checks():
    sql = next(Path(__file__).resolve().parents[1].glob("migrations/sql/*_deal_documents.sql")).read_text(encoding="utf-8")
    for enum in (DocumentKind, DocumentStatus):
        declared = re.search(rf"{enum.__name__}: (.+)", sql)
        assert declared, f"the migration documents {enum.__name__}"
        allowed = declared.group(1)
        assert set(re.findall(r"[A-Z_]{3,}", allowed)) == {e.value for e in enum}


# --------------------------------------------------------------- end to end
@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Doc-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant, app_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("SAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr("app.deals.app_engine", lambda: app_engine)
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()


def ctx(worker_engine, reader) -> worker.Context:
    return worker.Context(worker_engine, NO_PAYPAL, reader_factory=lambda: reader)


def upload(client, content: bytes, kind: str = "PURCHASE_ORDER", deal_ref: str = ""):
    return client.post("/api/deal-documents", data={"kind": kind, "deal_ref": deal_ref},
                       files={"file": ("po.bin", content, "application/octet-stream")})


def read_doc(client, reader, worker_engine) -> dict:
    worker.drain(ctx(worker_engine, reader))
    return client.get("/api/deal-documents").json()["items"][0]


@pytest.mark.db
def test_a_text_pdf_is_read_without_the_vision_step(client, worker_engine):
    reader = FakeReader()
    assert upload(client, render_text_pdf(PAGE)).status_code == 201
    doc = read_doc(client, reader, worker_engine)
    assert doc["status"] == "NEEDS_CONFIRMATION" and reader.transcribed == 0
    assert doc["proposal"]["total"]["value"] == "1200.00"


@pytest.mark.db
def test_a_photo_is_transcribed_then_grounded(client, worker_engine):
    reader = FakeReader()
    upload(client, PNG)
    doc = read_doc(client, reader, worker_engine)
    assert reader.transcribed >= 1 and doc["status"] == "NEEDS_CONFIRMATION"
    assert [line["text"] for line in doc["lines"]] == PAGE


@pytest.mark.db
def test_a_transcription_that_stopped_early_is_taken_again(client, worker_engine):
    long_page = [f"line {i}" for i in range(12)]

    class Short(FakeReader):
        def transcribe(self, data, mime):
            self.transcribed += 1
            return long_page[:1] if self.transcribed == 1 else long_page
    reader = Short(page=long_page)
    upload(client, PNG)
    assert len(read_doc(client, reader,
                        worker_engine)["lines"]) == 12 and reader.transcribed == 3   # 2 + the second copy


@pytest.mark.db
def test_a_page_with_no_text_is_unreadable_not_guessed(client, worker_engine):
    upload(client, PNG)
    assert read_doc(client, FakeReader(page=[]), worker_engine)["status"] == "UNREADABLE"


@pytest.mark.db
def test_a_blank_is_read_again_and_filled(client, worker_engine):
    class Flaky(FakeReader):
        reads = 0

        def read(self, kind, lines):
            self.reads += 1
            return read_page(total=v("", 6)) if self.reads == 1 else read_page()
    reader = Flaky()
    upload(client, PNG)
    assert read_doc(client, reader, worker_engine)["proposal"]["total"]["value"] == "1200.00" and reader.reads == 2


@pytest.mark.db
def test_no_deal_exists_until_a_person_confirms(client, worker_engine):
    upload(client, PNG)
    doc = read_doc(client, FakeReader(), worker_engine)
    assert client.get("/api/deals").json()["items"] == []
    r = client.post(f"/api/deal-documents/{doc['id']}/confirm-order", json=order_body())
    assert r.status_code == 201 and r.json()["status"] == "WAITING_INVOICE"
    assert client.post(f"/api/deal-documents/{doc['id']}/confirm-order", json=order_body()).status_code == 409


@pytest.mark.db
def test_a_confirmed_invoice_is_checked_by_the_worker(client, worker_engine):
    upload(client, PNG)
    po = read_doc(client, FakeReader(), worker_engine)
    client.post(f"/api/deal-documents/{po['id']}/confirm-order", json=order_body())
    assert upload(client, PNG + b"2", "INVOICE", "PO-7781").status_code == 201
    invoice = read_doc(client, FakeReader(), worker_engine)
    assert invoice["kind"] == "INVOICE"
    wrong = invoice_body(total="1250.00")
    assert client.post(f"/api/deal-documents/{invoice['id']}/confirm-invoice", json=wrong).status_code == 200
    worker.drain(ctx(worker_engine, FakeReader()))
    assert client.get("/api/deals/PO-7781").json()["status"] == "HOLD"


@pytest.mark.db
def test_an_invoice_needs_a_deal_that_exists(client):
    assert upload(client, PNG, "INVOICE", "PO-NOPE").status_code == 404


@pytest.mark.db
def test_an_order_cannot_be_confirmed_from_an_invoice_file(client, worker_engine):
    upload(client, PNG)
    po = read_doc(client, FakeReader(), worker_engine)
    r = client.post(f"/api/deal-documents/{po['id']}/confirm-invoice", json=invoice_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WRONG_DOCUMENT_KIND"


@pytest.mark.db
def test_a_discarded_document_cannot_be_confirmed(client, worker_engine):
    upload(client, PNG)
    doc = read_doc(client, FakeReader(), worker_engine)
    assert client.post(f"/api/deal-documents/{doc['id']}/discard").status_code == 200
    assert client.post(f"/api/deal-documents/{doc['id']}/confirm-order", json=order_body()).status_code == 409


@pytest.mark.db
def test_confirming_is_audited_as_a_person(client, merchant, worker_engine, app_engine):
    upload(client, PNG)
    doc = read_doc(client, FakeReader(), worker_engine)
    client.post(f"/api/deal-documents/{doc['id']}/confirm-order", json=order_body())
    with tenant_session(merchant, app_engine) as s:
        actor = s.execute(text("SELECT actor FROM audit_logs WHERE action = 'deal.ordered'")).scalar_one()
    assert actor.startswith("operator")


@pytest.mark.db
def test_a_file_that_is_not_a_document_is_refused(client):
    assert upload(client, b"MZ executable").status_code == 415


@pytest.mark.db
def test_a_reader_that_keeps_failing_ends_as_unreadable(client, merchant, worker_engine):
    upload(client, PNG)
    doc = client.get("/api/deal-documents").json()["items"][0]
    deal_documents.give_up(merchant, UUID(doc["id"]), worker_engine)
    assert client.get("/api/deal-documents").json()["items"][0]["status"] == "UNREADABLE"


@pytest.mark.db
def test_one_merchant_never_sees_anothers_document(client):
    upload(client, PNG)
    other = create_merchant(f"Doc-{uuid4().hex[:6]}")
    app.dependency_overrides[current_merchant] = lambda: other
    assert client.get("/api/deal-documents").json()["items"] == []


def test_a_subtotal_is_never_taken_for_the_total():
    page = ["Subtotal USD 1,000.00", "Total USD 1,200.00"]
    assert ground_document(read_page(total=v("1000.00", 1), items=[]), page)["total"]["value"] is None
    assert ground_document(read_page(total=v("1200.00", 2), items=[]), page)["total"]["value"] == "1200.00"


def test_a_value_the_second_copy_does_not_show_is_left_blank():
    second = [line.replace("BP-2217-A", "BP-2211-A").replace("1,200.00", "1,300.00") for line in PAGE]
    proposal = ground_document(read_page(), PAGE, second)
    assert proposal["items"][0]["item_code"]["value"] is None and proposal["total"]["value"] is None
    assert proposal["items"][0]["quantity"]["value"] == "40"
    assert proposal["reference"]["value"] == "PO-7781"


def test_two_agreeing_copies_keep_every_value():
    assert ground_document(read_page(), PAGE, list(PAGE)) == ground_document(read_page(), PAGE)


@pytest.mark.parametrize(("written", "kept"), [
    ("No. PO-7781", "PO-7781"), ("No:#7781", "#7781"), ("Nr. PO-7781", "PO-7781"),
    # labels seen on real public documents (San Diego POs, Bradenton Beach invoices, 2026-11-03)
    ("Invoice No. INV-2001", "INV-2001"), ("PO# 4500105350", "4500105350"), ("Invoice number: INV-2001", "INV-2001"),
    ("PO-7781", "PO-7781"), ("INV-2001", "INV-2001"),
])
def test_a_label_in_front_of_the_number_is_dropped(written, kept):
    page = [f"Order {written}"]
    assert ground_document(read_page(reference=v(written, 1), items=[]), page)["reference"]["value"] == kept


def test_a_document_too_long_for_one_read_comes_back_blank():
    class Overflowing:
        def parse(self, **_):
            raise LengthFinishReasonError(completion=cast(ChatCompletion, SimpleNamespace(usage=None)))
    client = SimpleNamespace(chat=SimpleNamespace(completions=Overflowing()))
    read = deal_documents.LLMDocumentReader(client=openai(client), model="test-model").read(DocumentKind.INVOICE, PAGE)
    proposal = ground_document(read, PAGE)
    assert proposal["total"]["value"] is None and proposal["items"] == [] and deal_documents.has_blanks(proposal)


@pytest.mark.parametrize("short", ["54", "02", "A1"])
def test_a_number_too_short_to_be_a_reference_is_left_blank(short):
    assert ground_document(read_page(reference=v(short, 1), items=[]), [f"Page {short}"])["reference"]["value"] is None


@pytest.mark.db
def test_a_photo_is_copied_twice_and_a_disagreement_is_blank(client, worker_engine):
    other = [line.replace("BP-2217-A", "BP-2211-A") for line in PAGE]

    class Reader(FakeReader):
        def transcribe(self, data, mime):
            self.transcribed += 1
            return PAGE if self.transcribed <= 3 else other
    upload(client, PNG)
    doc = read_doc(client, Reader(), worker_engine)
    assert doc["proposal"]["items"][0]["item_code"]["value"] is None
    assert doc["proposal"]["reference"]["value"] == "PO-7781"


@pytest.mark.db
def test_a_typed_pdf_needs_no_second_copy(client, worker_engine):
    reader = FakeReader()
    upload(client, render_text_pdf(PAGE))
    assert read_doc(client, reader, worker_engine)["proposal"]["reference"]["value"] == "PO-7781"
    assert reader.transcribed == 0
