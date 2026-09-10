from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OnboardingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OnboardingDraftCreate(OnboardingModel):
    proposed_identifier: str | None = Field(default=None, max_length=64)
    plant_code: str | None = Field(default=None, max_length=32)
    area_code: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class OnboardingDraftPatch(OnboardingDraftCreate):
    expected_row_version: int = Field(ge=1)


class OnboardingDraftDiscard(OnboardingModel):
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class OnboardingFinalize(OnboardingModel):
    expected_row_version: int = Field(ge=1)


class OnboardingIdentifierGenerate(OnboardingModel):
    expected_row_version: int = Field(ge=1)


class OnboardingMediaCreate(OnboardingModel):
    media_kind: Literal["document", "photo"]
    document_type: str = Field(min_length=1, max_length=64)
    file_name: str = Field(min_length=1, max_length=512)
    storage_path: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    revision: str | None = Field(default=None, max_length=64)
    mime_type: str | None = Field(default=None, max_length=255)
    photo_view_type: str | None = Field(default=None, max_length=64)
    caption: str | None = None


class OnboardingMediaUpload(OnboardingMediaCreate):
    content_base64: str = Field(min_length=1, max_length=36_000_000)


class OnboardingMediaArchive(OnboardingModel):
    expected_row_version: int = Field(ge=1)


class OnboardingProfilePhotoSelect(OnboardingModel):
    reason: str | None = Field(default=None, max_length=2000)


class OnboardingProfilePhotoSelectionResult(OnboardingModel):
    row_version: int = Field(ge=1)


class EOATEngineeringPatch(OnboardingModel):
    expected_row_version: int = Field(ge=0)
    cylinders_present: bool | None = None
    cylinder_count: int | None = Field(default=None, ge=0)
    cylinder_type: str | None = None
    cylinder_model: str | None = None
    gripper_type: str | None = None
    gripper_model: str | None = None
    gripper_size: str | None = None
    vacuum_cup_type: str | None = None
    vacuum_cup_size: str | None = None
    vacuum_cup_model: str | None = None
    vacuum_generation: str | None = None
    vacuum_circuits: int | None = Field(default=None, ge=0)
    pressure_circuits: int | None = Field(default=None, ge=0)
    interchangeable_circuits: int | None = Field(default=None, ge=0)
    external_circuits: int | None = Field(default=None, ge=0)
    pneumatic_connection: str | None = None
    pneumatic_notes: str | None = None
    electrical_present: bool | None = None
    electrical_connection: str | None = None
    electrical_pinout_reference: str | None = None
    sensor_types: str | None = None
    sensor_models: str | None = None
    command_center_data: dict[str, Any] | None = None
