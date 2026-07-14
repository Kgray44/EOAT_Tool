from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from .constants import TOOLKIT_ROOT
from .paths import resolve_project_paths

DEFAULT_GRIPPER_PRESETS_PATH = TOOLKIT_ROOT / "data_templates" / "gripper_presets.example.json"
PROJECT_GRIPPER_PRESETS_FILENAME = "gripper_presets.json"

_BUILTIN_GRIPPER_PRESETS = (
    {
        "friendly_name": "Large Double Gripper",
        "part_number": "MHZL2-16D",
        "manufacturer": "SMC",
        "default_type": "Double Pressure",
        "notes": "Default EOAT Atlas gripper preset.",
        "active": True,
    },
    {
        "friendly_name": "Small Double Gripper",
        "part_number": "MHZL2-10S",
        "manufacturer": "SMC",
        "default_type": "Single Pressure",
        "notes": "Default EOAT Atlas gripper preset.",
        "active": True,
    },
)
_PRESET_CACHE: dict[tuple[bool, tuple[tuple[str, bool, int, int], ...]], tuple[GripperPreset, ...]] = {}
_PRESET_CACHE_LOCK = RLock()


@dataclass(frozen=True)
class GripperPreset:
    friendly_name: str
    part_number: str
    manufacturer: str = ""
    default_type: str = ""
    notes: str = ""
    active: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GripperPreset:
        return cls(
            friendly_name=_text(data.get("friendly_name") or data.get("label")),
            part_number=_text(data.get("part_number") or data.get("model") or data.get("value")),
            manufacturer=_text(data.get("manufacturer")),
            default_type=_text(data.get("default_type")),
            notes=_text(data.get("notes")),
            active=bool(data.get("active", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_gripper_presets_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).reference_data / PROJECT_GRIPPER_PRESETS_FILENAME


def load_gripper_presets(
    project_root: str | Path | None = None,
    *,
    extra_paths: Iterable[str | Path] | None = None,
    include_inactive: bool = False,
) -> list[GripperPreset]:
    paths = _preset_source_paths(project_root, extra_paths)
    cache_key = (bool(include_inactive), tuple(_file_signature(path) for path in paths))
    with _PRESET_CACHE_LOCK:
        cached = _PRESET_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)
    loaded = _load_gripper_presets_uncached(paths, include_inactive=include_inactive)
    with _PRESET_CACHE_LOCK:
        _PRESET_CACHE[cache_key] = tuple(loaded)
    return list(loaded)


def _preset_source_paths(project_root: str | Path | None, extra_paths: Iterable[str | Path] | None) -> list[Path]:
    paths = [DEFAULT_GRIPPER_PRESETS_PATH]
    if project_root is not None:
        paths.append(project_gripper_presets_path(project_root))
    paths.extend(Path(path) for path in (extra_paths or []))
    return paths


def _file_signature(path: str | Path) -> tuple[str, bool, int, int]:
    source = Path(path).expanduser()
    try:
        resolved = source.resolve()
    except OSError:
        resolved = source
    try:
        stat = resolved.stat()
    except OSError:
        return str(resolved), False, 0, 0
    return str(resolved), True, stat.st_mtime_ns, stat.st_size


def _load_gripper_presets_uncached(paths: list[Path], *, include_inactive: bool) -> list[GripperPreset]:
    presets: dict[str, GripperPreset] = {}
    default_presets = _load_presets_from_file(paths[0]) if paths else []
    for preset in default_presets or [GripperPreset.from_dict(data) for data in _BUILTIN_GRIPPER_PRESETS]:
        if include_inactive or preset.active:
            presets[preset.friendly_name.casefold()] = preset

    for path in paths[1:]:
        for preset in _load_presets_from_file(path):
            if not preset.friendly_name or not preset.part_number:
                continue
            if include_inactive or preset.active:
                presets[preset.friendly_name.casefold()] = preset
            elif preset.friendly_name.casefold() in presets:
                presets.pop(preset.friendly_name.casefold(), None)
    return sorted(presets.values(), key=lambda preset: preset.friendly_name.casefold())


def gripper_model_display_values(project_root: str | Path | None = None) -> list[str]:
    return [preset.friendly_name for preset in load_gripper_presets(project_root)]


def default_gripper_display_to_value() -> dict[str, str]:
    return {preset.friendly_name: preset.part_number for preset in load_gripper_presets(None)}


def default_gripper_value_to_display() -> dict[str, str]:
    return {preset.part_number: preset.friendly_name for preset in load_gripper_presets(None)}


def gripper_model_to_workbook_value(value: Any, project_root: str | Path | None = None) -> str:
    text = _text(value)
    if not text:
        return ""
    mapping = {preset.friendly_name.casefold(): preset.part_number for preset in load_gripper_presets(project_root)}
    return mapping.get(text.casefold(), text)


def gripper_model_to_ui_value(value: Any, project_root: str | Path | None = None) -> str:
    text = _text(value)
    if not text:
        return ""
    mapping = {preset.part_number.casefold(): preset.friendly_name for preset in load_gripper_presets(project_root)}
    return mapping.get(text.casefold(), text)


def is_known_gripper_preset(value: Any, project_root: str | Path | None = None) -> bool:
    text = _text(value).casefold()
    if not text:
        return False
    for preset in load_gripper_presets(project_root):
        if text in {preset.friendly_name.casefold(), preset.part_number.casefold()}:
            return True
    return False


def _load_presets_from_default_source() -> list[GripperPreset]:
    presets = _load_presets_from_file(DEFAULT_GRIPPER_PRESETS_PATH)
    if presets:
        return presets
    return [GripperPreset.from_dict(data) for data in _BUILTIN_GRIPPER_PRESETS]


def _load_presets_from_file(path: str | Path) -> list[GripperPreset]:
    source = Path(path)
    if not source.exists():
        return []
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_presets = data.get("presets", data) if isinstance(data, dict) else data
    if not isinstance(raw_presets, list):
        return []
    presets: list[GripperPreset] = []
    for raw in raw_presets:
        if not isinstance(raw, dict):
            continue
        preset = GripperPreset.from_dict(raw)
        if preset.friendly_name and preset.part_number:
            presets.append(preset)
    return presets


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "DEFAULT_GRIPPER_PRESETS_PATH",
    "PROJECT_GRIPPER_PRESETS_FILENAME",
    "GripperPreset",
    "default_gripper_display_to_value",
    "default_gripper_value_to_display",
    "gripper_model_display_values",
    "gripper_model_to_ui_value",
    "gripper_model_to_workbook_value",
    "is_known_gripper_preset",
    "load_gripper_presets",
    "project_gripper_presets_path",
]
