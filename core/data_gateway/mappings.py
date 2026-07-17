from __future__ import annotations

from core.atlas_models import (
    AtlasDataBundle,
    AtlasIndexes,
    AtlasSourceStatus,
    EOATRecord,
    MachineRecord,
    PhotoItem,
    PhotoSet,
    ToolRecord,
    WarningItem,
)


def snapshot_to_bundle(snapshot: dict, project_root: str = "") -> AtlasDataBundle:
    photos_by_eoat: dict[str, list[PhotoItem]] = {}
    for item in snapshot.get("photos", []):
        photo = PhotoItem(
            path=item.get("storage_path", ""),
            filename=item.get("file_name", ""),
            photo_id=item.get("document_number") or item.get("document_uuid", ""),
            category=item.get("photo_view_type") or "",
            description=item.get("caption") or "",
            source="mysql_api",
        )
        for link in item.get("related_entities", []):
            if link.get("relationship_type") == "eoat":
                photos_by_eoat.setdefault(str(link.get("identifier", "")), []).append(photo)
    eoats = []
    for item in snapshot.get("eoats", []):
        relationships = item.get("relationships", [])
        machines = tuple(rel["identifier"] for rel in relationships if rel.get("relationship_type") == "machine")
        tools = tuple(rel["identifier"] for rel in relationships if rel.get("relationship_type") == "tool")
        location = item.get("current_location_detail") or {}
        state = str(location.get("state") or "UNKNOWN")
        warning = WarningItem(
            "warning" if state == "CONFLICTING" else "info",
            "Current location requires review" if state == "CONFLICTING" else "Current location not verified",
            str(location.get("evidence") or "No authoritative physical-location evidence is available."),
            source="mysql_api", related_eoat_id=item["business_identifier"],
        )
        evidence = item.get("audit_evidence", [])
        primary = evidence[0] if evidence else {}
        connection_pieces = [item.get("connection_type") or ""]
        for field_name in ("Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"):
            value = str(primary.get(field_name) or "").strip()
            if value.casefold() not in {"", "n/a", "na", "none", "unknown", "unknown / not checked", "not checked"}:
                connection_pieces.append(f"{field_name.replace(' Type', '')}: {value}")
        connection_summary = "; ".join(value for value in connection_pieces if value)
        linked_photos = tuple(photos_by_eoat.get(item["business_identifier"], ()))
        eoats.append(
            EOATRecord(
                eoat_id=item["business_identifier"],
                display_id=item.get("display_name") or item["business_identifier"],
                tools=tools,
                machines=machines,
                eoat_type=item.get("eoat_type") or "",
                status=item.get("status") or "",
                current_location=item.get("current_location") or state,
                current_location_status=state.casefold(),
                current_location_source=str(location.get("source") or "mysql_api"),
                current_location_confidence=str(location.get("confidence") or ""),
                current_location_resolution_reason=str(location.get("evidence") or ""),
                connection_type=connection_summary,
                vacuum_info="Present"
                if item.get("vacuum_present") is True
                else ("Not present" if item.get("vacuum_present") is False else "Unknown"),
                sensor_info="Present"
                if item.get("sensors_present") is True
                else ("Not present" if item.get("sensors_present") is False else "Unknown"),
                known_issues=item.get("notes") or "",
                photos=PhotoSet(
                    eoat_id=item["business_identifier"], photos=linked_photos, indexed_photos=linked_photos
                ),
                warnings=(warning,) if state in {"UNKNOWN", "CONFLICTING"} else (),
                source_rows=tuple(evidence),
            )
        )
    machines = []
    for item in snapshot.get("machines", []):
        current = str(item.get("current_eoat") or "")
        missing = current in {"NONE_OBSERVED", "UNKNOWN_NOT_VERIFIED"}
        machines.append(MachineRecord(
            machine=item["machine_number"],
            label=item.get("machine_name") or item["machine_number"],
            compatible_eoats=tuple(
                rel["identifier"] for rel in item.get("relationships", []) if rel.get("relationship_type") == "eoat"
            ),
            compatible_tools=tuple(
                rel["identifier"] for rel in item.get("relationships", []) if rel.get("relationship_type") == "tool"
            ),
            current_eoat="" if missing else current,
            current_eoat_status="unknown" if missing else "observed_installed",
            current_eoat_source="mysql_api",
            current_eoat_confidence="unverified" if missing else "authoritative_observation",
            source_rows=tuple(item.get("audit_evidence", ())),
        ))
    tools = [
        ToolRecord(
            tool=item["business_identifier"],
            label=item.get("display_name") or item["business_identifier"],
            molds=tuple(filter(None, [item.get("mold_number")])),
            compatible_eoats=tuple(
                rel["identifier"] for rel in item.get("relationships", []) if rel.get("relationship_type") == "eoat"
            ),
            compatible_machines=tuple(
                rel["identifier"] for rel in item.get("relationships", []) if rel.get("relationship_type") == "machine"
            ),
            source="mysql_api",
            source_rows=tuple(item.get("audit_evidence", ())),
        )
        for item in snapshot.get("tools", [])
    ]
    return AtlasDataBundle(
        project_root=project_root,
        loaded_at=snapshot.get("generated_at", ""),
        source_statuses=(AtlasSourceStatus("EOAT Atlas API", "mysql_api", True, True, "Read-only MySQL/API backend"),),
        eoats=tuple(eoats),
        machines=tuple(machines),
        tools=tuple(tools),
        indexes=AtlasIndexes(),
        metrics={
            "backend": "mysql_api",
            "schema_revision": snapshot.get("schema_revision"),
            "server_revision": snapshot.get("server_revision"),
        },
    )
