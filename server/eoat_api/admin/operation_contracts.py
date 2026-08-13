from __future__ import annotations

from pydantic import Field

from ..write_contracts import WriteModel


class IntegrityScanRequest(WriteModel):
    reason: str | None = Field(default=None, max_length=512)


class ExportRequest(WriteModel):
    format: str = Field(pattern="^(csv|json)$")
    filters: dict[str, str | bool | None] = Field(default_factory=dict)


class SupportBundleRequest(WriteModel):
    sections: list[str] = Field(min_length=1, max_length=4)
    request_id: str | None = Field(default=None, max_length=64)


class DangerStepUpRequest(WriteModel):
    rehearsal_step_up_secret: str = Field(min_length=16, max_length=512)


class DangerPreviewRequest(WriteModel):
    fixture_namespace: str = Field(min_length=6, max_length=96)


class DangerCommitRequest(WriteModel):
    preview_reference: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(min_length=3, max_length=255)
    reason: str = Field(min_length=3, max_length=2000)
