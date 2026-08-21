"""Export a read-only, source-of-truth EOAT photo inventory for media staging.

Run this only in a controlled environment where ``EOAT_DATABASE_URL`` is
already supplied by protected runtime configuration.  It does not modify the
database and intentionally emits storage paths only to the named protected
output file, never through an API response.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, prefix=f".{path.name}.", encoding="utf-8") as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_inventory(database_url: str, output: Path) -> dict[str, int]:
    """Read linked EOAT photo metadata without mutating database state."""
    query = text(
        """
        SELECT d.document_uuid, d.storage_path, d.file_name, d.file_extension,
               d.file_size_bytes, d.checksum_sha256, e.business_identifier AS eoat_identifier
        FROM documents AS d
        JOIN photos AS p ON p.document_id = d.id
        JOIN document_links AS l ON l.document_id = d.id AND l.entity_type = 'eoat'
        JOIN eoats AS e ON e.id = l.entity_id
        WHERE d.is_active = 1
        ORDER BY d.document_uuid, e.business_identifier
        """
    )
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
    finally:
        engine.dispose()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        document_uuid = str(row["document_uuid"])
        current = grouped.setdefault(
            document_uuid,
            {
                "document_uuid": document_uuid,
                "source_path": str(row["storage_path"]),
                "file_name": str(row["file_name"]),
                "file_extension": str(row["file_extension"] or ""),
                "source_size_bytes": int(row["file_size_bytes"]) if row["file_size_bytes"] is not None else None,
                "source_sha256": str(row["checksum_sha256"]).casefold() if row["checksum_sha256"] else None,
                "eoat_links": [],
            },
        )
        current["eoat_links"].append(str(row["eoat_identifier"]))
    entries = []
    for value in grouped.values():
        value["eoat_links"] = sorted(set(value["eoat_links"]))
        entries.append(value)
    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "entries": sorted(entries, key=lambda entry: entry["document_uuid"]),
    }
    _atomic_json(output, payload)
    return {"linked_photo_count": len(entries), "eoat_link_count": len(rows)}


def _database_url_from_environment() -> str:
    explicit = os.getenv("EOAT_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    required = {name: os.getenv(name, "").strip() for name in ("EOAT_DB_HOST", "EOAT_DB_NAME", "EOAT_DB_USER", "EOAT_DB_PASSWORD")}
    if not all(required.values()):
        raise RuntimeError("Protected EOAT database environment is incomplete.")
    port = os.getenv("EOAT_DB_PORT", "3306").strip() or "3306"
    return "mysql+pymysql://{user}:{password}@{host}:{port}/{database}".format(
        user=quote_plus(required["EOAT_DB_USER"]),
        password=quote_plus(required["EOAT_DB_PASSWORD"]),
        host=required["EOAT_DB_HOST"],
        port=port,
        database=quote_plus(required["EOAT_DB_NAME"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        database_url = _database_url_from_environment()
    except RuntimeError as exc:
        parser.error(str(exc))
    report = export_inventory(database_url, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
