from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .atlas_models import PhotoItem, PhotoSet
from .atlas_utils import display_value, normalized_eoat_key, normalized_tool_key, row_value
from .eoat_ids import normalize_eoat_assembly_id
from .paths import resolve_project_paths
from .photo_indexing import PHOTO_CATEGORY_FOLDERS, SUPPORTED_IMAGE_EXTENSIONS, eoat_photo_root, photo_category_folder
from .tool_fields import TOOL_FIELD


def build_photo_index(
    project_root: str | Path,
    eoat_rows: list[dict[str, Any]],
    photo_rows: list[dict[str, Any]],
) -> tuple[dict[str, PhotoSet], dict[str, tuple[PhotoItem, ...]], list[str]]:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    folder_photos = _scan_photo_folder(paths.cell_photos, warnings)
    indexed_photos = [_photo_item_from_index_row(project_root, row) for row in photo_rows]
    indexed_photos = [photo for photo in indexed_photos if photo is not None]

    photos_by_eoat: dict[str, list[PhotoItem]] = {}
    photos_by_tool: dict[str, list[PhotoItem]] = {}
    for photo in [*folder_photos, *indexed_photos]:
        eoat_key = normalized_eoat_key(photo.eoat_id or _infer_eoat_from_path(photo.path))
        if eoat_key:
            photos_by_eoat.setdefault(eoat_key, []).append(photo)
        tool_key = normalized_tool_key(photo.tool or _infer_tool_from_path(photo.path))
        if tool_key:
            photos_by_tool.setdefault(tool_key, []).append(photo)

    photo_sets: dict[str, PhotoSet] = {}
    for row in eoat_rows:
        eoat_id = normalize_eoat_assembly_id(row.get("EOAT Assembly ID"))
        display_id = eoat_id or display_value(row.get("Audit ID"))
        if not display_id:
            continue
        eoat_key = normalized_eoat_key(display_id)
        folder = eoat_photo_root(project_root, eoat_id) if eoat_id else Path("")
        folder_items = tuple(_dedupe_photos(photos_by_eoat.get(eoat_key, [])))
        indexed_items = tuple(photo for photo in indexed_photos if normalized_eoat_key(photo.eoat_id) == eoat_key)
        missing_categories = _missing_photo_categories(folder_items)
        photo_sets[eoat_key] = PhotoSet(
            eoat_id=display_id,
            folder_path=str(folder) if eoat_id else display_value(row.get("Photo Folder/Link")),
            folder_exists=bool(eoat_id and folder.exists()),
            photos=folder_items,
            indexed_photos=tuple(_dedupe_photos(indexed_items)),
            missing_categories=missing_categories,
        )
    return photo_sets, {key: tuple(_dedupe_photos(value)) for key, value in photos_by_tool.items()}, warnings


def _scan_photo_folder(root: Path, warnings: list[str]) -> list[PhotoItem]:
    if not root.exists():
        warnings.append(f"Photos folder not found: {root}")
        return []
    incoming = (root / "Incoming_Photos").resolve(strict=False)
    photos: list[PhotoItem] = []
    try:
        walker = os.walk(root)
        for dirpath, _dirnames, filenames in walker:
            folder = Path(dirpath)
            if _is_relative_to(folder.resolve(strict=False), incoming):
                continue
            category = folder.name if folder.name in PHOTO_CATEGORY_FOLDERS else ""
            for filename in filenames:
                path = folder / filename
                if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                    continue
                photos.append(
                    PhotoItem(
                        path=str(path),
                        filename=filename,
                        category=category or photo_category_folder(folder.name),
                        eoat_id=_infer_eoat_from_path(path),
                        tool=_infer_tool_from_path(path),
                        source="folder",
                    )
                )
    except OSError as exc:
        warnings.append(f"Could not scan photos folder {root}: {exc}")
    return photos


def _photo_item_from_index_row(project_root: str | Path, row: dict[str, Any]) -> PhotoItem | None:
    filename = row_value(row, ("Stored Filename", "Photo Filename", "Original Filename"))
    folder_reference = row_value(row, ("Folder Path", "Stored Relative Path", "Photo Folder/Link"))
    if not filename and not folder_reference:
        return None
    path = _resolve_photo_path(project_root, folder_reference, filename)
    return PhotoItem(
        path=str(path),
        filename=path.name if path.name else filename,
        category=row_value(row, ("EOAT Area Shown", "Photo Type")) or photo_category_folder(path.parent.name),
        eoat_id=normalize_eoat_assembly_id(row.get("EOAT Assembly ID")),
        tool=row_value(row, (TOOL_FIELD, "Tool Number", "Tool #")),
        machine=row_value(row, ("Press/Machine #", "Machine #", "Machine Number")),
        related_audit_id=row_value(row, ("Related Audit ID", "Audit ID")),
        source="photo index",
    )


def _resolve_photo_path(project_root: str | Path, folder_reference: str, filename: str) -> Path:
    root = Path(project_root)
    if folder_reference:
        text = folder_reference.strip("\"'")
        if text.casefold().startswith("file://"):
            text = text[7:]
        folder = Path(text)
        if not folder.is_absolute():
            folder = root / folder
        if filename and folder.name != filename:
            candidate = folder / filename
            if candidate.suffix:
                return candidate
        return folder
    return root / filename


def _infer_eoat_from_path(path: str | Path) -> str:
    for part in Path(path).parts:
        match = re.fullmatch(r"P4-EOAT-\d{4}", part, flags=re.IGNORECASE)
        if match:
            return part.upper()
    name_match = re.search(r"P4-EOAT-\d{4}", Path(path).name, flags=re.IGNORECASE)
    return name_match.group(0).upper() if name_match else ""


def _infer_tool_from_path(path: str | Path) -> str:
    for part in Path(path).parts:
        match = re.match(r"Tool[_ -]+([^_\\/]+)", part, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    name_match = re.search(r"(?:Tool|Mold)[_ -]+([A-Za-z0-9.-]+)", Path(path).name, flags=re.IGNORECASE)
    return name_match.group(1) if name_match else ""


def _missing_photo_categories(photos: tuple[PhotoItem, ...]) -> tuple[str, ...]:
    if not photos:
        return ("00_Overall", "01_Front_View", "02_Side_View")
    present = {photo.category for photo in photos if photo.category}
    expected = ("00_Overall", "01_Front_View", "02_Side_View", "03_Vacuum_Cups_Grippers")
    return tuple(category for category in expected if category not in present)


def _dedupe_photos(photos: list[PhotoItem] | tuple[PhotoItem, ...]) -> list[PhotoItem]:
    deduped: dict[str, PhotoItem] = {}
    for photo in photos:
        key = photo.path.casefold() if photo.path else photo.filename.casefold()
        deduped.setdefault(key, photo)
    return sorted(deduped.values(), key=lambda item: (item.category.casefold(), item.filename.casefold()))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


__all__ = ["build_photo_index"]
