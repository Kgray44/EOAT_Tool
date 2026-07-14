from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReportOptions:
    include_summary: bool = True
    include_details: bool = True
    include_relationships: bool = True
    include_documentation: bool = True
    include_photos: bool = True
    include_photo_thumbnails: bool = True
    include_photo_appendix: bool = False
    include_missing_photo_status: bool = True
    include_history: bool = True
    include_notes: bool = True
    include_workbook_appendix: bool = True
    format_mode: str = "compact"
    output_path: str | Path | None = None
    auto_open_preview: bool = True

    @property
    def detailed(self) -> bool:
        return str(self.format_mode or "").casefold() == "detailed"


__all__ = ["ReportOptions"]
