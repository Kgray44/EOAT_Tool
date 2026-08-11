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


class AuditActionCategory(StrEnum):
    BUSINESS_DATA = "BUSINESS_DATA"
    RELATIONSHIPS = "RELATIONSHIPS"
    LOCATION_STATE = "LOCATION_STATE"
    DOCUMENTS_MEDIA = "DOCUMENTS_MEDIA"
    MAINTENANCE_INSPECTION = "MAINTENANCE_INSPECTION"
    IMPORTS_BULK = "IMPORTS_BULK"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    SETTINGS = "SETTINGS"
    EXPORTS = "EXPORTS"
    SYSTEM_OPERATIONS = "SYSTEM_OPERATIONS"
    DANGER_ZONE = "DANGER_ZONE"
    OTHER = "OTHER"


# Entity identifiers are intentionally owned by the server contract.  They are
# a discovery aid for the Administrator UI, not a database constraint: audit
# evidence may record a governed entity type introduced by a later migration.
AUDIT_ENTITY_TYPES = (
    "EOAT",
    "Machine",
    "Tool",
    "Relationship",
    "Document",
    "Maintenance",
    "Identity",
    "System",
)

ADMINISTRATIVE_AUDIT_CATEGORIES = (
    "SETTINGS",
    "EXPORTS",
    "SYSTEM_OPERATIONS",
    "DANGER_ZONE",
)


_ACTION_CATEGORIES = {
    AuditAction.CREATE: AuditActionCategory.BUSINESS_DATA,
    AuditAction.UPDATE: AuditActionCategory.BUSINESS_DATA,
    AuditAction.ARCHIVE: AuditActionCategory.BUSINESS_DATA,
    AuditAction.RESTORE: AuditActionCategory.BUSINESS_DATA,
    AuditAction.DELETE: AuditActionCategory.BUSINESS_DATA,
    AuditAction.LINK: AuditActionCategory.RELATIONSHIPS,
    AuditAction.UNLINK: AuditActionCategory.RELATIONSHIPS,
    AuditAction.ASSIGN: AuditActionCategory.RELATIONSHIPS,
    AuditAction.UNASSIGN: AuditActionCategory.RELATIONSHIPS,
    AuditAction.LOCATION_CHANGE: AuditActionCategory.LOCATION_STATE,
    AuditAction.STATUS_CHANGE: AuditActionCategory.LOCATION_STATE,
    AuditAction.UPLOAD: AuditActionCategory.DOCUMENTS_MEDIA,
    AuditAction.METADATA_CHANGE: AuditActionCategory.DOCUMENTS_MEDIA,
    AuditAction.SUPERSEDE: AuditActionCategory.DOCUMENTS_MEDIA,
    AuditAction.PHOTO_ADD: AuditActionCategory.DOCUMENTS_MEDIA,
    AuditAction.PHOTO_ARCHIVE: AuditActionCategory.DOCUMENTS_MEDIA,
    AuditAction.PM_COMPLETE: AuditActionCategory.MAINTENANCE_INSPECTION,
    AuditAction.INSPECTION_COMPLETE: AuditActionCategory.MAINTENANCE_INSPECTION,
    AuditAction.IMPORT_COMMIT: AuditActionCategory.IMPORTS_BULK,
    AuditAction.BULK_OPERATION: AuditActionCategory.IMPORTS_BULK,
    AuditAction.CORRECTION: AuditActionCategory.IMPORTS_BULK,
    AuditAction.LOGIN_SUCCESS: AuditActionCategory.AUTHENTICATION,
    AuditAction.LOGIN_FAILURE: AuditActionCategory.AUTHENTICATION,
    AuditAction.LOGOUT: AuditActionCategory.AUTHENTICATION,
    AuditAction.ACCESS_DENIED: AuditActionCategory.AUTHORIZATION,
    AuditAction.ROLE_MAPPING_CHANGE: AuditActionCategory.AUTHORIZATION,
    AuditAction.GROUP_MAPPING_CHANGE: AuditActionCategory.AUTHORIZATION,
    AuditAction.SETTINGS_CHANGE: AuditActionCategory.SETTINGS,
    AuditAction.EXPORT: AuditActionCategory.EXPORTS,
    AuditAction.SCHEMA_MIGRATED: AuditActionCategory.SYSTEM_OPERATIONS,
    AuditAction.ADMIN_REPAIR: AuditActionCategory.SYSTEM_OPERATIONS,
    AuditAction.DANGER_ATTEMPT: AuditActionCategory.DANGER_ZONE,
    AuditAction.DANGER_CONFIRMED: AuditActionCategory.DANGER_ZONE,
    AuditAction.DANGER_STARTED: AuditActionCategory.DANGER_ZONE,
    AuditAction.DANGER_SUCCEEDED: AuditActionCategory.DANGER_ZONE,
    AuditAction.DANGER_FAILED: AuditActionCategory.DANGER_ZONE,
}


def category_for_action(action: AuditAction) -> AuditActionCategory:
    return _ACTION_CATEGORIES.get(action, AuditActionCategory.OTHER)


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
