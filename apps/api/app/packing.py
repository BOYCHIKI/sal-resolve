"""Packing proof vault (ADR-007): photos or a short video of the parcel, recorded before shipping.

The seller creates a packing record (order number, PayPal transaction id and/or tracking number), uploads
photos or a video, and prints a QR label carrying a random code. When a dispute arrives, the worker matches it to
a record and attaches the photos plus a text summary to the case as the seller's evidence (origin SELLER_INPUT,
doc type packing_proof). Grounding accepts no fact from it: it shows what was packed and when, never delivery.
PayPal accepts images and PDF only, so videos stay in SAL.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import segno
from sqlalchemy import Engine, text

from app import repositories as repo
from app.db import tenant_session
from app.evidence import SIGNATURES, EvidenceError
from app.evidence_pdf import render_label_pdf

MAX_IMAGE_BYTES = 10 * 1024 * 1024   # PayPal's per-file limit, so a photo can be attached as it is
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_FILES = 10
IMAGES = {"image/jpeg", "image/png", "image/gif"}
_ORDER = re.compile(r"[A-Za-z0-9#/_. -]{1,64}")
_TXN = re.compile(r"[A-Z0-9]{17}")
_RESI = re.compile(r"(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{5,39}")
SOURCE_PREFIX = "Packing record"


def _sniff(data: bytes) -> str | None:
    for magic, mime in SIGNATURES:
        if data.startswith(magic):
            return mime
    if data[4:8] == b"ftyp":
        return "video/quicktime" if data[8:10] == b"qt" else "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None


def new_code() -> str:
    """128 random bits as 26 base32 characters: unguessable, and only this goes on the QR."""
    return base64.b32encode(secrets.token_bytes(16)).decode().rstrip("=")


def create(merchant_id: UUID, order_ref: str | None, transaction_id: str | None, tracking_number: str | None,
           created_by: str, engine: Engine | None = None) -> dict[str, Any]:
    order = " ".join((order_ref or "").split()) or None
    txn = (transaction_id or "").strip().upper() or None
    resi = "".join((tracking_number or "").split()).upper() or None
    if not (order or txn or resi):
        raise EvidenceError(422, "PACKING_NEEDS_REFERENCE", "Give the order number, PayPal transaction id or tracking number.")
    if order and not _ORDER.fullmatch(order):
        raise EvidenceError(422, "BAD_ORDER_REF", "Order number: up to 64 letters, digits and # / _ . -")
    if txn and not _TXN.fullmatch(txn):
        raise EvidenceError(422, "BAD_TRANSACTION_ID", "A PayPal transaction id has 17 letters and digits.")
    if resi and not _RESI.fullmatch(resi):
        raise EvidenceError(422, "BAD_TRACKING_NUMBER", "Enter the tracking number (resi) as printed: 6-40 letters and digits.")
    code = new_code()
    with tenant_session(merchant_id, engine) as s:
        row = s.execute(text("""
            INSERT INTO packing_proofs (merchant_id, code, order_ref, transaction_id, tracking_number)
            VALUES (:m, :c, :o, :t, :r) RETURNING id, created_at, expires_at"""),
            {"m": merchant_id, "c": code, "o": order, "t": txn, "r": resi}).one()
        repo.write_audit(s, merchant_id, created_by, "packing.created", target=str(row.id),
                         summary={"has_order": bool(order), "has_txn": bool(txn), "has_resi": bool(resi)})
    return {"id": str(row.id), "code": code, "order_ref": order, "transaction_id": txn, "tracking_number": resi,
            "created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat(), "files": []}


def add_file(merchant_id: UUID, packing_id: UUID, data: bytes, added_by: str, storage_dir: Path,
             engine: Engine | None = None) -> dict[str, Any]:
    if not data:
        raise EvidenceError(422, "EMPTY_FILE", "The file is empty.")
    mime = _sniff(data)
    if mime is None:
        raise EvidenceError(415, "UNSUPPORTED_TYPE", "Add JPG, PNG or GIF photos, or an MP4, MOV or WebM video.")
    limit = MAX_IMAGE_BYTES if mime in IMAGES else MAX_VIDEO_BYTES
    if len(data) >= limit:
        raise EvidenceError(413, "FILE_TOO_LARGE",
                            "Photos must be under 10 MB and videos under 50 MB." if mime in IMAGES else
                            "Videos must be under 50 MB.")
    digest = hashlib.sha256(data).hexdigest()
    with tenant_session(merchant_id, engine) as s:
        if s.execute(text("SELECT 1 FROM packing_proofs WHERE id = :p AND expires_at > now()"),
                     {"p": packing_id}).first() is None:   # another tenant's record looks exactly like a missing one
            raise EvidenceError(404, "PACKING_NOT_FOUND", "Packing record not found.")
        count = s.execute(text("SELECT count(*) FROM packing_files WHERE packing_id = :p"), {"p": packing_id}).scalar()
        if count >= MAX_FILES:
            raise EvidenceError(409, "TOO_MANY_FILES", f"A packing record holds at most {MAX_FILES} files.")
        if s.execute(text("SELECT 1 FROM packing_files WHERE packing_id = :p AND sha256 = :h"),
                     {"p": packing_id, "h": digest}).first():
            raise EvidenceError(409, "DUPLICATE_FILE", "This file is already on the packing record.")
        file_id = uuid4()
        object_key = f"{merchant_id}/packing/{packing_id}/{file_id}"
        path = storage_dir / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        s.execute(text("""INSERT INTO packing_files (id, merchant_id, packing_id, object_key, mime, sha256, size_bytes)
                          VALUES (:id, :m, :p, :k, :mime, :h, :n)"""),
                  {"id": file_id, "m": merchant_id, "p": packing_id, "k": object_key, "mime": mime, "h": digest,
                   "n": len(data)})
        repo.write_audit(s, merchant_id, added_by, "packing.file_added", target=str(packing_id),
                         summary={"mime": mime, "bytes": len(data), "sha256": digest})
    return {"id": str(file_id), "mime": mime, "sha256": digest, "size_bytes": len(data)}


def list_records(merchant_id: UUID, engine: Engine | None = None) -> list[dict[str, Any]]:
    with tenant_session(merchant_id, engine) as s:
        rows = s.execute(text("""
            SELECT p.id, p.code, p.order_ref, p.transaction_id, p.tracking_number, p.created_at, p.expires_at,
                   coalesce(json_agg(json_build_object('id', f.id, 'mime', f.mime, 'sha256', f.sha256,
                                                       'size_bytes', f.size_bytes) ORDER BY f.created_at)
                            FILTER (WHERE f.id IS NOT NULL), '[]') AS files
            FROM packing_proofs p LEFT JOIN packing_files f ON f.packing_id = p.id
            WHERE p.expires_at > now()
            GROUP BY p.id ORDER BY p.created_at DESC LIMIT 100""")).all()
    return [{"id": str(r.id), "code": r.code, "order_ref": r.order_ref, "transaction_id": r.transaction_id,
             "tracking_number": r.tracking_number, "created_at": r.created_at.isoformat(),
             "expires_at": r.expires_at.isoformat(), "files": r.files} for r in rows]


def label_pdf(merchant_id: UUID, packing_id: UUID, engine: Engine | None = None) -> bytes | None:
    with tenant_session(merchant_id, engine) as s:
        r = s.execute(text("""SELECT code, order_ref, transaction_id, tracking_number, created_at
                              FROM packing_proofs WHERE id = :p"""), {"p": packing_id}).first()
    if r is None:
        return None
    qr = segno.make(f"SAL-PACK:{r.code}", error="m")
    lines = ["SAL Resolve - packing record", " ".join(r.code[i:i + 4] for i in range(0, len(r.code), 4))]
    lines += [f"Order: {r.order_ref}"] if r.order_ref else []
    lines += [f"PayPal transaction: {r.transaction_id}"] if r.transaction_id else []
    lines += [f"Tracking: {r.tracking_number}"] if r.tracking_number else []
    lines += [f"Recorded: {r.created_at.astimezone(timezone.utc):%d %b %Y %H:%M} UTC",
              "Keep this label visible in your packing photos."]
    return render_label_pdf([[bool(m) for m in row] for row in qr.matrix], lines)


# ---------------------------------------------------------------- worker: attach a record to a dispute
def dispute_refs(s, dispute_id: UUID) -> tuple[str | None, set[str], set[str]] | None:
    d = s.execute(text("SELECT case_ref, provider_payload FROM disputes WHERE id = :d"), {"d": dispute_id}).first()
    if d is None:
        return None
    txns = (d.provider_payload or {}).get("disputed_transactions") or [{}]
    txn = (txns[0] or {}).get("seller_transaction_id")
    orders = {v for v in (d.case_ref, (txns[0] or {}).get("invoice_number")) if v}
    resis = set(s.execute(text("""
        SELECT DISTINCT f->>'value' FROM analyses a, jsonb_array_elements(a.facts) f
        WHERE a.dispute_id = :d AND f->>'field' = 'tracking_id' AND f->>'status' = 'supported'"""),
        {"d": dispute_id}).scalars())
    return txn, orders, resis


def attach_to_dispute(merchant_id: UUID, dispute_id: UUID, engine: Engine | None = None) -> int:
    """Attach the newest matching packing record to the dispute (idempotent). Returns documents added. Worker only."""
    with tenant_session(merchant_id, engine) as s:
        refs = dispute_refs(s, dispute_id)
        if refs is None:
            return 0
        txn, orders, resis = refs
        if not (txn or orders or resis):
            return 0
        p = s.execute(text("""
            SELECT id, code, order_ref, transaction_id, tracking_number, created_at FROM packing_proofs
            WHERE expires_at > now() AND (transaction_id = :t OR order_ref = ANY(:o) OR tracking_number = ANY(:r))
            ORDER BY created_at DESC LIMIT 1"""), {"t": txn, "o": list(orders), "r": list(resis)}).first()
        if p is None:
            return 0
        files = s.execute(text("""SELECT object_key, mime, sha256, size_bytes, created_at FROM packing_files
                                  WHERE packing_id = :p ORDER BY created_at"""), {"p": p.id}).all()
        photos = [f for f in files if f.mime in IMAGES]
        videos = [f for f in files if f.mime not in IMAGES]
        ref = f"{SOURCE_PREFIX} {p.code[:8]}"
        summary = [f"Packing record {p.code}, opened by the seller on "
                   f"{p.created_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC (server time)"]
        summary += [f"Order: {p.order_ref}"] if p.order_ref else []
        summary += [f"PayPal transaction: {p.transaction_id}"] if p.transaction_id else []
        summary += [f"Tracking: {p.tracking_number}"] if p.tracking_number else []
        summary.append(f"{len(photos)} photo(s) and {len(videos)} video(s) on the record")
        if files:  # only when SAL received them: it cannot know when they were taken
            summary.append(f"Files received by SAL from {files[0].created_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} "
                           f"to {files[-1].created_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC (server time)")
        summary += [f"SHA-256 {f.sha256} ({f.mime})" for f in files]
        if videos:
            summary.append("Videos are kept in SAL: PayPal accepts images and PDF only.")
        body = "\n".join(summary)
        rows = [(None, hashlib.sha256(body.encode()).hexdigest(), "text/plain", len(body.encode()), ref,
                 [{"line": i, "text": t} for i, t in enumerate(summary, 1)])]
        rows += [(f.object_key, f.sha256, f.mime, f.size_bytes, f"{ref} photo {i}", [])
                 for i, f in enumerate(photos, 1)]
        added = 0
        for key, checksum, mime, size, source_ref, lines in rows:
            added += s.execute(text("""
                INSERT INTO evidence (merchant_id, dispute_id, object_key, checksum, mime, size_bytes, uploaded_by,
                                      doc_type, content_lines, source_ref, origin)
                VALUES (:m, :d, :k, :c, :mime, :n, 'sal:packing', 'packing_proof', CAST(:l AS jsonb), :ref,
                        'SELLER_INPUT')
                ON CONFLICT (dispute_id, checksum) DO NOTHING RETURNING 1"""),
                {"m": merchant_id, "d": dispute_id, "k": key, "c": checksum, "mime": mime, "n": size,
                 "l": json.dumps(lines), "ref": source_ref}).rowcount
        if added:
            repo.write_audit(s, merchant_id, "sal:packing", "packing.attached", target=str(dispute_id),
                             summary={"packing_id": str(p.id), "documents": added})
    return added


def purge_expired(merchant_id: UUID, storage_dir: Path, engine: Engine | None = None) -> int:
    """Delete packing records past their retention, files first. Worker only. A record whose photos are evidence on
    a dispute that is still open stays until the dispute ends, since a send attaches those same files."""
    with tenant_session(merchant_id, engine) as s:
        ids = s.execute(text("""
            SELECT p.id FROM packing_proofs p WHERE p.expires_at <= now() AND NOT EXISTS (
                SELECT 1 FROM packing_files f JOIN evidence e ON e.object_key = f.object_key
                JOIN disputes d ON d.id = e.dispute_id
                WHERE f.packing_id = p.id AND d.provider_status IS DISTINCT FROM 'RESOLVED')""")).scalars().all()
        keys = s.execute(text("SELECT object_key FROM packing_files WHERE packing_id = ANY(:ids)"),
                         {"ids": ids}).scalars().all()
        gone = s.execute(text("DELETE FROM packing_proofs WHERE id = ANY(:ids)"), {"ids": ids}).rowcount
    for key in keys:
        path = (storage_dir / key).resolve()
        if storage_dir.resolve() in path.parents and path.is_file():
            path.unlink()
    return gone
