from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .audit_compatibility import normalize_machine_token, normalize_tool_identifier, parse_machine_tokens, text_value
from .eoat_ids import normalize_eoat_assembly_id


def normalize_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def row_value(row: dict[str, Any], aliases: Iterable[str]) -> str:
    normalized = {normalize_header(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(normalize_header(alias))
        text = display_value(value)
        if text:
            return text
    return ""


def display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.casefold() in {"n/a", "na", "none", "null"}:
        return ""
    return text


def normalized_lookup_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", display_value(value).casefold())


def normalized_tool_key(value: Any) -> str:
    return normalized_lookup_key(normalize_tool_identifier(value))


def normalized_machine_key(value: Any) -> str:
    return normalized_lookup_key(normalize_machine_token(value))


def normalized_eoat_key(value: Any) -> str:
    return normalized_lookup_key(normalize_eoat_assembly_id(value))


def split_multi_value(value: Any) -> tuple[str, ...]:
    text = text_value(value)
    if not text:
        return ()
    raw = re.split(r"[,;/\n\r]+", text)
    return tuple(dict.fromkeys(piece.strip() for piece in raw if piece.strip()))


def machine_tokens(value: Any) -> tuple[str, ...]:
    return tuple(parse_machine_tokens(value))


def sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    unique = {display_value(value) for value in values if display_value(value)}

    def key(value: str) -> tuple[int, int | str, str]:
        normalized = normalize_machine_token(value)
        if normalized.isdigit():
            return (0, int(normalized), value.casefold())
        return (1, value.casefold(), value)

    return tuple(sorted(unique, key=key))


def first_present(row: dict[str, Any], *aliases: str) -> str:
    return row_value(row, aliases)


__all__ = [
    "display_value",
    "first_present",
    "machine_tokens",
    "normalize_header",
    "normalized_eoat_key",
    "normalized_lookup_key",
    "normalized_machine_key",
    "normalized_tool_key",
    "row_value",
    "sorted_unique",
    "split_multi_value",
]
