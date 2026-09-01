"""Deterministic, in-memory EOAT QR-label PDF generation."""

from __future__ import annotations

from io import BytesIO
from textwrap import wrap
from urllib.parse import quote

import qrcode
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_WIDTH = 4 * 72
PAGE_HEIGHT = 3 * 72
PAGE_SIZE = (PAGE_WIDTH, PAGE_HEIGHT)
_MARGIN = 12
_QR_SIZE = 144
_GAP = 10
_TEXT_WIDTH = PAGE_WIDTH - (_MARGIN * 2) - _QR_SIZE - _GAP


def canonical_eoat_profile_url(identifier: str, origin: str) -> str:
    """Return the immutable EOAT profile URL used in QR labels."""
    return f"{origin.rstrip('/')}/eoats/{quote(identifier, safe='')}"


def _identifier_lines(identifier: str) -> list[str]:
    """Keep even unusually long authoritative identifiers legible on 4x3 stock."""
    return wrap(identifier, width=13, break_long_words=True, break_on_hyphens=True) or [identifier]


def generate_eoat_qr_label_pdf(identifier: str, origin: str) -> tuple[bytes, str]:
    """Create a single 288x216-point label without touching the filesystem."""
    payload = canonical_eoat_profile_url(identifier, origin)
    qr_image = qrcode.make(payload, border=4)
    qr_bytes = BytesIO()
    qr_image.save(qr_bytes, format="PNG")
    qr_bytes.seek(0)

    output = BytesIO()
    document = canvas.Canvas(output, pagesize=PAGE_SIZE, invariant=1, pageCompression=1)
    document.setTitle(f"EOAT Atlas label - {identifier}")
    document.setAuthor("EOAT Atlas")
    document.setSubject("EOAT QR label")
    document.setCreator("EOAT Atlas")

    left = _MARGIN
    top = PAGE_HEIGHT - _MARGIN
    document.setFillColor(HexColor("#0D2038"))
    document.setFont("Helvetica-Bold", 13)
    document.drawString(left, top - 13, "EOAT Atlas")

    lines = _identifier_lines(identifier)
    identifier_size = 16 if len(lines) <= 2 else 13 if len(lines) <= 3 else 10
    line_height = identifier_size + 3
    document.setFont("Helvetica-Bold", identifier_size)
    identifier_y = top - 42
    for line in lines:
        document.drawString(left, identifier_y, line)
        identifier_y -= line_height

    document.setFont("Helvetica", 7.5)
    description_y = max(_MARGIN + 26, identifier_y - 7)
    for line in (
        "Scan for the EOAT profile,",
        "compatibility, documents,",
        "and history.",
    ):
        document.drawString(left, description_y, line)
        description_y -= 10

    qr_x = PAGE_WIDTH - _MARGIN - _QR_SIZE
    qr_y = (PAGE_HEIGHT - _QR_SIZE) / 2
    document.drawImage(
        ImageReader(qr_bytes), qr_x, qr_y, width=_QR_SIZE, height=_QR_SIZE, mask="auto"
    )
    document.showPage()
    document.save()
    return output.getvalue(), payload
