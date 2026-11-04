"""Dependency-free renderer: evidence text lines -> a single-page text PDF (from the G1 spike).

PayPal accepts PDF/JPG/PNG/GIF evidence, < 10 MB per file and < 50 MB per case.
"""
from __future__ import annotations


def _escape(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_text_pdf(lines: list[str]) -> bytes:
    ops = ["BT", "/F1 11 Tf", "14 TL", "50 800 Td"]
    for line in lines:
        ops.append(f"({_escape(line)}) Tj T*")
    ops.append("ET")
    return _single_page(ops)


def render_label_pdf(matrix: list[list[bool]], lines: list[str], module: float = 4.0) -> bytes:
    """A printable label: the QR drawn as filled squares (vector, so it prints sharp at any size) above the text."""
    quiet, n = 4, len(matrix)
    side = (n + 2 * quiet) * module
    left, top = 50.0, 790.0
    ops = ["0 g"]
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                x = left + (c + quiet) * module
                y = top - (r + quiet + 1) * module
                ops.append(f"{x:.2f} {y:.2f} {module:.2f} {module:.2f} re f")
    ops += ["BT", "/F1 12 Tf", "16 TL", f"{left:.2f} {top - side - 16:.2f} Td"]
    for line in lines:
        ops.append(f"({_escape(line)}) Tj T*")
    ops.append("ET")
    return _single_page(ops)


def _single_page(ops: list[str]) -> bytes:
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
