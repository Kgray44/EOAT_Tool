from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QFontMetrics, QGuiApplication


def test_offscreen_evidence_font_supports_freshness_status_glyphs(qapp) -> None:
    """Keep headless evidence readable without packaging a local font file."""
    if QGuiApplication.platformName().casefold() != "offscreen":
        return

    font = QFont("Segoe UI", 9)
    resolved = QFontInfo(font).family()
    metrics = QFontMetrics(font)
    required = {
        "U+002E": ".",
        "U+007C": "|",
        "U+00B7": "·",
        "U+00D7": "×",
        "U+2026": "…",
        "U+2022": "•",
        "U+2192": "→",
        "U+2713": "✓",
        "U+26A0": "⚠",
    }

    assert resolved
    assert "Segoe UI" in QFontDatabase.families()
    missing = [codepoint for codepoint, character in required.items() if not metrics.inFontUcs4(ord(character))]
    assert not missing, f"Offscreen font {resolved!r} is missing: {', '.join(missing)}"
