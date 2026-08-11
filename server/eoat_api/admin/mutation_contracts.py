from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..write_contracts import CompatibilityWrite, ExpectedVersion, WriteModel


class RehearsalSessionIssue(WriteModel):
    identity: str = Field(min_length=3, max_length=255, pattern=r"^(dev|staging)\.[a-z0-9._-]+$")
    rehearsal_secret: str = Field(min_length=16, max_length=512)


class AdminLifecycleRequest(ExpectedVersion):
    reason: str = Field(min_length=3, max_length=2000)
    confirmation: str = Field(min_length=3, max_length=255)


class AdminRelationshipWrite(CompatibilityWrite):
    reason: str | None = Field(default=None, max_length=2000)
    confirmation: str = Field(min_length=3, max_length=255)


class AdminDocumentPatch(ExpectedVersion):
    document_number: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    revision: str | None = Field(default=None, max_length=64)
    mime_type: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=2000)


class AdminPhotoPatch(ExpectedVersion):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    caption: str | None = Field(default=None, max_length=10000)
    photo_view_type: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=2000)


class AdminSettingUpdate(WriteModel):
    value: Any
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class AdminRoleMappingUpdate(WriteModel):
    role_code: Literal["ADMIN_AUDITOR", "ADMIN_DATA_MANAGER", "ADMIN_SETTINGS_MANAGER", "ADMIN_ACCESS_MANAGER", "ADMINISTRATOR"]
    expected_row_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


class AdminSessionRevoke(WriteModel):
    reason: str = Field(min_length=3, max_length=512)
    confirmation: str = Field(min_length=3, max_length=255)


class AdminBulkStatusPreview(WriteModel):
    identifiers: list[str] = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=64)
    expected_versions: dict[str, int] = Field(min_length=1)

    @model_validator(mode="after")
    def _identifiers_have_versions(self):
        identifiers = {value.strip() for value in self.identifiers}
        if len(identifiers) != len(self.identifiers) or not identifiers.issubset(self.expected_versions):
            raise ValueError("Each unique selected identifier must have an expected row version.")
        if any(version < 1 for version in self.expected_versions.values()):
            raise ValueError("Expected row versions must be positive.")
        return self


class AdminBulkStatusCommit(AdminBulkStatusPreview):
    reason: str = Field(min_length=3, max_length=2000)
    confirmation: str = Field(min_length=3, max_length=255)
