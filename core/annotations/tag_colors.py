from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagColor:
    key: str
    label: str
    ui_hex: str
    excel_rgb: str


TAG_COLOR_PALETTE: dict[str, TagColor] = {
    "yellow": TagColor("yellow", "Yellow", "#facc15", "00FACC15"),
    "red": TagColor("red", "Red", "#ef4444", "00EF4444"),
    "green": TagColor("green", "Green", "#22c55e", "0022C55E"),
    "blue": TagColor("blue", "Blue", "#3b82f6", "003B82F6"),
    "purple": TagColor("purple", "Purple", "#a855f7", "00A855F7"),
    "orange": TagColor("orange", "Orange", "#f97316", "00F97316"),
    "gray": TagColor("gray", "Gray", "#9ca3af", "009CA3AF"),
    "teal": TagColor("teal", "Teal", "#14b8a6", "0014B8A6"),
    "pink": TagColor("pink", "Pink", "#ec4899", "00EC4899"),
}

DEFAULT_TAG_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "name": "Info",
        "color_key": "gray",
        "description": "Neutral context or useful information; does not imply a problem.",
    },
    {"name": "Needs Review", "color_key": "yellow", "description": "Field or item needs engineering review."},
    {"name": "Question", "color_key": "purple", "description": "Open question or unclear observation."},
    {"name": "Verified", "color_key": "green", "description": "Information has been checked and confirmed."},
    {"name": "Missing Evidence", "color_key": "orange", "description": "Documentation, photo, or proof is missing."},
    {"name": "Data Conflict", "color_key": "orange", "description": "Two pieces of project data disagree."},
    {"name": "Follow Up", "color_key": "yellow", "description": "Needs follow-up action."},
    {"name": "Pilot Candidate Evidence", "color_key": "blue", "description": "Evidence that supports pilot selection."},
    {
        "name": "Maintenance Concern",
        "color_key": "teal",
        "description": "Maintenance reliability or serviceability concern.",
    },
    {"name": "Compatibility Concern", "color_key": "blue", "description": "Machine/tool compatibility needs review."},
    {"name": "Documentation Gap", "color_key": "orange", "description": "Missing or incomplete documentation."},
    {"name": "Safety Concern", "color_key": "red", "description": "Safety concern requiring priority attention."},
    {"name": "Critical Issue", "color_key": "red", "description": "Critical issue requiring urgent review."},
    {"name": "Neutral", "color_key": "gray", "description": "Low-priority neutral annotation."},
)

TAG_PRIORITY_BY_NAME: dict[str, int] = {
    "critical issue": 10,
    "safety concern": 20,
    "data conflict": 30,
    "missing evidence": 40,
    "documentation gap": 45,
    "needs review": 50,
    "question": 60,
    "compatibility concern": 70,
    "pilot candidate evidence": 75,
    "maintenance concern": 80,
    "follow up": 90,
    "verified": 100,
    "info": 105,
    "neutral": 110,
}

NEUTRAL_CONTEXT_TAG_NAMES = frozenset({"info", "neutral", "verified"})


def is_neutral_context_tag(name: str) -> bool:
    return (name or "").strip().casefold() in NEUTRAL_CONTEXT_TAG_NAMES


COLOR_PRIORITY: dict[str, int] = {
    "red": 10,
    "orange": 30,
    "yellow": 50,
    "purple": 60,
    "blue": 70,
    "teal": 80,
    "green": 100,
    "gray": 110,
    "pink": 120,
}


def normalize_color_key(color_key: str) -> str:
    key = (color_key or "").strip().lower()
    if key not in TAG_COLOR_PALETTE:
        raise ValueError(f"Unsupported tag color: {color_key}")
    return key


def tag_priority(name: str, color_key: str = "gray") -> int:
    normalized_name = (name or "").strip().casefold()
    if normalized_name in TAG_PRIORITY_BY_NAME:
        return TAG_PRIORITY_BY_NAME[normalized_name]
    return COLOR_PRIORITY.get((color_key or "gray").strip().lower(), 999)


def highest_priority_tag(tags: list[dict[str, object]]) -> dict[str, object] | None:
    active = [tag for tag in tags if tag.get("color_key")]
    if not active:
        return None
    return sorted(
        active,
        key=lambda tag: (
            tag_priority(str(tag.get("name") or ""), str(tag.get("color_key") or "")),
            str(tag.get("name") or "").casefold(),
        ),
    )[0]


def excel_fill_for_color(color_key: str) -> str:
    return TAG_COLOR_PALETTE[normalize_color_key(color_key)].excel_rgb


def ui_hex_for_color(color_key: str) -> str:
    return TAG_COLOR_PALETTE[normalize_color_key(color_key)].ui_hex
