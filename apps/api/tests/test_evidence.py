"""Evidence upload: type sniffing, limits, text extraction, tenant isolation, re-analysis, original-file submit."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import evidence
from app import worker
from app.db import tenant_session
from app.evidence_pdf import render_text_pdf
from app.main import app, current_merchant
from app.seed import create_merchant
from app.seed_demo import seed_golden

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# --------------------------------------------------------------- offline
def test_sniff_by_content_not_name():
    assert evidence.sniff_mime(b"%PDF-1.4 ...") == "application/pdf"
    assert evidence.sniff_mime(PNG) == "image/png"
    assert evidence.sniff_mime(b"MZ\x90\x00 windows exe") is None
    assert evidence.sniff_mime(b"<html><script>") is None


def test_pdf_text_becomes_numbered_lines():
    pdf = render_text_pdf(["Delivery date: 2026-08-20", "", "Delivery status: DELIVERED"])
    lines = evidence.extract_lines(pdf, "application/pdf")
    assert [l["text"] for l in lines] == ["Delivery date: 2026-08-20", "Delivery status: DELIVERED"]
    assert [l["line"] for l in lines] == [1, 2]


def test_broken_pdf_is_a_clear_error():
    with pytest.raises(evidence.EvidenceError) as e:
        evidence.extract_lines(b"%PDF-1.4 not really a pdf", "application/pdf")
    assert e.value.code == "PDF_UNREADABLE"


def test_storage_paths_cannot_escape(tmp_path):
    (tmp_path / "outside.txt").write_text("secret")
    store = tmp_path / "store"
    store.mkdir()
    assert evidence.read_file(store, "../outside.txt") is None


# --------------------------------------------------------------- API + database


@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Ev-{uuid4().hex[:6]}")


@pytest.fixture
def client(merchant, tmp_path, monkeypatch):
    from app import config
    monkeypatch.setenv("SAL_STORAGE_DIR", str(tmp_path / "storage"))
    config.get_settings.cache_clear()
    app.dependency_overrides[current_merchant] = lambda: merchant
    yield TestClient(app)
    app.dependency_overrides.clear()
    config.get_settings.cache_clear()


def upload(client, dispute_id, data, doc_type="delivery_proof", name="receipt.pdf"):
    return client.post(f"/api/disputes/{dispute_id}/evidence", data={"doc_type": doc_type},
                       files={"file": (name, data, "application/octet-stream")})


@pytest.mark.db
def test_upload_extracts_text_stores_file_and_queues_analysis(client, merchant, app_engine, tmp_path):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")  # missing delivery proof + tracking
    pdf = render_text_pdf(["SYNTHETIC DELIVERY CONFIRMATION | TRK-SYN-99999", "Delivery status: DELIVERED",
                           "Delivery date: 2026-07-30"])
    r = upload(client, dispute_id, pdf)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mime"] == "application/pdf" and body["text_lines"] == 3 and body["analysis_queued"]
    with tenant_session(merchant, app_engine) as s:
        row = s.execute(text("SELECT object_key, doc_type, content_lines FROM evidence WHERE id = :i"),
                        {"i": body["evidence_id"]}).one()
    assert row.doc_type == "delivery_proof" and row.content_lines[2]["text"] == "Delivery date: 2026-07-30"
    assert (tmp_path / "storage" / row.object_key).read_bytes() == pdf


@pytest.mark.db
def test_reanalysis_sees_the_new_document(client, merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")
    pdf = render_text_pdf(["SYNTHETIC DELIVERY CONFIRMATION | TRK-SYN-99999", "Delivery status: DELIVERED",
                           "Delivery date: 2026-07-30"])
    assert upload(client, dispute_id, pdf).status_code == 201
    ctx = worker.Context(worker_engine, lambda: None)
    while worker.run_one_job(ctx):
        pass
    a = client.get(f"/api/disputes/{dispute_id}/analysis").json()
    missing = {f["field"] for f in a["findings"] if f["kind"] == "missing"}
    assert missing == {"carrier_tracking"}  # delivery proof is no longer missing
    assert any(f["field"] == "delivery_date" and f["value"] == "2026-07-30" for f in a["facts"])


@pytest.mark.db
def test_rejections(client, merchant, app_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    pdf = render_text_pdf(["hello"])
    assert upload(client, dispute_id, b"MZ\x90\x00exe").json()["detail"]["code"] == "UNSUPPORTED_TYPE"
    assert upload(client, dispute_id, b"").json()["detail"]["code"] == "EMPTY_FILE"
    assert upload(client, dispute_id, pdf, doc_type="selfie").json()["detail"]["code"] == "UNKNOWN_DOC_TYPE"
    big = b"%PDF-" + b"0" * evidence.MAX_BYTES
    assert upload(client, dispute_id, big).status_code == 413
    assert upload(client, dispute_id, pdf).status_code == 201
    assert upload(client, dispute_id, pdf).json()["detail"]["code"] == "DUPLICATE_FILE"


@pytest.mark.db
def test_images_are_accepted_without_text(client, merchant, app_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    r = upload(client, dispute_id, PNG, doc_type="carrier_tracking", name="label.png")
    assert r.status_code == 201 and r.json()["mime"] == "image/png" and r.json()["text_lines"] == 0


@pytest.mark.db
def test_other_tenant_cannot_upload(client, merchant, app_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    app.dependency_overrides[current_merchant] = lambda: create_merchant("Intruder")
    r = upload(client, dispute_id, render_text_pdf(["x"]))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "DISPUTE_NOT_FOUND"


@pytest.mark.db
def test_submit_sends_the_original_upload(client, merchant, app_engine, worker_engine):
    from app.main import paypal_sink
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    with tenant_session(merchant, app_engine) as s:
        s.execute(text("UPDATE disputes SET origin = 'PAYPAL_SANDBOX' WHERE id = :d"), {"d": dispute_id})
    assert upload(client, dispute_id, PNG, doc_type="delivery_proof", name="signed.png").status_code == 201
    ctx = worker.Context(worker_engine, lambda: None)
    while worker.run_one_job(ctx):
        pass
    a = client.get(f"/api/disputes/{dispute_id}/analysis").json()
    client.post(f"/api/drafts/{a['draft']['id']}/approve",
                json={"revision": a["draft"]["revision"], "snapshot_hash": a["snapshot_hash"]})

    class Fake:
        sent = []

        def get(self, pid):
            return {"status": "WAITING_FOR_SELLER_RESPONSE", "links": [{"rel": "provide_evidence"}]}

        def provide_evidence(self, pid, payload, files):
            self.sent.append(files)
            return {}

    fake = Fake()
    app.dependency_overrides[paypal_sink] = lambda: fake
    assert client.post(f"/api/drafts/{a['draft']['id']}/submit").status_code == 200
    files = fake.sent[0]
    assert any(data == PNG and mime == "image/png" and name.endswith(".png") for name, data, mime in files)
    assert sum(1 for _, _, mime in files if mime == "application/pdf") == 5  # seeded docs rendered from text


@pytest.mark.db
def test_batch_upload_queues_one_analysis(client, merchant, app_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-011")
    for i in range(3):
        assert upload(client, dispute_id, render_text_pdf([f"page {i}"]), doc_type="other").status_code == 201
    with tenant_session(merchant, app_engine) as s:
        n = s.execute(text("""SELECT count(*) FROM jobs WHERE kind = 'analyze_dispute' AND target_id = :d
                              AND state = 'QUEUED'"""), {"d": dispute_id}).scalar()
    assert n == 1
