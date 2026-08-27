from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .base import Base

PK = BIGINT(unsigned=True)
UTC_DEFAULT = text("UTC_TIMESTAMP(6)")


class UTCDateTime(TypeDecorator[datetime]):
    """Store UTC wall-clock values and always return timezone-aware UTC datetimes.

    MySQL's ``DATETIME`` deliberately does not preserve a timezone offset.  The
    application has always written UTC values, but SQLAlchemy consequently
    rehydrated them as naive datetimes and FastAPI serialized ambiguous ISO
    strings.  Normalizing at this single database boundary keeps the database
    representation in UTC while ensuring every API path identifies the instant
    as UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        # Legacy MySQL values and server defaults are UTC wall-clock values.
        # Treat an unannotated value the same way rather than applying a host
        # or user-local timezone while persisting it.
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=UTC_DEFAULT, onupdate=UTC_DEFAULT, nullable=False
    )


class VersionMixin(TimestampMixin):
    created_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    archived_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    source_system: Mapped[str] = mapped_column(String(64), server_default=text("'eoat_atlas'"), nullable=False)
    source_import_batch_id: Mapped[int | None] = mapped_column(PK, ForeignKey("import_batches.id", ondelete="SET NULL"))


class LookupMixin(TimestampMixin):
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"), nullable=False)


class EOATType(LookupMixin, Base):
    __tablename__ = "eoat_types"


class ConnectionType(LookupMixin, Base):
    __tablename__ = "connection_types"


class CleanroomClassification(LookupMixin, Base):
    __tablename__ = "cleanroom_classifications"


class AssetStatus(LookupMixin, Base):
    __tablename__ = "asset_statuses"


class CompatibilityStatus(LookupMixin, Base):
    __tablename__ = "compatibility_statuses"


class CompatibilitySource(LookupMixin, Base):
    __tablename__ = "compatibility_sources"


class DocumentType(LookupMixin, Base):
    __tablename__ = "document_types"


class HistoryEventType(LookupMixin, Base):
    __tablename__ = "history_event_types"


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    batch_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    batch_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_file_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Deliberately not an FK: import_batches must be creatable before users during
    # the first legacy import, and the actor may be an external administrator.
    started_by_user_id: Mapped[int | None] = mapped_column(PK)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False)
    records_discovered: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    records_imported: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    records_rejected: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    warnings_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class Plant(VersionMixin, Base):
    __tablename__ = "plants"
    __table_args__ = (CheckConstraint("row_version > 0", name="ck_plants_row_version"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    plant_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    plant_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Area(VersionMixin, Base):
    __tablename__ = "areas"
    __table_args__ = (UniqueConstraint("plant_id", "area_code", name="uq_areas_plant_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    plant_id: Mapped[int] = mapped_column(PK, ForeignKey("plants.id", ondelete="RESTRICT"), nullable=False)
    area_code: Mapped[str] = mapped_column(String(64), nullable=False)
    area_name: Mapped[str] = mapped_column(String(160), nullable=False)
    area_type: Mapped[str | None] = mapped_column(String(64))
    cleanroom_classification_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("cleanroom_classifications.id", ondelete="SET NULL")
    )
    description: Mapped[str | None] = mapped_column(Text)


class User(VersionMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    external_identity: Mapped[str | None] = mapped_column(String(255), unique=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    authentication_provider: Mapped[str | None] = mapped_column(String(64))
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"), nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", "assigned_at", name="uq_user_roles_assignment"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(PK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(PK, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    assigned_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DevelopmentIdentityMapping(VersionMixin, Base):
    """Explicit local rehearsal identity-to-role mapping; never a corporate directory map."""

    __tablename__ = "development_identity_mappings"
    __table_args__ = (
        UniqueConstraint("environment", "identity", name="uq_dev_identity_mapping_environment_identity"),
        CheckConstraint("row_version > 0", name="ck_dev_identity_mapping_row_version"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    identity: Mapped[str] = mapped_column(String(255), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)


class ExternalGroupRoleMapping(TimestampMixin, Base):
    """Server-side corporate directory group to application-role mapping."""

    __tablename__ = "external_group_role_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "external_group_identifier", "role_code", name="uq_external_group_role"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_group_identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    explicit_deny: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"), nullable=False)
    # A canonical recovery mapping is a security control, not presentation
    # text.  It is intentionally persisted so a renamed directory group cannot
    # turn an Administrator recovery path into an ordinary removable policy.
    is_system_policy: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
    # The original corporate-authentication seam predates governed browser
    # editing.  Keep its compact model, but give administrators an optimistic
    # concurrency token rather than silently overwriting another policy edit.
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    # Role mapping preserves existing access semantics.  Explicit operational
    # grants are separately default-deny so a new group cannot gain mutation
    # authority merely by being mapped to a non-Administrator role.
    permissions_json: Mapped[list[str]] = mapped_column(JSON, server_default=text("(JSON_ARRAY())"), nullable=False)


class CorporateUser(VersionMixin, Base):
    """Governed EOAT record for an identity that completed corporate sign-in.

    This intentionally records only the identity and access facts EOAT owns. It
    is neither an Active Directory mirror nor a store for provider secrets.
    """

    __tablename__ = "corporate_users"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_corporate_users_user"),
        UniqueConstraint("provider", "canonical_identity", name="uq_corporate_users_provider_identity"),
        CheckConstraint("sign_in_count >= 1", name="ck_corporate_users_sign_in_count"),
        CheckConstraint("row_version > 0", name="ck_corporate_users_row_version"),
        Index("ix_corporate_users_last_sign_in", "last_successful_sign_in_at"),
        Index("ix_corporate_users_access", "explicit_role_code", "explicit_denied", "is_active"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(PK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    first_successful_sign_in_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_successful_sign_in_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sign_in_count: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    explicit_role_code: Mapped[str | None] = mapped_column(String(64))
    explicit_denied: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
    access_reason: Mapped[str | None] = mapped_column(Text)
    access_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    access_changed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))


class CorporateAuthenticationSession(Base):
    """Opaque, short-lived corporate session; raw tokens are never persisted."""

    __tablename__ = "corporate_authentication_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_corporate_authentication_session_token"),
        Index("ix_corporate_authentication_sessions_user_active", "user_id", "expires_at", "revoked_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    session_reference: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(PK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    roles_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # Persist only directory groups which were relevant to an EOAT role
    # mapping.  This lets every protected request re-evaluate authorization
    # without retaining an unrelated directory-membership inventory.
    authorization_groups_json: Mapped[list[str] | None] = mapped_column(JSON)
    authenticated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoke_reason: Mapped[str | None] = mapped_column(String(128))
    fresh_authenticated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fresh_auth_operation: Mapped[str | None] = mapped_column(String(96))
    fresh_auth_risk_class: Mapped[str | None] = mapped_column(String(32))
    fresh_auth_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CorporateAuthenticationEvent(Base):
    """Bounded, credential-free authentication event evidence."""

    __tablename__ = "corporate_authentication_events"
    __table_args__ = (Index("ix_corporate_authentication_events_occurred", "occurred_at", "event_type"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    provider: Mapped[str | None] = mapped_column(String(32))
    reason_code: Mapped[str | None] = mapped_column(String(64))


class AdminRehearsalSession(Base):
    """Opaque server-side session used only by Phase 3 local/test admin mutations."""

    __tablename__ = "admin_rehearsal_sessions"
    __table_args__ = (
        UniqueConstraint("session_token_hash", name="uq_admin_rehearsal_session_token_hash"),
        Index("ix_admin_rehearsal_sessions_user_active", "user_id", "expires_at", "revoked_at"),
        Index("ix_admin_rehearsal_sessions_environment", "environment", "expires_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    session_reference: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    session_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(PK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    revoke_reason: Mapped[str | None] = mapped_column(String(512))


class AdminDangerStepUp(Base):
    """Short-lived, server-controlled development/test step-up proof.

    This is deliberately separate from the Phase 3 rehearsal session.  It is
    not a production corporate reauthentication mechanism.
    """

    __tablename__ = "admin_danger_step_ups"
    __table_args__ = (
        Index("ix_admin_danger_step_ups_session_expiry", "admin_rehearsal_session_id", "expires_at", "revoked_at"),
        Index("ix_admin_danger_step_ups_scope", "operation_type", "risk_class", "expires_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    step_up_reference: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    admin_rehearsal_session_id: Mapped[int] = mapped_column(
        PK, ForeignKey("admin_rehearsal_sessions.id", ondelete="CASCADE"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(96), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AdminOperation(Base):
    """Durable, browser-independent state for bounded Phase 4 operations."""

    __tablename__ = "admin_operations"
    __table_args__ = (
        UniqueConstraint("preview_reference", name="uq_admin_operations_preview_reference"),
        Index("ix_admin_operations_status", "operation_type", "status", "created_at"),
        Index("ix_admin_operations_actor", "actor_user_id", "created_at"),
        Index("ix_admin_operations_lock", "lock_key", "status"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(96), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    target_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    preview_reference: Mapped[str | None] = mapped_column(String(36))
    preview_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    target_fingerprint: Mapped[str | None] = mapped_column(String(64))
    lock_key: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AdminOperationFixture(Base):
    """Non-authoritative disposable data used only to exercise Phase 4 recovery.

    It is never exposed through a browser creation endpoint and is not a
    business-record table.  Acceptance fixtures are inserted by tests and may
    be removed only by the tightly scoped fixture-recovery rehearsal.
    """

    __tablename__ = "admin_operation_fixtures"
    __table_args__ = (
        UniqueConstraint("fixture_namespace", "fixture_key", name="uq_admin_operation_fixture_namespace_key"),
        Index("ix_admin_operation_fixtures_namespace", "fixture_namespace"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    fixture_namespace: Mapped[str] = mapped_column(String(96), nullable=False)
    fixture_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class ApplicationInstance(TimestampMixin, Base):
    __tablename__ = "application_instances"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    instance_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    computer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    installation_name: Mapped[str | None] = mapped_column(String(160))
    plant_id: Mapped[int | None] = mapped_column(PK, ForeignKey("plants.id", ondelete="SET NULL"))
    area_id: Mapped[int | None] = mapped_column(PK, ForeignKey("areas.id", ondelete="SET NULL"))
    application_version: Mapped[str] = mapped_column(String(64), nullable=False)
    launcher_version: Mapped[str | None] = mapped_column(String(64))
    operating_system: Mapped[str | None] = mapped_column(String(255))
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class StorageLocation(VersionMixin, Base):
    __tablename__ = "storage_locations"
    __table_args__ = (UniqueConstraint("plant_id", "location_code", name="uq_storage_locations_plant_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    plant_id: Mapped[int] = mapped_column(PK, ForeignKey("plants.id", ondelete="RESTRICT"), nullable=False)
    area_id: Mapped[int | None] = mapped_column(PK, ForeignKey("areas.id", ondelete="SET NULL"))
    location_code: Mapped[str] = mapped_column(String(64), nullable=False)
    location_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class EOAT(VersionMixin, Base):
    __tablename__ = "eoats"
    __table_args__ = (
        CheckConstraint("row_version > 0", name="ck_eoats_row_version"),
        CheckConstraint(
            "number_of_parts_picked IS NULL OR number_of_parts_picked >= 0", name="ck_eoats_parts_nonnegative"
        ),
        CheckConstraint(
            "number_of_vacuum_cups IS NULL OR number_of_vacuum_cups >= 0", name="ck_eoats_cups_nonnegative"
        ),
        CheckConstraint("number_of_grippers IS NULL OR number_of_grippers >= 0", name="ck_eoats_grippers_nonnegative"),
        Index("ix_eoats_legacy_identifier", "legacy_identifier"),
        Index("ix_eoats_display_name", "display_name"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    business_identifier: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    legacy_identifier: Mapped[str | None] = mapped_column(String(96))
    display_name: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    eoat_type_id: Mapped[int | None] = mapped_column(PK, ForeignKey("eoat_types.id", ondelete="SET NULL"))
    connection_type_id: Mapped[int | None] = mapped_column(PK, ForeignKey("connection_types.id", ondelete="SET NULL"))
    cleanroom_classification_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("cleanroom_classifications.id", ondelete="SET NULL")
    )
    status_id: Mapped[int | None] = mapped_column(PK, ForeignKey("asset_statuses.id", ondelete="SET NULL"))
    revision: Mapped[str | None] = mapped_column(String(64))
    number_of_parts_picked: Mapped[int | None] = mapped_column(Integer)
    number_of_vacuum_cups: Mapped[int | None] = mapped_column(Integer)
    number_of_grippers: Mapped[int | None] = mapped_column(Integer)
    vacuum_present: Mapped[bool | None] = mapped_column(Boolean)
    sensors_present: Mapped[bool | None] = mapped_column(Boolean)
    part_present_sensor_present: Mapped[bool | None] = mapped_column(Boolean)
    vacuum_confirmation_sensor_present: Mapped[bool | None] = mapped_column(Boolean)
    quick_disconnect_present: Mapped[bool | None] = mapped_column(Boolean)
    cup_material: Mapped[str | None] = mapped_column(String(160))
    frame_material: Mapped[str | None] = mapped_column(String(160))
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    maximum_payload_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    drawing_number: Mapped[str | None] = mapped_column(String(128))
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    date_built: Mapped[datetime | None] = mapped_column(Date)
    date_commissioned: Mapped[datetime | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class Machine(VersionMixin, Base):
    __tablename__ = "machines"
    __table_args__ = (
        UniqueConstraint("plant_id", "machine_number", name="uq_machines_plant_number"),
        CheckConstraint("press_capacity_tons IS NULL OR press_capacity_tons > 0", name="ck_machines_capacity_positive"),
        Index("ix_machines_number", "machine_number"),
        Index("ix_machines_area", "area_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    plant_id: Mapped[int] = mapped_column(PK, ForeignKey("plants.id", ondelete="RESTRICT"), nullable=False)
    area_id: Mapped[int | None] = mapped_column(PK, ForeignKey("areas.id", ondelete="SET NULL"))
    machine_number: Mapped[str] = mapped_column(String(64), nullable=False)
    machine_name: Mapped[str | None] = mapped_column(String(160))
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160))
    serial_number: Mapped[str | None] = mapped_column(String(160))
    machine_type: Mapped[str | None] = mapped_column(String(64))
    press_capacity_tons: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    controller_type: Mapped[str | None] = mapped_column(String(160))
    cleanroom_classification_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("cleanroom_classifications.id", ondelete="SET NULL")
    )
    status_id: Mapped[int | None] = mapped_column(PK, ForeignKey("asset_statuses.id", ondelete="SET NULL"))
    installation_date: Mapped[datetime | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class Robot(VersionMixin, Base):
    __tablename__ = "robots"
    __table_args__ = (
        UniqueConstraint("plant_id", "robot_number", name="uq_robots_plant_number"),
        CheckConstraint("payload_capacity_kg IS NULL OR payload_capacity_kg > 0", name="ck_robots_payload_positive"),
        CheckConstraint("reach_mm IS NULL OR reach_mm > 0", name="ck_robots_reach_positive"),
        Index("ix_robots_number", "robot_number"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    plant_id: Mapped[int] = mapped_column(PK, ForeignKey("plants.id", ondelete="RESTRICT"), nullable=False)
    area_id: Mapped[int | None] = mapped_column(PK, ForeignKey("areas.id", ondelete="SET NULL"))
    robot_number: Mapped[str] = mapped_column(String(64), nullable=False)
    robot_name: Mapped[str | None] = mapped_column(String(160))
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160))
    controller_model: Mapped[str | None] = mapped_column(String(160))
    serial_number: Mapped[str | None] = mapped_column(String(160))
    payload_capacity_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    reach_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mounting_type: Mapped[str | None] = mapped_column(String(128))
    communication_interface: Mapped[str | None] = mapped_column(String(128))
    status_id: Mapped[int | None] = mapped_column(PK, ForeignKey("asset_statuses.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)


class MachineRobotAssignment(Base):
    __tablename__ = "machine_robot_assignments"
    __table_args__ = (
        CheckConstraint("removed_at IS NULL OR removed_at >= assigned_at", name="ck_machine_robot_dates"),
        Index("ix_machine_robot_active", "machine_id", "removed_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(PK, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    robot_id: Mapped[int] = mapped_column(PK, ForeignKey("robots.id", ondelete="RESTRICT"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    assignment_reason: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))


class Tool(VersionMixin, Base):
    __tablename__ = "tools"
    __table_args__ = (Index("ix_tools_tool_number", "tool_number"), Index("ix_tools_mold_number", "mold_number"))
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    business_identifier: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    tool_number: Mapped[str | None] = mapped_column(String(96))
    mold_number: Mapped[str | None] = mapped_column(String(96))
    display_name: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    cavity_count: Mapped[int | None] = mapped_column(Integer)
    tool_type: Mapped[str | None] = mapped_column(String(64))
    customer: Mapped[str | None] = mapped_column(String(160))
    program_name: Mapped[str | None] = mapped_column(String(160))
    status_id: Mapped[int | None] = mapped_column(PK, ForeignKey("asset_statuses.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)


class Part(VersionMixin, Base):
    __tablename__ = "parts"
    __table_args__ = (Index("ix_parts_name", "part_name"), Index("ix_parts_family", "part_family"))
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    part_number: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    part_name: Mapped[str | None] = mapped_column(String(255))
    part_family: Mapped[str | None] = mapped_column(String(255))
    customer: Mapped[str | None] = mapped_column(String(160))
    material: Mapped[str | None] = mapped_column(String(160))
    resin_type: Mapped[str | None] = mapped_column(String(160))
    color: Mapped[str | None] = mapped_column(String(64))
    cleanroom_required: Mapped[bool | None] = mapped_column(Boolean)
    status_id: Mapped[int | None] = mapped_column(PK, ForeignKey("asset_statuses.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)


class ToolPart(Base):
    __tablename__ = "tool_parts"
    __table_args__ = (
        UniqueConstraint("tool_id", "part_id", "effective_from", name="uq_tool_parts_effective"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_tool_parts_dates"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tool_id: Mapped[int] = mapped_column(PK, ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False)
    part_id: Mapped[int] = mapped_column(PK, ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False)
    is_primary_part: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime())
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))


class CompatibilityMixin(VersionMixin):
    compatibility_status_id: Mapped[int] = mapped_column(
        PK, ForeignKey("compatibility_statuses.id", ondelete="RESTRICT"), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    verified_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    verification_source_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("compatibility_sources.id", ondelete="SET NULL")
    )
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reason: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class EOATMachineCompatibility(CompatibilityMixin, Base):
    __tablename__ = "eoat_machine_compatibility"
    __table_args__ = (
        UniqueConstraint("eoat_id", "machine_id", "effective_from", name="uq_eoat_machine_compatibility_effective"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="ck_eoat_machine_compatibility_dates"
        ),
        Index("ix_eoat_machine_lookup", "eoat_id", "machine_id"),
        Index("ix_machine_compatibility_status", "machine_id", "compatibility_status_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    eoat_id: Mapped[int] = mapped_column(PK, ForeignKey("eoats.id", ondelete="RESTRICT"), nullable=False)
    machine_id: Mapped[int] = mapped_column(PK, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    connection_compatible: Mapped[bool | None] = mapped_column(Boolean)
    payload_compatible: Mapped[bool | None] = mapped_column(Boolean)
    reach_compatible: Mapped[bool | None] = mapped_column(Boolean)
    cleanroom_compatible: Mapped[bool | None] = mapped_column(Boolean)
    robot_interface_compatible: Mapped[bool | None] = mapped_column(Boolean)
    utilities_compatible: Mapped[bool | None] = mapped_column(Boolean)


class ToolMachineCompatibility(CompatibilityMixin, Base):
    __tablename__ = "tool_machine_compatibility"
    __table_args__ = (
        UniqueConstraint("tool_id", "machine_id", "effective_from", name="uq_tool_machine_compatibility_effective"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="ck_tool_machine_compatibility_dates"
        ),
        Index("ix_tool_machine_lookup", "tool_id", "machine_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tool_id: Mapped[int] = mapped_column(PK, ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False)
    machine_id: Mapped[int] = mapped_column(PK, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    tonnage_compatible: Mapped[bool | None] = mapped_column(Boolean)
    physical_size_compatible: Mapped[bool | None] = mapped_column(Boolean)
    utilities_compatible: Mapped[bool | None] = mapped_column(Boolean)
    process_compatible: Mapped[bool | None] = mapped_column(Boolean)


class EOATToolCompatibility(CompatibilityMixin, Base):
    __tablename__ = "eoat_tool_compatibility"
    __table_args__ = (
        UniqueConstraint("eoat_id", "tool_id", "effective_from", name="uq_eoat_tool_compatibility_effective"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="ck_eoat_tool_compatibility_dates"
        ),
        Index("ix_eoat_tool_lookup", "eoat_id", "tool_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    eoat_id: Mapped[int] = mapped_column(PK, ForeignKey("eoats.id", ondelete="RESTRICT"), nullable=False)
    tool_id: Mapped[int] = mapped_column(PK, ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False)
    part_geometry_compatible: Mapped[bool | None] = mapped_column(Boolean)
    number_of_parts_compatible: Mapped[bool | None] = mapped_column(Boolean)
    vacuum_or_gripper_compatible: Mapped[bool | None] = mapped_column(Boolean)
    sensor_compatible: Mapped[bool | None] = mapped_column(Boolean)
    cycle_requirement_compatible: Mapped[bool | None] = mapped_column(Boolean)


class FitCheckRecord(Base):
    __tablename__ = "fit_check_records"
    __table_args__ = (
        Index("ix_fit_checks_performed", "performed_at"),
        Index("ix_fit_checks_entities", "machine_id", "tool_id", "eoat_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(PK, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    tool_id: Mapped[int] = mapped_column(PK, ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False)
    eoat_id: Mapped[int] = mapped_column(PK, ForeignKey("eoats.id", ondelete="RESTRICT"), nullable=False)
    overall_status_id: Mapped[int] = mapped_column(
        PK, ForeignKey("compatibility_statuses.id", ondelete="RESTRICT"), nullable=False
    )
    machine_tool_status_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("compatibility_statuses.id", ondelete="SET NULL")
    )
    machine_eoat_status_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("compatibility_statuses.id", ondelete="SET NULL")
    )
    tool_eoat_status_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("compatibility_statuses.id", ondelete="SET NULL")
    )
    evaluation_engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    performed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    application_instance_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("application_instances.id", ondelete="SET NULL")
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text)
    result_details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class EOATInstallation(TimestampMixin, Base):
    __tablename__ = "eoat_installations"
    __table_args__ = (
        CheckConstraint("removed_at IS NULL OR removed_at >= installed_at", name="ck_eoat_installations_dates"),
        UniqueConstraint("active_eoat_marker", name="uq_active_installation_eoat"),
        UniqueConstraint("active_machine_marker", name="uq_active_installation_machine"),
        Index("ix_installations_eoat_started", "eoat_id", "installed_at"),
        Index("ix_installations_machine_started", "machine_id", "installed_at"),
        Index("ix_installations_removed", "removed_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    eoat_id: Mapped[int] = mapped_column(PK, ForeignKey("eoats.id", ondelete="RESTRICT"), nullable=False)
    machine_id: Mapped[int] = mapped_column(PK, ForeignKey("machines.id", ondelete="RESTRICT"), nullable=False)
    tool_id: Mapped[int | None] = mapped_column(PK, ForeignKey("tools.id", ondelete="SET NULL"))
    robot_id: Mapped[int | None] = mapped_column(PK, ForeignKey("robots.id", ondelete="SET NULL"))
    installed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    installed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    removed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    installation_reason: Mapped[str | None] = mapped_column(String(255))
    removal_reason: Mapped[str | None] = mapped_column(String(255))
    installation_notes: Mapped[str | None] = mapped_column(Text)
    removal_notes: Mapped[str | None] = mapped_column(Text)
    application_instance_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("application_instances.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    source_import_batch_id: Mapped[int | None] = mapped_column(PK, ForeignKey("import_batches.id", ondelete="SET NULL"))
    active_eoat_marker: Mapped[int | None] = mapped_column(
        PK, Computed("CASE WHEN removed_at IS NULL THEN eoat_id ELSE NULL END")
    )
    active_machine_marker: Mapped[int | None] = mapped_column(
        PK, Computed("CASE WHEN removed_at IS NULL THEN machine_id ELSE NULL END")
    )


class EOATStorageAssignment(Base):
    __tablename__ = "eoat_storage_assignments"
    __table_args__ = (
        CheckConstraint(
            "removed_from_storage_at IS NULL OR removed_from_storage_at >= stored_at", name="ck_eoat_storage_dates"
        ),
        UniqueConstraint("active_eoat_marker", name="uq_active_storage_eoat"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    eoat_id: Mapped[int] = mapped_column(PK, ForeignKey("eoats.id", ondelete="RESTRICT"), nullable=False)
    storage_location_id: Mapped[int] = mapped_column(
        PK, ForeignKey("storage_locations.id", ondelete="RESTRICT"), nullable=False
    )
    stored_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    removed_from_storage_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stored_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    removed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    active_eoat_marker: Mapped[int | None] = mapped_column(
        PK, Computed("CASE WHEN removed_from_storage_at IS NULL THEN eoat_id ELSE NULL END")
    )


class Document(VersionMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_checksum", "checksum_sha256"),
        Index("ix_documents_number", "document_number"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    document_type_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_types.id", ondelete="RESTRICT"), nullable=False
    )
    document_number: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[str | None] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_extension: Mapped[str | None] = mapped_column(String(32))
    storage_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(64), server_default=text("'network_file'"), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    file_size_bytes: Mapped[int | None] = mapped_column(PK)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    status_id: Mapped[int | None] = mapped_column(PK, ForeignKey("asset_statuses.id", ondelete="SET NULL"))
    effective_from: Mapped[datetime | None] = mapped_column(UTCDateTime())
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    superseded_by_document_id: Mapped[int | None] = mapped_column(PK, ForeignKey("documents.id", ondelete="SET NULL"))


class Photo(TimestampMixin, Base):
    __tablename__ = "photos"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        PK, ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    photo_view_type: Mapped[str | None] = mapped_column(String(64))
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    captured_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    caption: Mapped[str | None] = mapped_column(Text)
    is_profile_photo: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    width_pixels: Mapped[int | None] = mapped_column(Integer)
    height_pixels: Mapped[int | None] = mapped_column(Integer)


class DocumentLink(Base):
    __tablename__ = "document_links"
    __table_args__ = (
        UniqueConstraint("document_id", "entity_type", "entity_id", "relationship_type", name="uq_document_links"),
        Index("ix_document_links_entity", "entity_type", "entity_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(PK, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(PK, nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))


class AuditRecord(VersionMixin, Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_records_entities", "eoat_id", "machine_id", "tool_id"),
        Index("ix_audit_records_date", "audit_date"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    audit_identifier: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    eoat_id: Mapped[int | None] = mapped_column(PK, ForeignKey("eoats.id", ondelete="SET NULL"))
    machine_id: Mapped[int | None] = mapped_column(PK, ForeignKey("machines.id", ondelete="SET NULL"))
    tool_id: Mapped[int | None] = mapped_column(PK, ForeignKey("tools.id", ondelete="SET NULL"))
    robot_id: Mapped[int | None] = mapped_column(PK, ForeignKey("robots.id", ondelete="SET NULL"))
    audit_date: Mapped[datetime | None] = mapped_column(UTCDateTime())
    performed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    status_id: Mapped[int | None] = mapped_column(PK, ForeignKey("asset_statuses.id", ondelete="SET NULL"))
    source_sheet: Mapped[str | None] = mapped_column(String(128))
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)


class EntityHistoryEvent(Base):
    __tablename__ = "entity_history_events"
    __table_args__ = (
        Index("ix_entity_history_timeline", "entity_type", "entity_id", "occurred_at"),
        Index("ix_entity_history_category", "entity_type", "entity_id", "event_category", "occurred_at"),
        Index("ix_entity_history_request", "request_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(PK, nullable=False)
    event_type_id: Mapped[int] = mapped_column(
        PK, ForeignKey("history_event_types.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    application_instance_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("application_instances.id", ondelete="SET NULL")
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
    event_category: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    previous_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    related_entity_type: Mapped[str | None] = mapped_column(String(64))
    related_entity_id: Mapped[int | None] = mapped_column(PK)
    source_table: Mapped[str | None] = mapped_column(String(64))
    source_record_id: Mapped[int | None] = mapped_column(PK)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class AuditEvent(Base):
    """Append-only global administrator audit evidence; separate from profile history."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user','service','system','import','migration')", name="ck_audit_events_actor_type"
        ),
        CheckConstraint("result IN ('SUCCESS','FAILURE','DENIED','PARTIAL')", name="ck_audit_events_result"),
        CheckConstraint("action_category <> ''", name="ck_audit_events_action_category"),
        CheckConstraint("schema_version > 0", name="ck_audit_events_schema_version"),
        Index("ix_audit_events_time", "occurred_at_utc"),
        Index("ix_audit_events_actor_time", "actor_id", "occurred_at_utc"),
        Index("ix_audit_events_action_time", "action", "occurred_at_utc"),
        Index("ix_audit_events_category_time", "action_category", "occurred_at_utc"),
        Index("ix_audit_events_entity_time", "entity_type", "entity_id", "occurred_at_utc"),
        Index("ix_audit_events_result", "result"),
        Index("ix_audit_events_correlation", "correlation_id"),
        Index("ix_audit_events_request", "request_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    occurred_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255))
    actor_display_name: Mapped[str | None] = mapped_column(String(255))
    actor_directory_name: Mapped[str | None] = mapped_column(String(255))
    actor_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    action_category: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_display_id: Mapped[str | None] = mapped_column(String(255))
    changed_fields_json: Mapped[list[str] | None] = mapped_column(JSON)
    before_state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason_or_note: Mapped[str | None] = mapped_column(Text)
    source_client: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    transaction_id: Mapped[str | None] = mapped_column(String(64))
    operation: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    schema_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class AuditChange(Base):
    __tablename__ = "audit_changes"
    __table_args__ = (
        UniqueConstraint("audit_event_id", "field_path", name="uq_audit_changes_event_field"),
        Index("ix_audit_changes_field", "field_path"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    audit_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("audit_events.event_id", ondelete="RESTRICT"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(512), nullable=False)
    before_value_json: Mapped[Any | None] = mapped_column(JSON)
    after_value_json: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class ChangeAuditLog(Base):
    __tablename__ = "change_audit_log"
    __table_args__ = (
        Index("ix_change_audit_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_change_audit_actor", "actor_user_id", "occurred_at"),
        Index("ix_change_audit_request", "request_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    application_instance_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("application_instances.id", ondelete="SET NULL")
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(PK, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    changed_fields_json: Mapped[list[str] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    api_version: Mapped[str | None] = mapped_column(String(64))
    client_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class ChangeFeed(Base):
    __tablename__ = "change_feed"
    __table_args__ = (
        Index("ix_change_feed_entity_cursor", "entity_type", "change_id"),
        Index("ix_change_feed_changed", "changed_at"),
    )
    change_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(PK, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    changed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    request_id: Mapped[str | None] = mapped_column(String(36))


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        UniqueConstraint("import_batch_id", "source_sheet", "source_row_number", name="uq_import_rows_source"),
        Index("ix_import_rows_target", "target_entity_type", "target_entity_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    import_batch_id: Mapped[int] = mapped_column(
        PK, ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False
    )
    source_sheet: Mapped[str] = mapped_column(String(128), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_identifier: Mapped[str | None] = mapped_column(String(255))
    target_entity_type: Mapped[str | None] = mapped_column(String(64))
    target_entity_id: Mapped[int | None] = mapped_column(PK)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    normalized_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class ImportIssue(Base):
    __tablename__ = "import_issues"
    __table_args__ = (Index("ix_import_issues_batch_severity", "import_batch_id", "severity"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    import_batch_id: Mapped[int] = mapped_column(
        PK, ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False
    )
    import_row_id: Mapped[int | None] = mapped_column(PK, ForeignKey("import_rows.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    issue_code: Mapped[str] = mapped_column(String(64), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(128))
    source_value: Mapped[str | None] = mapped_column(MEDIUMTEXT)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolved_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class SystemSetting(VersionMixin, Base):
    __tablename__ = "system_settings"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    setting_value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)


class SystemMetadata(TimestampMixin, Base):
    __tablename__ = "system_metadata"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    metadata_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    metadata_value: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)


class Tag(VersionMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        CheckConstraint("row_version > 0", name="ck_tags_row_version"),
        Index("ix_tags_display_name", "display_name"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tag_code: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    color_key: Mapped[str] = mapped_column(String(32), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
    source_record_identifier: Mapped[str | None] = mapped_column(String(255), unique=True)


class AnnotationTarget(VersionMixin, Base):
    __tablename__ = "annotation_targets"
    __table_args__ = (
        Index("ix_annotation_targets_type", "target_type"),
        Index("ix_annotation_targets_audit_field", "audit_identifier", "field_key"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    target_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_label: Mapped[str | None] = mapped_column(String(512))
    audit_identifier: Mapped[str | None] = mapped_column(String(96))
    machine_identifier: Mapped[str | None] = mapped_column(String(96))
    field_key: Mapped[str | None] = mapped_column(String(160))
    field_label: Mapped[str | None] = mapped_column(String(255))
    sheet_name: Mapped[str | None] = mapped_column(String(128))
    header_name: Mapped[str | None] = mapped_column(String(255))
    workbook_path: Mapped[str | None] = mapped_column(String(2048))
    cached_cell_ref: Mapped[str | None] = mapped_column(String(64))
    object_ref: Mapped[str | None] = mapped_column(String(512))
    source_record_identifier: Mapped[str | None] = mapped_column(String(255), unique=True)


class EntityTag(Base):
    __tablename__ = "entity_tags"
    __table_args__ = (
        CheckConstraint("row_version > 0", name="ck_entity_tags_row_version"),
        UniqueConstraint("active_assignment_key", name="uq_entity_tags_active_assignment"),
        Index("ix_entity_tags_entity", "entity_type", "entity_id"),
        Index("ix_entity_tags_target", "annotation_target_id"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tag_id: Mapped[int] = mapped_column(PK, ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(PK, nullable=False)
    annotation_target_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("annotation_targets.id", ondelete="RESTRICT")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    assigned_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    removed_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    source_record_identifier: Mapped[str | None] = mapped_column(String(255), unique=True)
    source_import_batch_id: Mapped[int | None] = mapped_column(PK, ForeignKey("import_batches.id", ondelete="SET NULL"))
    active_assignment_key: Mapped[str | None] = mapped_column(
        String(255),
        Computed("CASE WHEN removed_at IS NULL THEN CONCAT(tag_id, ':', entity_type, ':', entity_id) ELSE NULL END"),
    )


class Annotation(VersionMixin, Base):
    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint("row_version > 0", name="ck_annotations_row_version"),
        Index("ix_annotations_entity", "entity_type", "entity_id"),
        Index("ix_annotations_target", "annotation_target_id"),
        Index("ix_annotations_status", "status"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    annotation_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(PK)
    annotation_target_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("annotation_targets.id", ondelete="SET NULL")
    )
    annotation_type: Mapped[str] = mapped_column(String(64), server_default=text("'note'"), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    importance: Mapped[str] = mapped_column(String(32), server_default=text("'Neutral'"), nullable=False)
    status: Mapped[str | None] = mapped_column(String(64))
    collection: Mapped[str | None] = mapped_column(String(160))
    follow_up_date: Mapped[datetime | None] = mapped_column(Date)
    source_record_identifier: Mapped[str | None] = mapped_column(String(255), unique=True)


class AnnotationTargetLink(Base):
    __tablename__ = "annotation_target_links"
    __table_args__ = (UniqueConstraint("annotation_id", "annotation_target_id", name="uq_annotation_target_links"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    annotation_id: Mapped[int] = mapped_column(PK, ForeignKey("annotations.id", ondelete="CASCADE"), nullable=False)
    annotation_target_id: Mapped[int] = mapped_column(
        PK, ForeignKey("annotation_targets.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)


class MaintenanceEvent(VersionMixin, Base):
    __tablename__ = "maintenance_events"
    __table_args__ = (
        CheckConstraint(
            "downtime_minutes IS NULL OR downtime_minutes >= 0", name="ck_maintenance_downtime_nonnegative"
        ),
        Index("ix_maintenance_entity", "eoat_id", "machine_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    eoat_id: Mapped[int | None] = mapped_column(PK, ForeignKey("eoats.id", ondelete="SET NULL"))
    machine_id: Mapped[int | None] = mapped_column(PK, ForeignKey("machines.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    downtime_minutes: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    application_instance_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("application_instances.id", ondelete="SET NULL")
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "operation", "idempotency_key", name="uq_idempotency_actor_operation_key"),
        Index("ix_idempotency_expires", "expires_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int] = mapped_column(PK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_entity_type: Mapped[str | None] = mapped_column(String(64))
    result_entity_id: Mapped[int | None] = mapped_column(PK)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=UTC_DEFAULT, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CutoverSession(VersionMixin, Base):
    __tablename__ = "cutover_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PLANNED','SOURCE_FROZEN','IMPORTING','VALIDATING','READY',"
            "'AUTHORITY_ENABLED','MONITORING','ROLLED_BACK','COMPLETED','FAILED','CANCELLED')",
            name="ck_cutover_sessions_status",
        ),
        Index("ix_cutover_sessions_environment_status", "environment", "status"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    cutover_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot_timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    database_schema_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    api_version: Mapped[str] = mapped_column(String(32), nullable=False)
    client_version: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_by_user_id: Mapped[int | None] = mapped_column(PK, ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    authority_enabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rollback_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rollback_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rollback_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    start_change_feed_cursor: Mapped[int] = mapped_column(PK, server_default=text("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
