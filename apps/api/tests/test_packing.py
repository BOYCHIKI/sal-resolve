"""Packing proof vault (ADR-007): recorded before shipping, matched to a dispute later, never proof of delivery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import actions, packing
from app.agent.models import CandidateFact, Document, Line, SourceRef
from app.agent.validation import ground
from app.config import get_settings
from app.db import tenant_session
from app.evidence import EvidenceError
from app.main import app, current_merchant
from app.seed import create_merchant
from app.seed_demo import seed_golden

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG_2 = b"\x89PNG\r\n\x1a\n" + b"\x01" * 64
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64


# --------------------------------------------------------------- pure
def test_codes_are_unguessable_base32():
    codes = {packing.new_code() for _ in range(200)}
    assert len(codes) == 200 and all(len(c) == 26 and set(c) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for c in codes)


def test_video_and_image_types_come_from_the_bytes():
    assert packing._sniff(PNG) == "image/png"
    assert packing._sniff(MP4) == "video/mp4"
    assert packing._sniff(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 8) == "video/quicktime"
    assert packing._sniff(b"<html>not a video</html>") is None


def test_a_packing_record_proves_nothing_by_itself():
    doc = Document("P", "packing_proof", (Line(1, "Status: DELIVERED 2026-10-19 Tracking: JP8812345678"),),
                   "SELLER_INPUT")
    facts = ground([CandidateFact("carrier_status", "DELIVERED", SourceRef("P", 1), "Status: DELIVERED"),
                    CandidateFact("tracking_id", "JP8812345678", SourceRef("P", 1), "Tracking: JP8812345678")], [doc])
    assert {f.status for f in facts} == {"rejected"}


def test_snad_card_mentions_the_packing_record_only_when_there_is_one():
    from tests.test_actions import NOW, dispute
    snad = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
    with_photos = actions.propose_for_dispute(dispute(reason=snad, packing_photos=3), None, None, NOW)[0]
    without = actions.propose_for_dispute(dispute(reason=snad), None, None, NOW)[0]
    assert "3 photo(s)" in with_photos.rationale and "PayPal decides" in with_photos.rationale
    assert "record the parcel in SAL before shipping" in without.rationale


# --------------------------------------------------------------- database
@pytest.fixture
def merchant(migrated_db) -> UUID:
    return create_merchant(f"Pack-{uuid4().hex[:6]}")


@pytest.mark.db
def test_a_record_needs_a_reference_and_valid_ones(merchant, app_engine):
    with pytest.raises(EvidenceError, match="order number"):
        packing.create(merchant, None, None, None, "operator:test", app_engine)
    with pytest.raises(EvidenceError) as bad:
        packing.create(merchant, None, "short", None, "operator:test", app_engine)
    assert bad.value.code == "BAD_TRANSACTION_ID"
    rec = packing.create(merchant, "ORD-77", None, "jp 8812 345678", "operator:test", app_engine)
    assert rec["tracking_number"] == "JP8812345678" and len(rec["code"]) == 26


@pytest.mark.db
def test_files_are_stored_by_content_with_their_hash_and_duplicates_refused(merchant, app_engine, tmp_path):
    rec = packing.create(merchant, "ORD-1", None, None, "operator:test", app_engine)
    pid = UUID(rec["id"])
    photo = packing.add_file(merchant, pid, PNG, "operator:test", tmp_path, app_engine)
    video = packing.add_file(merchant, pid, MP4, "operator:test", tmp_path, app_engine)
    assert (photo["mime"], video["mime"]) == ("image/png", "video/mp4")
    with pytest.raises(EvidenceError) as dup:
        packing.add_file(merchant, pid, PNG, "operator:test", tmp_path, app_engine)
    assert dup.value.code == "DUPLICATE_FILE"
    with pytest.raises(EvidenceError) as html:
        packing.add_file(merchant, pid, b"<script>", "operator:test", tmp_path, app_engine)
    assert html.value.status == 415
    stored = list((tmp_path / str(merchant) / "packing" / str(pid)).iterdir())
    assert len(stored) == 2


@pytest.mark.db
def test_another_merchant_cannot_add_files_or_print_the_label(merchant, app_engine, tmp_path):
    rec = packing.create(merchant, "ORD-2", None, None, "operator:test", app_engine)
    intruder = create_merchant("Intruder")
    with pytest.raises(EvidenceError) as other:
        packing.add_file(intruder, UUID(rec["id"]), PNG, "operator:test", tmp_path, app_engine)
    assert other.value.status == 404
    assert packing.label_pdf(intruder, UUID(rec["id"]), app_engine) is None
    assert packing.list_records(intruder, app_engine) == []


@pytest.mark.db
def test_the_label_is_a_pdf_with_the_qr_and_the_code(merchant, app_engine):
    rec = packing.create(merchant, "ORD-3", None, None, "operator:test", app_engine)
    pdf = packing.label_pdf(merchant, UUID(rec["id"]), app_engine)
    assert pdf.startswith(b"%PDF-1.4") and pdf.count(b" re f") > 100      # QR modules drawn as squares
    assert rec["code"][:4].encode() in pdf and b"ORD-3" in pdf


@pytest.mark.db
def test_a_matching_dispute_gets_the_photos_and_a_summary_once(merchant, app_engine, worker_engine, tmp_path):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")          # case_ref SAL-INR-001
    rec = packing.create(merchant, "SAL-INR-001", None, None, "operator:test", app_engine)
    pid = UUID(rec["id"])
    packing.add_file(merchant, pid, PNG, "operator:test", tmp_path, app_engine)
    packing.add_file(merchant, pid, PNG_2, "operator:test", tmp_path, app_engine)
    packing.add_file(merchant, pid, MP4, "operator:test", tmp_path, app_engine)

    assert packing.attach_to_dispute(merchant, dispute_id, worker_engine) == 3   # summary + 2 photos
    assert packing.attach_to_dispute(merchant, dispute_id, worker_engine) == 0   # idempotent
    with tenant_session(merchant, app_engine) as s:
        rows = s.execute(text("""SELECT mime, origin, content_lines FROM evidence
                                 WHERE dispute_id = :d AND doc_type = 'packing_proof' ORDER BY mime"""),
                         {"d": dispute_id}).all()
    assert [r.mime for r in rows] == ["image/png", "image/png", "text/plain"]
    assert {r.origin for r in rows} == {"SELLER_INPUT"}
    summary = " ".join(line["text"] for line in rows[-1].content_lines)
    assert "2 photo(s) and 1 video(s)" in summary and "PayPal accepts images and PDF only" in summary


@pytest.mark.db
def test_no_match_attaches_nothing(merchant, app_engine, worker_engine):
    dispute_id = seed_golden(app_engine, merchant, "SAL-INR-001")
    packing.create(merchant, "SOMETHING-ELSE", None, None, "operator:test", app_engine)
    assert packing.attach_to_dispute(merchant, dispute_id, worker_engine) == 0


@pytest.mark.db
def test_records_past_retention_are_deleted_with_their_files(merchant, app_engine, worker_engine, tmp_path):
    rec = packing.create(merchant, "ORD-OLD", None, None, "operator:test", app_engine)
    packing.add_file(merchant, UUID(rec["id"]), PNG, "operator:test", tmp_path, app_engine)
    engine = create_engine(get_settings().migrator_database_url)
    with engine.begin() as conn:   # age the record past its 180 days
        conn.execute(text("SELECT set_config('app.merchant_id', :m, true)"), {"m": str(merchant)})
        conn.execute(text("UPDATE packing_proofs SET expires_at = :t WHERE id = :p"),
                     {"t": datetime.now(timezone.utc) - timedelta(days=1), "p": rec["id"]})
    engine.dispose()
    assert packing.purge_expired(merchant, tmp_path, worker_engine) == 1
    assert not any((tmp_path / str(merchant)).rglob("*.*")) and not any(
        p.is_file() for p in (tmp_path / str(merchant)).rglob("*"))
    assert packing.list_records(merchant, app_engine) == []


@pytest.mark.db
def test_api_create_upload_list_and_label(merchant, app_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("SAL_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    app.dependency_overrides[current_merchant] = lambda: merchant
    try:
        client = TestClient(app)
        created = client.post("/api/packing", json={"order_ref": "ORD-API", "tracking_number": "JP8812345678"})
        assert created.status_code == 201
        pid = created.json()["id"]
        up = client.post(f"/api/packing/{pid}/files", files={"file": ("p.png", PNG, "image/png")})
        assert up.status_code == 201 and up.json()["mime"] == "image/png"
        items = client.get("/api/packing").json()["items"]
        assert items[0]["id"] == pid and len(items[0]["files"]) == 1
        label = client.get(f"/api/packing/{pid}/label.pdf")
        assert label.status_code == 200 and label.headers["content-type"] == "application/pdf"
        assert client.post("/api/packing", json={}).status_code == 422
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
