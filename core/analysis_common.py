from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .safe_files import ensure_directory, safe_write_text

OPEN_STATUSES = {"open", "not started", "needs follow-up", "in progress", "blocked", "new"}
CLOSED_STATUSES = {"closed", "complete", "completed", "resolved", "done"}


def timestamp_for_report() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def write_timestamped_report(folder: str | Path, base_name: str, markdown: str) -> Path:
    directory = ensure_directory(folder)
    stamp = timestamp_for_report()
    path = directory / f"{base_name}_{stamp}.md"
    try:
        return safe_write_text(path, markdown, overwrite=False)
    except FileExistsError:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return safe_write_text(directory / f"{base_name}_{stamp}.md", markdown, overwrite=False)


def write_timestamped_csv(folder: str | Path, base_name: str, rows: list[dict[str, Any]]) -> Path:
    directory = ensure_directory(folder)
    stamp = timestamp_for_report()
    path = directory / f"{base_name}_{stamp}.csv"
    if path.exists():
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = directory / f"{base_name}_{stamp}.csv"
    headers = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


def count_by(rows: Iterable[dict[str, Any]], field: str, blank_label: str = "Blank") -> dict[str, int]:
    return dict(Counter(str(row.get(field) or blank_label).strip() or blank_label for row in rows))


def table_from_counts(counts: dict[str, int], item_name: str = "Item") -> list[str]:
    if not counts:
        return ["No data yet."]
    lines = [f"| {item_name} | Count |", "| --- | ---: |"]
    for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key} | {value} |")
    return lines


def table_from_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["No data yet."]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")).replace("\n", " ") for col in columns) + " |")
    return lines


def parse_score(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def numeric(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        parsed = parse_score(value)
        return float(parsed or 0)

