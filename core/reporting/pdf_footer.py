from __future__ import annotations

from typing import Any

from core.versioning import get_release_info

LEGAL_FOOTER_TEXT = "For reference only"
DEFAULT_FOOTER_Y = 22
DEFAULT_FOOTER_LINE_Y = 34.5
DEFAULT_HORIZONTAL_MARGIN = 44.64


def pdf_page_size(canvas: Any, doc: Any) -> tuple[float, float]:
    pagesize = getattr(doc, "pagesize", None) or getattr(canvas, "_pagesize", None)
    if pagesize and len(pagesize) >= 2:
        return float(pagesize[0]), float(pagesize[1])
    return 612.0, 792.0


def draw_standard_pdf_footer(
    canvas: Any,
    doc: Any,
    *,
    left_text: str = "",
    right_text: str = "",
    footer_y: float = DEFAULT_FOOTER_Y,
    line_y: float = DEFAULT_FOOTER_LINE_Y,
) -> None:
    apply_pdf_release_metadata(canvas)
    width, _height = pdf_page_size(canvas, doc)
    left_x = float(getattr(doc, "leftMargin", DEFAULT_HORIZONTAL_MARGIN) or DEFAULT_HORIZONTAL_MARGIN)
    right_x = width - float(getattr(doc, "rightMargin", DEFAULT_HORIZONTAL_MARGIN) or DEFAULT_HORIZONTAL_MARGIN)

    canvas.saveState()
    canvas.setStrokeColorRGB(0.78, 0.84, 0.90)
    canvas.setLineWidth(0.5)
    canvas.line(left_x, line_y, right_x, line_y)
    canvas.setFillColorRGB(0.36, 0.43, 0.51)
    canvas.setFont("Helvetica", 8)
    if left_text:
        canvas.drawString(left_x, footer_y, str(left_text)[:128])
    canvas.drawCentredString(width / 2, footer_y, LEGAL_FOOTER_TEXT)
    if right_text:
        canvas.drawRightString(right_x, footer_y, str(right_text)[:64])
    canvas.restoreState()


def apply_pdf_release_metadata(canvas: Any) -> None:
    info = get_release_info()
    values = {
        "setCreator": f"EOAT Atlas {info.application_version}",
        "setAuthor": "EOAT Atlas",
        "setSubject": f"Release {info.release_id}; build {info.build_id}",
        "setKeywords": f"EOAT Atlas,{info.application_version},{info.release_id},{info.build_id}",
    }
    for method_name, value in values.items():
        method = getattr(canvas, method_name, None)
        if callable(method):
            method(value)


__all__ = ["LEGAL_FOOTER_TEXT", "apply_pdf_release_metadata", "draw_standard_pdf_footer", "pdf_page_size"]
