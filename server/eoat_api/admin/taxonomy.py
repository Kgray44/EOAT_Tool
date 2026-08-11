from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    ARCHIVE = "ARCHIVE"
    RESTORE = "RESTORE"
    DELETE = "DELETE"
    LINK = "LINK"
    UNLINK = "UNLINK"
    ASSIGN = "ASSIGN"
    UNASSIGN = "UNASSIGN"
    LOCATION_CHANGE = "LOCATION_CHANGE"
    STATUS_CHANGE = "STATUS_CHANGE"
    UPLOAD = "UPLOAD"
    METADATA_CHANGE = "METADATA_CHANGE"
    SUPERSEDE = "SUPERSEDE"
    PHOTO_ADD = "PHOTO_ADD"
    PHOTO_ARCHIVE = "PHOTO_ARCHIVE"
    PM_COMPLETE = "PM_COMPLETE"
    INSPECTION_COMPLETE = "INSPECTION_COMPLETE"
    IMPORT_COMMIT = "IMPORT_COMMIT"
    BULK_OPERATION = "BULK_OPERATION"
    CORRECTION = "CORRECTION"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"
    ACCESS_DENIED = "ACCESS_DENIED"
    ROLE_MAPPING_CHANGE = "ROLE_MAPPING_CHANGE"
    GROUP_MAPPING_CHANGE = "GROUP_MAPPING_CHANGE"
    SETTINGS_CHANGE = "SETTINGS_CHANGE"
    EXPORT = "EXPORT"
    SCHEMA_MIGRATED = "SCHEMA_MIGRATED"
    ADMIN_REPAIR = "ADMIN_REPAIR"
    DANGER_ATTEMPT = "DANGER_ATTEMPT"
    DANGER_CONFIRMED = "DANGER_CONFIRMED"
    DANGER_STARTED = "DANGER_STARTED"
    DANGER_SUCCEEDED = "DANGER_SUCCEEDED"
    DANGER_FAILED = "DANGER_FAILED"


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
    PARTIAL = "PARTIAL"


class AuditActorType(StrEnum):
    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"
    IMPORT = "import"
    MIGRATION = "migration"


class AuditSource(StrEnum):
    WEB = "web"
    DESKTOP = "desktop"
    API = "api"
    IMPORT = "import"
    MIGRATION = "migration"
    SCHEDULED_SERVICE = "scheduled_service"
    SYSTEM = "system"


def action_for_legacy_operation(operation: str) -> AuditAction:
    """Map existing service operations to the governed, closed taxonomy."""
    value = operation.casefold()
    if "archive" in value:
        return AuditAction.ARCHIVE
    if "restore" in value:
        return AuditAction.RESTORE
    if "supersede" in value:
        return AuditAction.SUPERSEDE
    if "document" in value or "photo" in value:
        return AuditAction.METADATA_CHANGE
    if "compatibility" in value or "link" in value:
        return AuditAction.LINK
    if "remove" in value or "unassign" in value:
        return AuditAction.UNASSIGN
    if "assign" in value:
        return AuditAction.ASSIGN
    if "move" in value or "location" in value or "installation" in value:
        return AuditAction.LOCATION_CHANGE
    if "create" in value or value == "record_created":
        return AuditAction.CREATE
    return AuditAction.UPDATE
