"""Evidence upload: validate, extract text, store privately, record, queue a fresh analysis.

Uploaded files are untrusted. The type is decided from the file's own bytes (not its name or the
browser's content type), sizes follow PayPal's limits, and text is kept as data with line numbers.
"""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import Engine, text

from app import repositories as repo
from app.db import tenant_session

MAX_BYTES = 10 * 1024 * 1024          # PayPal: < 10 MB per file
MAX_CASE_BYTES = 50 * 1024 * 1024     # PayPal: < 50 MB per case
MAX_PAGES = 30
MAX_LINES = 400
DOC_TYPES = {"order_invoice", "payment_record", "carrier_tracking", "delivery_proof", "support_message", "other"}
SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


class EvidenceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code


@dataclass(frozen=True)
class Stored:
    evidence_id: UUID
    mime: str
    lines: int
    job_queued: bool


def sniff_mime(data: bytes) -> str | None:
    return next((mime for sig, mime in SIGNATURES if data.startswith(sig)), None)


def extract_lines(data: bytes, mime: str) -> list[dict]:
    """Text of a PDF as numbered, non-empty lines. Images carry no text without OCR (not in the demo)."""
    if mime != "application/pdf":
        return []
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise EvidenceError(422, "PDF_ENCRYPTED", "This PDF is password-protected. Upload an unlocked copy.")
        raw = []
        for page in reader.pages[:MAX_PAGES]:
            raw.extend((page.extract_text() or "").splitlines())
    except EvidenceError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise EvidenceError(422, "PDF_UNREADABLE", "This PDF could not be read.") from exc
    lines = [" ".join(line.split()) for line in raw]
    lines = [line for line in lines if line][:MAX_LINES]
    return [{"line": i, "text": line} for i, line in enumerate(lines, 1)]


def store(merchant_id: UUID, dispute_id: UUID, data: bytes, filename: str, doc_type: str, uploaded_by: str,
          storage_dir: Path, engine: Engine | None = None) -> Stored:
    if doc_type not in DOC_TYPES:
        raise EvidenceError(422, "UNKNOWN_DOC_TYPE", f"doc_type must be one of {sorted(DOC_TYPES)}")
    if not data:
        raise EvidenceError(422, "EMPTY_FILE", "The file is empty.")
    if len(data) >= MAX_BYTES:
        raise EvidenceError(413, "FILE_TOO_LARGE", "Files must be smaller than 10 MB.")
    mime = sniff_mime(data)
    if mime is None:
        raise EvidenceError(415, "UNSUPPORTED_TYPE", "Only PDF, JPG, PNG or GIF files are accepted.")
    lines = extract_lines(data, mime)
    checksum = hashlib.sha256(data).hexdigest()

    with tenant_session(merchant_id, engine) as s:
        found = s.execute(text("SELECT 1 FROM disputes WHERE id = :d"), {"d": dispute_id}).first()
        if found is None:  # another tenant's dispute looks exactly like a missing one
            raise EvidenceError(404, "DISPUTE_NOT_FOUND", "Dispute not found.")
        if s.execute(text("SELECT 1 FROM evidence WHERE dispute_id = :d AND checksum = :c"),
                     {"d": dispute_id, "c": checksum}).first():
            raise EvidenceError(409, "DUPLICATE_FILE", "This file is already attached to the dispute.")
        used = s.execute(text("SELECT coalesce(sum(size_bytes), 0) FROM evidence WHERE dispute_id = :d"),
                         {"d": dispute_id}).scalar()
        if used + len(data) >= MAX_CASE_BYTES:
            raise EvidenceError(413, "CASE_TOO_LARGE", "A dispute can hold at most 50 MB of documents.")

        evidence_id = uuid4()
        object_key = f"{merchant_id}/{dispute_id}/{evidence_id}"
        path = storage_dir / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)  # written inside the transaction: a failed insert leaves only an orphan file
        s.execute(text("""
            INSERT INTO evidence (id, merchant_id, dispute_id, object_key, checksum, mime, size_bytes, uploaded_by,
                                  doc_type, content_lines, source_ref)
            VALUES (:id, :m, :d, :k, :c, :mime, :n, :by, :t, CAST(:lines AS jsonb), :name)"""),
            {"id": evidence_id, "m": merchant_id, "d": dispute_id, "k": object_key, "c": checksum, "mime": mime,
             "n": len(data), "by": uploaded_by, "t": doc_type, "lines": json.dumps(lines),
             "name": _display_name(filename, evidence_id)})
        # One pending analysis is enough: it reads every document when it runs, so a batch of uploads
        # triggers one analysis instead of one per file.
        pending = s.execute(text("""SELECT 1 FROM jobs WHERE kind = 'analyze_dispute' AND target_id = :d
                                    AND state = 'QUEUED'"""), {"d": dispute_id}).first()
        queued = pending is not None or repo.enqueue_job(
            s, merchant_id, "analyze_dispute", f"analyze:{dispute_id}:evidence:{evidence_id}", dispute_id)
        repo.write_audit(s, merchant_id, uploaded_by, "evidence.uploaded", target=str(dispute_id),
                         summary={"evidence_id": str(evidence_id), "type": doc_type, "mime": mime,
                                  "bytes": len(data), "lines": len(lines)})
    return Stored(evidence_id, mime, len(lines), queued)


def _display_name(filename: str, evidence_id: UUID) -> str:
    """A short, safe label used as the document's id in analyses (never a path)."""
    stem = Path(filename or "").name.rsplit(".", 1)[0]
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in stem)[:40].strip("-")
    return f"{safe or 'document'}-{str(evidence_id)[:8]}"


def read_file(storage_dir: Path, object_key: str) -> bytes | None:
    """Original bytes of a stored upload, or None for seeded demo documents that have no file."""
    path = (storage_dir / object_key).resolve()
    if storage_dir.resolve() not in path.parents or not path.is_file():
        return None
    return path.read_bytes()
