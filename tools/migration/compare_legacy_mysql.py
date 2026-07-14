from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select, text

from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from tools.migration.excel_to_mysql import MISSING_TOKENS, _checksum, _rows, _text


@dataclass
class Difference:
    classification: str
    entity_type: str
    identifier: str
    field: str
    legacy_value: Any
    mysql_value: Any
    explanation: str


def compare(source_workbook: str | Path, sqlite_path: str | Path | None = None) -> dict[str, Any]:
    source = Path(source_workbook).resolve()
    workbook = load_workbook(source, read_only=True, data_only=True)
    inventory = _rows(workbook["EOAT Inventory"])
    photos = _rows(workbook["Photo Index"])
    workbook.close()
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for number, row in inventory:
        grouped[_text(row.get("EOAT Assembly ID"))].append((number, row))
    expected_eoats = {value for value in grouped if value}
    expected_machines = {
        _text(row.get("Press/Machine #")) for _, row in inventory if _text(row.get("Press/Machine #")).isdigit()
    }
    expected_tools = {
        _text(row.get("Tool #")) for _, row in inventory if _text(row.get("Tool #")).casefold() not in MISSING_TOKENS
    }
    expected_em = {
        (_text(row.get("EOAT Assembly ID")), _text(row.get("Press/Machine #")))
        for _, row in inventory
        if _text(row.get("EOAT Assembly ID")) and _text(row.get("Press/Machine #")).isdigit()
    }
    expected_et = {
        (_text(row.get("EOAT Assembly ID")), _text(row.get("Tool #")))
        for _, row in inventory
        if _text(row.get("EOAT Assembly ID")) and _text(row.get("Tool #")).casefold() not in MISSING_TOKENS
    }
    expected_tm = {
        (_text(row.get("Tool #")), _text(row.get("Press/Machine #")))
        for _, row in inventory
        if _text(row.get("Tool #")).casefold() not in MISSING_TOKENS and _text(row.get("Press/Machine #")).isdigit()
    }
    differences: list[Difference] = []
    factory = create_session_factory()
    with factory() as session:
        mysql_eoats = set(session.scalars(select(db.EOAT.business_identifier)))
        mysql_machines = set(session.scalars(select(db.Machine.machine_number)))
        mysql_tools = set(session.scalars(select(db.Tool.business_identifier)))
        mysql_em = set(
            session.execute(
                select(db.EOAT.business_identifier, db.Machine.machine_number)
                .join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.eoat_id == db.EOAT.id)
                .join(db.Machine, db.Machine.id == db.EOATMachineCompatibility.machine_id)
            ).tuples()
        )
        mysql_et = set(
            session.execute(
                select(db.EOAT.business_identifier, db.Tool.business_identifier)
                .join(db.EOATToolCompatibility, db.EOATToolCompatibility.eoat_id == db.EOAT.id)
                .join(db.Tool, db.Tool.id == db.EOATToolCompatibility.tool_id)
            ).tuples()
        )
        mysql_tm = set(
            session.execute(
                select(db.Tool.business_identifier, db.Machine.machine_number)
                .join(db.ToolMachineCompatibility, db.ToolMachineCompatibility.tool_id == db.Tool.id)
                .join(db.Machine, db.Machine.id == db.ToolMachineCompatibility.machine_id)
            ).tuples()
        )
        actual = {
            "eoats": len(mysql_eoats),
            "machines": len(mysql_machines),
            "tools": len(mysql_tools),
            "eoat_machine_compatibility": len(mysql_em),
            "eoat_tool_compatibility": len(mysql_et),
            "tool_machine_compatibility": len(mysql_tm),
            "audits": session.scalar(select(__import__("sqlalchemy").func.count(db.AuditRecord.id))) or 0,
            "documents": session.scalar(select(__import__("sqlalchemy").func.count(db.Document.id))) or 0,
            "photos": session.scalar(select(__import__("sqlalchemy").func.count(db.Photo.id))) or 0,
            "parts": session.scalar(select(__import__("sqlalchemy").func.count(db.Part.id))) or 0,
            "installations": session.scalar(select(__import__("sqlalchemy").func.count(db.EOATInstallation.id))) or 0,
        }
        for entity_type, expected, observed in (
            ("EOAT", expected_eoats, mysql_eoats),
            ("Machine", expected_machines, mysql_machines),
            ("Tool", expected_tools, mysql_tools),
        ):
            for identifier in sorted(expected - observed):
                differences.append(
                    Difference(
                        "MISSING_FROM_MYSQL",
                        entity_type,
                        identifier,
                        "business_identifier",
                        identifier,
                        None,
                        "A supported source identifier was not imported.",
                    )
                )
            for identifier in sorted(observed - expected):
                differences.append(
                    Difference(
                        "UNEXPECTED_EXTRA_IN_MYSQL",
                        entity_type,
                        identifier,
                        "business_identifier",
                        None,
                        identifier,
                        "MySQL contains an identifier absent from the current workbook.",
                    )
                )
        for entity_type, expected, observed in (
            ("EOAT_MACHINE", expected_em, mysql_em),
            ("EOAT_TOOL", expected_et, mysql_et),
            ("TOOL_MACHINE", expected_tm, mysql_tm),
        ):
            for pair in sorted(expected ^ observed):
                differences.append(
                    Difference(
                        "RELATIONSHIP_MISMATCH",
                        entity_type,
                        "|".join(pair),
                        "relationship",
                        pair if pair in expected else None,
                        pair if pair in observed else None,
                        "Compatibility pair differs from the safe normalized source set.",
                    )
                )
        lookup_models = {
            "EOAT Type": db.EOATType,
            "Connection Type": db.ConnectionType,
            "Cleanroom/Non-Cleanroom": db.CleanroomClassification,
        }
        attr_names = {
            "EOAT Type": "eoat_type_id",
            "Connection Type": "connection_type_id",
            "Cleanroom/Non-Cleanroom": "cleanroom_classification_id",
        }
        for identifier, source_rows in grouped.items():
            entity = session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == identifier))
            if entity is None:
                continue
            for field_name, lookup_model in lookup_models.items():
                values = sorted({_text(row.get(field_name)) for _, row in source_rows if _text(row.get(field_name))})
                lookup_id = getattr(entity, attr_names[field_name])
                mysql_value = (
                    session.scalar(select(lookup_model.display_name).where(lookup_model.id == lookup_id))
                    if lookup_id
                    else None
                )
                if len(values) > 1:
                    classification = "SOURCE_CONFLICT" if mysql_value is None else "VALUE_MISMATCH"
                    differences.append(
                        Difference(
                            classification,
                            "EOAT",
                            identifier,
                            field_name,
                            values,
                            mysql_value,
                            "Conflicting source values are retained; normalized value must remain unknown unless explicitly resolved.",
                        )
                    )
                elif values and mysql_value != values[0]:
                    differences.append(
                        Difference(
                            "VALUE_MISMATCH",
                            "EOAT",
                            identifier,
                            field_name,
                            values[0],
                            mysql_value,
                            "Normalized profile value differs from the sole source value.",
                        )
                    )
        mysql_paths = set(session.scalars(select(db.Document.storage_path)))
        expected_paths = set()
        for _, row in photos:
            relative = _text(row.get("Stored Relative Path"))
            folder = _text(row.get("Folder Path"))
            filename = _text(row.get("Stored Filename")) or _text(row.get("Photo Filename"))
            if relative or (folder and filename):
                expected_paths.add(
                    str(source.parents[2] / relative if relative else source.parents[2] / folder / filename)
                )
        for path in sorted(expected_paths - mysql_paths):
            differences.append(
                Difference(
                    "MISSING_FROM_MYSQL",
                    "Document",
                    path,
                    "storage_path",
                    path,
                    None,
                    "A valid source path is absent from MySQL.",
                )
            )
        sqlite_counts = {}
        if sqlite_path and Path(sqlite_path).exists():
            with sqlite3.connect(sqlite_path) as connection:
                tables = [
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                ]
                sqlite_counts = {
                    table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables
                }
            if sum(sqlite_counts.values()):
                differences.append(
                    Difference(
                        "EXPECTED_DEFERRED_AMBIGUITY",
                        "SQLiteAnnotations",
                        str(Path(sqlite_path)),
                        "permanent_annotation_records",
                        sqlite_counts,
                        None,
                        "Permanent legacy annotations remain in the legacy SQLite authority during this read-only phase.",
                    )
                )
        duplicate_counts = {
            "eoats": session.scalar(
                text(
                    "SELECT COUNT(*) FROM (SELECT business_identifier FROM eoats GROUP BY business_identifier HAVING COUNT(*) > 1) d"
                )
            )
            or 0,
            "tools": session.scalar(
                text(
                    "SELECT COUNT(*) FROM (SELECT business_identifier FROM tools GROUP BY business_identifier HAVING COUNT(*) > 1) d"
                )
            )
            or 0,
            "audits": session.scalar(
                text(
                    "SELECT COUNT(*) FROM (SELECT audit_identifier FROM audit_records GROUP BY audit_identifier HAVING COUNT(*) > 1) d"
                )
            )
            or 0,
        }
    return {
        "source_workbook": str(source),
        "source_checksum": _checksum(source),
        "expected": {
            "eoats": len(expected_eoats),
            "machines": len(expected_machines),
            "tools": len(expected_tools),
            "eoat_machine_compatibility": len(expected_em),
            "eoat_tool_compatibility": len(expected_et),
            "tool_machine_compatibility": len(expected_tm),
            "audits": len(inventory),
            "valid_photo_rows": sum(
                1
                for _, row in photos
                if _text(row.get("Stored Relative Path"))
                or (
                    _text(row.get("Folder Path"))
                    and (_text(row.get("Stored Filename")) or _text(row.get("Photo Filename")))
                )
            ),
        },
        "actual": actual,
        "duplicate_identifiers": duplicate_counts,
        "sqlite_legacy_counts": sqlite_counts,
        "differences": [asdict(item) for item in differences],
        "classification_counts": {
            name: sum(item.classification == name for item in differences)
            for name in (
                "EXPECTED_NORMALIZATION",
                "EXPECTED_DEFERRED_AMBIGUITY",
                "MISSING_FROM_MYSQL",
                "UNEXPECTED_EXTRA_IN_MYSQL",
                "VALUE_MISMATCH",
                "RELATIONSHIP_MISMATCH",
                "SOURCE_CONFLICT",
            )
        },
    }


def write_report(report: dict[str, Any], output: str | Path) -> None:
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    (target / "legacy_mysql_parity_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    count_rows = "\n".join(
        f"| {key} | {report['expected'].get(key, '-')} | {value} |" for key, value in report["actual"].items()
    )
    difference_rows = (
        "\n".join(
            f"| {item['classification']} | {item['entity_type']} | {item['identifier']} | {item['field']} | {item['explanation']} |"
            for item in report["differences"]
        )
        or "| MATCH | - | - | - | No differences |"
    )
    (target / "legacy_mysql_parity_report.md").write_text(
        "# Legacy-to-MySQL Data Parity\n\n## Counts\n\n| Dataset | Legacy expected | MySQL |\n|---|---:|---:|\n"
        + count_rows
        + "\n\n## Identifier, value, and relationship differences\n\n| Classification | Entity | Identifier | Field | Explanation |\n|---|---|---|---|---|\n"
        + difference_rows
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-workbook", required=True)
    parser.add_argument("--sqlite-path")
    parser.add_argument("--output", default="reports/mysql_import")
    args = parser.parse_args()
    report = compare(args.source_workbook, args.sqlite_path)
    write_report(report, args.output)
    print(json.dumps({"classification_counts": report["classification_counts"], "actual": report["actual"]}))
    return (
        1
        if any(
            report["classification_counts"][key]
            for key in ("MISSING_FROM_MYSQL", "UNEXPECTED_EXTRA_IN_MYSQL", "VALUE_MISMATCH", "RELATIONSHIP_MISMATCH")
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
