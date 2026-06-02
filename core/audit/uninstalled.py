from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.audit_constants import ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD
from core.tool_fields import TOOL_FIELD

UNINSTALLED_EOAT_NOTE = "EOAT Not Installed."
UNINSTALLED_EOAT_STATUS_TEXT = "Uninstalled EOAT audit mode: machine and robot fields are not required."
UNINSTALLED_MACHINE_CONTEXT_FIELDS = frozenset(
    {
        "Plant/Area",
        "Press/Machine #",
        "Robot Type",
        "Robot Model/Controller",
    }
)

_BLANKISH_VALUES = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "none",
    "not applicable",
    "select",
    "select machine",
    "select machine number",
    "enter machine",
    "enter machine number",
    "unknown",
    "unknown / not checked",
    "not checked",
}
_MACHINE_FIELD_ALIASES = (
    "Press/Machine #",
    "Press/Machine",
    "Press-Machine",
    "Machine Number",
    "Machine #",
    "Machine",
)


def normalize_identifier(value: Any) -> str:
    return "" if value is None else str(value).strip()


def is_blankish(value: Any) -> bool:
    return normalize_identifier(value).casefold() in _BLANKISH_VALUES


def has_meaningful_identifier(value: Any) -> bool:
    return not is_blankish(value)


def machine_number_value(entry: Mapping[str, Any]) -> str:
    for field_name in _MACHINE_FIELD_ALIASES:
        value = normalize_identifier(entry.get(field_name))
        if value:
            return value
    return ""


def tool_number_value(entry: Mapping[str, Any]) -> str:
    return normalize_identifier(entry.get(TOOL_FIELD) or entry.get("Tool #"))


def is_uninstalled_eoat_audit(entry: Mapping[str, Any]) -> bool:
    entry_type = normalize_identifier(entry.get(ENTRY_TYPE_FIELD)).casefold()
    if entry_type == ENTRY_TYPE_COMPATIBLE.casefold():
        return False
    return has_meaningful_identifier(tool_number_value(entry)) and is_blankish(machine_number_value(entry))


def append_uninstalled_note(notes: Any) -> str:
    existing = normalize_identifier(notes)
    if UNINSTALLED_EOAT_NOTE.casefold() in existing.casefold():
        return existing
    if is_blankish(existing):
        return UNINSTALLED_EOAT_NOTE
    return f"{existing.rstrip()}\n{UNINSTALLED_EOAT_NOTE}"


__all__ = [
    "UNINSTALLED_EOAT_NOTE",
    "UNINSTALLED_EOAT_STATUS_TEXT",
    "UNINSTALLED_MACHINE_CONTEXT_FIELDS",
    "append_uninstalled_note",
    "has_meaningful_identifier",
    "is_blankish",
    "is_uninstalled_eoat_audit",
    "machine_number_value",
    "normalize_identifier",
    "tool_number_value",
]
