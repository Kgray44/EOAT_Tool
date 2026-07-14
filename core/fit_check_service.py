from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, ToolRecord, WarningItem
from .atlas_utils import (
    display_value,
    normalized_eoat_key,
    normalized_machine_key,
    normalized_tool_key,
    row_value,
)

FitCheckStatus = Literal["compatible", "warning", "not_compatible", "insufficient_data", "invalid_input", "unknown"]
Confidence = Literal["high", "medium", "low", "unknown"]
PathStatus = Literal["confirmed", "warning", "conflict", "unknown"]
RequirementStatus = Literal["pass", "warning", "fail", "na", "unknown"]
AlternativeStatus = Literal["best", "available", "verify", "missing_data", "not_recommended", "current", "incompatible"]
EoatMode = Literal["auto", "current", "manual"]
CompatibilityStatus = Literal["pass", "fail", "unknown", "not_evaluated"]


@dataclass(frozen=True)
class FitCheckRequest:
    tool_id: str = ""
    machine_id: str = ""
    eoat_id: str = ""
    eoat_mode: EoatMode = "auto"


@dataclass(frozen=True)
class FitCheckPathSegment:
    status: PathStatus
    message: str


@dataclass(frozen=True)
class FitCheckRequirement:
    id: str
    label: str
    status: RequirementStatus
    value: str
    explanation: str = ""


@dataclass(frozen=True)
class FitCheckWarning:
    id: str
    severity: Literal["info", "warning", "critical"]
    title: str
    message: str


@dataclass(frozen=True)
class FitCheckAlternativeMachine:
    machine: MachineRecord
    status_label: str
    status: AlternativeStatus
    reason: str = ""


@dataclass(frozen=True)
class FitCheckAlternativeEOAT:
    eoat: EOATRecord
    status_label: str
    status: AlternativeStatus
    reason: str = ""


@dataclass(frozen=True)
class FitCheckAlternatives:
    machines: tuple[FitCheckAlternativeMachine, ...] = ()
    eoats: tuple[FitCheckAlternativeEOAT, ...] = ()


@dataclass(frozen=True)
class FitCheckDetails:
    tool_details: dict[str, Any] = field(default_factory=dict)
    machine_details: dict[str, Any] = field(default_factory=dict)
    eoat_details: dict[str, Any] = field(default_factory=dict)
    air_details: dict[str, Any] = field(default_factory=dict)
    sensor_details: dict[str, Any] = field(default_factory=dict)
    documentation_details: dict[str, Any] = field(default_factory=dict)
    confidence_explanation: tuple[str, ...] = ()


@dataclass(frozen=True)
class FitCheckInputValues:
    tool_id: str = ""
    machine_id: str = ""
    eoat_id: str = ""


@dataclass(frozen=True)
class FitCheckInputCompleteness:
    has_tool: bool = False
    has_machine: bool = False
    has_eoat: bool = False

    def complete(self) -> bool:
        return self.has_tool and self.has_machine and self.has_eoat


@dataclass(frozen=True)
class FitCheckValidity:
    tool_exists: bool = False
    machine_exists: bool = False
    eoat_exists: bool = False

    def valid_for_inputs(self, inputs: FitCheckInputCompleteness) -> bool:
        return (
            (not inputs.has_tool or self.tool_exists)
            and (not inputs.has_machine or self.machine_exists)
            and (not inputs.has_eoat or self.eoat_exists)
        )


@dataclass(frozen=True)
class FitCheckCompatibility:
    tool_machine: CompatibilityStatus = "not_evaluated"
    tool_eoat: CompatibilityStatus = "not_evaluated"
    machine_eoat: CompatibilityStatus = "not_evaluated"
    full_setup: CompatibilityStatus = "not_evaluated"


@dataclass(frozen=True)
class FitCheckResult:
    status: FitCheckStatus
    headline: str
    message: str
    confidence: Confidence
    selected_tool: ToolRecord | None = None
    selected_machine: MachineRecord | None = None
    selected_eoat: EOATRecord | None = None
    recommended_eoat: EOATRecord | None = None
    tool_to_eoat: FitCheckPathSegment = field(default_factory=lambda: FitCheckPathSegment("unknown", "Select a Tool and EOAT."))
    eoat_to_machine: FitCheckPathSegment = field(default_factory=lambda: FitCheckPathSegment("unknown", "Select an EOAT and Machine."))
    requirements: tuple[FitCheckRequirement, ...] = ()
    warnings: tuple[FitCheckWarning, ...] = ()
    alternatives: FitCheckAlternatives = field(default_factory=FitCheckAlternatives)
    details: FitCheckDetails = field(default_factory=FitCheckDetails)
    input_values: FitCheckInputValues = field(default_factory=FitCheckInputValues)
    input_completeness: FitCheckInputCompleteness = field(default_factory=FitCheckInputCompleteness)
    validity: FitCheckValidity = field(default_factory=FitCheckValidity)
    compatibility: FitCheckCompatibility = field(default_factory=FitCheckCompatibility)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FitCheckService:
    def __init__(self, bundle: AtlasDataBundle | None):
        self.bundle = bundle
        self._tools = {
            normalized_tool_key(record.tool): record
            for record in getattr(bundle, "tools", ()) or ()
            if normalized_tool_key(record.tool)
        }
        self._machines = {
            normalized_machine_key(record.machine): record
            for record in getattr(bundle, "machines", ()) or ()
            if normalized_machine_key(record.machine)
        }
        self._eoats = {
            normalized_eoat_key(record.eoat_id): record
            for record in getattr(bundle, "eoats", ()) or ()
            if normalized_eoat_key(record.eoat_id)
        }

    def run_fit_check(self, request: FitCheckRequest | dict[str, Any] | None = None, **kwargs: Any) -> FitCheckResult | None:
        if isinstance(request, dict):
            request = FitCheckRequest(**{**request, **kwargs})
        elif request is None:
            request = FitCheckRequest(**kwargs)
        elif kwargs:
            request = FitCheckRequest(**{**asdict(request), **kwargs})

        input_values = self._input_values(request)
        input_completeness = FitCheckInputCompleteness(
            has_tool=bool(input_values.tool_id),
            has_machine=bool(input_values.machine_id),
            has_eoat=bool(input_values.eoat_id),
        )
        tool = self._tool(input_values.tool_id)
        machine = self._machine(input_values.machine_id)
        selected_eoat = self._eoat(input_values.eoat_id)
        validity = FitCheckValidity(
            tool_exists=tool is not None,
            machine_exists=machine is not None,
            eoat_exists=selected_eoat is not None,
        )
        compatibility = self._compatibility(tool, machine, selected_eoat, input_completeness, validity)
        auto_eoat = self._best_eoat(tool, machine, None)
        recommended_eoat = auto_eoat

        if not any((input_completeness.has_tool, input_completeness.has_machine, input_completeness.has_eoat)):
            return None

        requirements = tuple(
            requirement
            for requirement in (
                self._machine_compatibility(
                    tool,
                    machine,
                    has_tool_input=input_completeness.has_tool,
                    has_machine_input=input_completeness.has_machine,
                ),
                self._eoat_compatibility(
                    tool,
                    machine,
                    selected_eoat,
                    has_eoat_input=input_completeness.has_eoat,
                    has_tool_input=input_completeness.has_tool,
                    has_machine_input=input_completeness.has_machine,
                ),
                self._robot_type_requirement(
                    machine,
                    selected_eoat,
                    has_machine_input=input_completeness.has_machine,
                    has_eoat_input=input_completeness.has_eoat,
                ),
                self._air_architecture_requirement(
                    machine,
                    selected_eoat,
                    has_machine_input=input_completeness.has_machine,
                    has_eoat_input=input_completeness.has_eoat,
                ),
                self._quick_disconnect_requirement(selected_eoat, has_eoat_input=input_completeness.has_eoat),
                self._part_count_requirement(tool, selected_eoat, has_tool_input=input_completeness.has_tool, has_eoat_input=input_completeness.has_eoat),
                self._sensor_requirement(selected_eoat, has_eoat_input=input_completeness.has_eoat),
            )
            if requirement is not None
        )
        tool_to_eoat = self._tool_to_eoat_path(tool, selected_eoat)
        eoat_to_machine = self._eoat_to_machine_path(selected_eoat, machine)
        warnings = self._warnings(
            request=request,
            tool=tool,
            machine=machine,
            selected_eoat=selected_eoat,
            recommended_eoat=recommended_eoat,
            auto_eoat=auto_eoat,
            requirements=requirements,
        )
        alternatives = self._alternatives(tool, machine, selected_eoat, auto_eoat)
        confidence, confidence_explanation = self._confidence(
            tool=tool,
            machine=machine,
            eoat=selected_eoat,
            requirements=requirements,
            warnings=warnings,
        )
        status, headline, message = self._summary(
            input_values=input_values,
            input_completeness=input_completeness,
            validity=validity,
            compatibility=compatibility,
            tool=tool,
            machine=machine,
            eoat=selected_eoat,
            recommended_eoat=recommended_eoat,
            requirements=requirements,
            warnings=warnings,
        )
        details = self._details(tool, machine, selected_eoat, confidence_explanation)
        return FitCheckResult(
            status=status,
            headline=headline,
            message=message,
            confidence=confidence,
            selected_tool=tool,
            selected_machine=machine,
            selected_eoat=selected_eoat,
            recommended_eoat=recommended_eoat,
            tool_to_eoat=tool_to_eoat,
            eoat_to_machine=eoat_to_machine,
            requirements=requirements,
            warnings=warnings,
            alternatives=alternatives,
            details=details,
            input_values=input_values,
            input_completeness=input_completeness,
            validity=validity,
            compatibility=compatibility,
        )

    def _tool(self, value: str) -> ToolRecord | None:
        return self._tools.get(normalized_tool_key(value))

    def _machine(self, value: str) -> MachineRecord | None:
        return self._machines.get(normalized_machine_key(value))

    def _eoat(self, value: str) -> EOATRecord | None:
        return self._eoats.get(normalized_eoat_key(value))

    def _input_values(self, request: FitCheckRequest) -> FitCheckInputValues:
        tool_id = display_value(request.tool_id)
        machine_id = display_value(request.machine_id)
        eoat_id = display_value(request.eoat_id)
        if request.eoat_mode == "current" and not eoat_id:
            machine = self._machine(machine_id)
            if machine is not None:
                eoat_id = display_value(getattr(machine, "current_eoat", ""))
        return FitCheckInputValues(tool_id=tool_id, machine_id=machine_id, eoat_id=eoat_id)

    def _request_eoat(self, request: FitCheckRequest, machine: MachineRecord | None) -> EOATRecord | None:
        if request.eoat_mode == "manual":
            return self._eoat(request.eoat_id)
        if request.eoat_mode == "current" and machine is not None:
            current = display_value(getattr(machine, "current_eoat", ""))
            return self._eoat(current)
        if request.eoat_id:
            return self._eoat(request.eoat_id)
        return None

    def _best_eoat(
        self,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        selected_eoat: EOATRecord | None = None,
    ) -> EOATRecord | None:
        candidates: dict[str, EOATRecord] = {}
        if selected_eoat is not None:
            candidates[normalized_eoat_key(selected_eoat.eoat_id)] = selected_eoat
        if tool is not None and machine is not None:
            tool_eoats = tuple(getattr(tool, "compatible_eoats", ()) or ())
            machine_eoats = tuple(getattr(machine, "compatible_eoats", ()) or ())
            for eoat_id in tool_eoats:
                if not _contains_eoat(machine_eoats, eoat_id):
                    continue
                record = self._eoat(eoat_id)
                if record is not None:
                    candidates[normalized_eoat_key(record.eoat_id)] = record
            if selected_eoat is None:
                return self._top_scored_eoat(candidates, tool, machine, selected_eoat)
        elif tool is not None:
            for eoat_id in getattr(tool, "compatible_eoats", ()) or ():
                record = self._eoat(eoat_id)
                if record is not None:
                    candidates[normalized_eoat_key(record.eoat_id)] = record
        elif machine is not None:
            for eoat_id in getattr(machine, "compatible_eoats", ()) or ():
                record = self._eoat(eoat_id)
                if record is not None:
                    candidates[normalized_eoat_key(record.eoat_id)] = record
        return self._top_scored_eoat(candidates, tool, machine, selected_eoat)

    def _top_scored_eoat(
        self,
        candidates: dict[str, EOATRecord],
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        selected_eoat: EOATRecord | None,
    ) -> EOATRecord | None:
        if not candidates:
            return None
        scored = [(self._eoat_score(record, tool, machine, selected_eoat), record.eoat_id.casefold(), record) for record in candidates.values()]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

    def _eoat_score(
        self,
        eoat: EOATRecord,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        selected_eoat: EOATRecord | None,
    ) -> int:
        score = 0
        if selected_eoat is not None and normalized_eoat_key(eoat.eoat_id) == normalized_eoat_key(selected_eoat.eoat_id):
            score += 5
        if tool is not None and _record_supports_tool(eoat, tool):
            score += 65
        if machine is not None and _record_supports_machine(eoat, machine):
            score += 65
        if machine is not None and normalized_eoat_key(getattr(machine, "current_eoat", "")) == normalized_eoat_key(eoat.eoat_id):
            score += 18
        score += min(8, _documentation_score(eoat) // 12)
        if display_value(getattr(eoat, "eoat_type", "")):
            score += 4
        if _last_audit(eoat):
            score += 4
        return score

    def _machine_compatibility(
        self,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        *,
        has_tool_input: bool = False,
        has_machine_input: bool = False,
    ) -> FitCheckRequirement | None:
        if has_tool_input and tool is None:
            return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "fail", "Invalid Tool")
        if has_machine_input and machine is None:
            return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "fail", "Invalid Machine")
        if tool is None and machine is None:
            return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "unknown", "Select Tool + Machine")
        if tool is None:
            return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "unknown", "Select Tool")
        if machine is None:
            return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "unknown", "Select Machine")
        if _record_supports_machine(tool, machine) or _machine_supports_tool(machine, tool):
            return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "pass", "Confirmed")
        if not getattr(tool, "compatible_machines", ()) and not getattr(machine, "compatible_tools", ()):
            return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "unknown", "Missing Data")
        return FitCheckRequirement("machine_compatibility", "Machine Fit Check", "fail", "Conflict")

    def _eoat_compatibility(
        self,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        eoat: EOATRecord | None,
        *,
        has_eoat_input: bool = False,
        has_tool_input: bool = False,
        has_machine_input: bool = False,
    ) -> FitCheckRequirement | None:
        if has_eoat_input and eoat is None:
            return FitCheckRequirement("eoat_compatibility", "EOAT Fit Check", "fail", "Invalid EOAT")
        if has_tool_input and tool is None:
            return FitCheckRequirement("eoat_compatibility", "EOAT Fit Check", "fail", "Invalid Tool")
        if has_machine_input and machine is None:
            return FitCheckRequirement("eoat_compatibility", "EOAT Fit Check", "fail", "Invalid Machine")
        if eoat is None:
            return FitCheckRequirement("eoat_compatibility", "EOAT Fit Check", "unknown", "Select EOAT")
        statuses = []
        if tool is not None:
            statuses.append(_record_supports_tool(eoat, tool) or _tool_supports_eoat(tool, eoat))
        if machine is not None:
            statuses.append(_record_supports_machine(eoat, machine) or _machine_supports_eoat(machine, eoat))
        if statuses and all(statuses):
            return FitCheckRequirement("eoat_compatibility", "EOAT Fit Check", "pass", "Confirmed")
        if statuses and any(status is False for status in statuses):
            return FitCheckRequirement("eoat_compatibility", "EOAT Fit Check", "fail", "Mismatch")
        return FitCheckRequirement("eoat_compatibility", "EOAT Fit Check", "warning", "Verify")

    def _robot_type_requirement(
        self,
        machine: MachineRecord | None,
        eoat: EOATRecord | None,
        *,
        has_machine_input: bool = False,
        has_eoat_input: bool = False,
    ) -> FitCheckRequirement | None:
        if has_machine_input and machine is None:
            return FitCheckRequirement("robot_type", "Robot Type", "fail", "Invalid Machine")
        if has_eoat_input and eoat is None:
            return FitCheckRequirement("robot_type", "Robot Type", "fail", "Invalid EOAT")
        if machine is None and eoat is None:
            return FitCheckRequirement("robot_type", "Robot Type", "unknown", "Missing Context")
        if machine is None:
            return FitCheckRequirement("robot_type", "Robot Type", "unknown", "Select Machine")
        if eoat is None:
            return FitCheckRequirement("robot_type", "Robot Type", "unknown", "Select EOAT")
        robot_text = " ".join(
            value
            for value in (
                display_value(getattr(machine, "robot_type", "")),
                display_value(getattr(machine, "robot_model", "")),
                display_value(getattr(machine, "controller", "")),
            )
            if value
        )
        eoat_types = tuple(display_value(value) for value in getattr(eoat, "robot_types", ()) or () if display_value(value))
        eoat_models = tuple(display_value(value) for value in getattr(eoat, "robot_models", ()) or () if display_value(value))
        if not robot_text and not eoat_types and not eoat_models:
            return FitCheckRequirement("robot_type", "Robot Type", "unknown", "Missing Data")
        if not eoat_types and not eoat_models:
            return FitCheckRequirement("robot_type", "Robot Type", "warning", "Verify")
        haystack = robot_text.casefold()
        if any(_token_overlap(value, haystack) for value in (*eoat_types, *eoat_models)):
            return FitCheckRequirement("robot_type", "Robot Type", "pass", "Match")
        if not robot_text:
            return FitCheckRequirement("robot_type", "Robot Type", "warning", "Machine Missing")
        return FitCheckRequirement("robot_type", "Robot Type", "fail", "Mismatch")

    def _air_architecture_requirement(
        self,
        machine: MachineRecord | None,
        eoat: EOATRecord | None,
        *,
        has_machine_input: bool = False,
        has_eoat_input: bool = False,
    ) -> FitCheckRequirement | None:
        if has_machine_input and machine is None:
            return FitCheckRequirement("air_architecture", "Air Architecture", "fail", "Invalid Machine")
        if has_eoat_input and eoat is None:
            return FitCheckRequirement("air_architecture", "Air Architecture", "fail", "Invalid EOAT")
        if eoat is None:
            return FitCheckRequirement("air_architecture", "Air Architecture", "unknown", "Select EOAT")
        eoat_air = _air_blob(eoat)
        machine_air = _machine_air_blob(machine) if machine is not None else ""
        requires_external = "external" in eoat_air
        requires_vacuum = "vacuum" in eoat_air or "# of cups" in eoat_air or "cup" in eoat_air
        requires_pressure = "pressure" in eoat_air or "cylinder" in eoat_air or "gripper" in eoat_air
        if not eoat_air:
            return FitCheckRequirement("air_architecture", "Air Architecture", "unknown", "Missing Data")
        if machine is None:
            return FitCheckRequirement("air_architecture", "Air Architecture", "warning", "Select Machine")
        if requires_external and machine_air and _has_negative_external_air(machine_air):
            return FitCheckRequirement("air_architecture", "Air Architecture", "fail", "External Circuit Missing")
        if requires_external:
            return FitCheckRequirement("air_architecture", "Air Architecture", "warning", "External Circuit")
        if not machine_air and (requires_vacuum or requires_pressure):
            return FitCheckRequirement("air_architecture", "Air Architecture", "warning", "Verify Air")
        return FitCheckRequirement("air_architecture", "Air Architecture", "pass", "Supported")

    def _quick_disconnect_requirement(self, eoat: EOATRecord | None, *, has_eoat_input: bool = False) -> FitCheckRequirement | None:
        if has_eoat_input and eoat is None:
            return FitCheckRequirement("quick_disconnect", "Pneumatic Quick Disconnect", "fail", "Invalid EOAT")
        if eoat is None:
            return FitCheckRequirement("quick_disconnect", "Pneumatic Quick Disconnect", "unknown", "Select EOAT")
        text = " ".join(
            (
                display_value(getattr(eoat, "connection_type", "")),
                _rows_blob(getattr(eoat, "source_rows", ()) or ()),
            )
        ).casefold()
        if "quick disconnect" not in text and "qd" not in text:
            return FitCheckRequirement("quick_disconnect", "Pneumatic Quick Disconnect", "na", "Not Required")
        if any(token in text for token in ("none", "missing", "no quick", "not present")):
            return FitCheckRequirement("quick_disconnect", "Pneumatic Quick Disconnect", "fail", "Missing")
        if "pneumatic" in text or "quick disconnect" in text or "qd" in text:
            return FitCheckRequirement("quick_disconnect", "Pneumatic Quick Disconnect", "pass", "Confirmed")
        return FitCheckRequirement("quick_disconnect", "Pneumatic Quick Disconnect", "warning", "Verify")

    def _part_count_requirement(
        self,
        tool: ToolRecord | None,
        eoat: EOATRecord | None,
        *,
        has_tool_input: bool = False,
        has_eoat_input: bool = False,
    ) -> FitCheckRequirement | None:
        if has_eoat_input and eoat is None:
            return FitCheckRequirement("part_count", "Part Count", "fail", "Invalid EOAT")
        if has_tool_input and tool is None:
            return FitCheckRequirement("part_count", "Part Count", "fail", "Invalid Tool")
        if eoat is None:
            return FitCheckRequirement("part_count", "Part Count", "unknown", "Select EOAT")
        eoat_count = _parts_picked(eoat)
        tool_count = _parts_picked(tool) if tool is not None else 0
        if eoat_count and tool_count:
            if eoat_count == tool_count:
                return FitCheckRequirement("part_count", "Part Count", "pass", f"Match ({eoat_count} parts)")
            return FitCheckRequirement("part_count", "Part Count", "fail", f"Mismatch ({eoat_count} vs {tool_count})")
        if eoat_count:
            return FitCheckRequirement("part_count", "Part Count", "pass", f"Indexed ({eoat_count} parts)")
        if getattr(eoat, "parts", ()):
            return FitCheckRequirement("part_count", "Part Count", "pass", f"Indexed ({len(getattr(eoat, 'parts', ()))} parts)")
        return FitCheckRequirement("part_count", "Part Count", "warning", "Verify")

    def _sensor_requirement(self, eoat: EOATRecord | None, *, has_eoat_input: bool = False) -> FitCheckRequirement | None:
        if has_eoat_input and eoat is None:
            return FitCheckRequirement("sensor_requirements", "Sensor Requirements", "fail", "Invalid EOAT")
        if eoat is None:
            return FitCheckRequirement("sensor_requirements", "Sensor Requirements", "unknown", "Select EOAT")
        sensor_text = display_value(getattr(eoat, "sensor_info", ""))
        folded = sensor_text.casefold()
        if not sensor_text:
            return FitCheckRequirement("sensor_requirements", "Sensor Requirements", "na", "Not Required")
        if any(token in folded for token in ("yes", "present", "part-present", "vacuum confirmation", "sensor type")):
            return FitCheckRequirement("sensor_requirements", "Sensor Requirements", "pass", "Confirmed")
        if any(token in folded for token in ("no", "not required", "none")):
            return FitCheckRequirement("sensor_requirements", "Sensor Requirements", "na", "Not Required")
        return FitCheckRequirement("sensor_requirements", "Sensor Requirements", "warning", "Verify")

    def _tool_to_eoat_path(self, tool: ToolRecord | None, eoat: EOATRecord | None) -> FitCheckPathSegment:
        if tool is None or eoat is None:
            return FitCheckPathSegment("unknown", "Select Tool + EOAT.")
        if _record_supports_tool(eoat, tool) or _tool_supports_eoat(tool, eoat):
            return FitCheckPathSegment("confirmed", "Tool and EOAT relationship is confirmed.")
        if not getattr(tool, "compatible_eoats", ()) and not getattr(eoat, "tools", ()):
            return FitCheckPathSegment("unknown", "Tool-to-EOAT relationship is not indexed.")
        return FitCheckPathSegment("conflict", "EOAT is not confirmed for this Tool.")

    def _eoat_to_machine_path(self, eoat: EOATRecord | None, machine: MachineRecord | None) -> FitCheckPathSegment:
        if eoat is None or machine is None:
            return FitCheckPathSegment("unknown", "Select EOAT + Machine.")
        if _record_supports_machine(eoat, machine) or _machine_supports_eoat(machine, eoat):
            return FitCheckPathSegment("confirmed", "EOAT and Machine relationship is confirmed.")
        if not getattr(machine, "compatible_eoats", ()) and not getattr(eoat, "machines", ()):
            return FitCheckPathSegment("unknown", "EOAT-to-Machine relationship is not indexed.")
        return FitCheckPathSegment("conflict", "EOAT is not confirmed for this Machine.")

    def _warnings(
        self,
        *,
        request: FitCheckRequest,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        selected_eoat: EOATRecord | None,
        recommended_eoat: EOATRecord | None,
        auto_eoat: EOATRecord | None,
        requirements: tuple[FitCheckRequirement, ...],
    ) -> tuple[FitCheckWarning, ...]:
        warnings: list[FitCheckWarning] = []
        add = _WarningAccumulator(warnings)
        if request.eoat_mode == "current" and machine is not None and selected_eoat is None:
            add("current-eoat-missing", "warning", f"Current EOAT on Machine {machine.machine} is Not Indexed", "Verify before setup.")
        if machine is not None and selected_eoat is not None and auto_eoat is not None:
            current = display_value(getattr(machine, "current_eoat", ""))
            if current and normalized_eoat_key(current) != normalized_eoat_key(auto_eoat.eoat_id):
                add(
                    "current-eoat-differs",
                    "warning",
                    "Current EOAT differs from recommended EOAT",
                    f"Machine {machine.machine} currently lists {current}.",
                )
        if tool is not None and machine is not None and recommended_eoat is None:
            add("no-eoat-found", "critical", "No confirmed EOAT supports this setup", "Review the Library relationships before setup.")
        possible_eoats = self._candidate_eoats_for(tool, machine)
        if len(possible_eoats) > 1 and selected_eoat is not None:
            add("multiple-eoats", "info", "Multiple possible EOATs", f"{len(possible_eoats)} EOAT options are indexed for this context.")
        for requirement in requirements:
            if requirement.status == "fail":
                add(f"requirement-{requirement.id}", "critical", f"{requirement.label} conflict", requirement.explanation or requirement.value)
            elif requirement.status == "warning":
                add(f"requirement-{requirement.id}", "warning", f"{requirement.label} needs verification", requirement.explanation or requirement.value)
        for record in (tool, machine, selected_eoat):
            if record is None:
                continue
            for warning in getattr(record, "warnings", ()) or ():
                if not _is_setup_warning(warning):
                    continue
                severity = "critical" if str(warning.severity).casefold() in {"critical", "error"} else "warning"
                add(f"record-{id(record)}-{warning.title}", severity, warning.title, warning.message)
        if selected_eoat is not None:
            if _has_real_known_issue(getattr(selected_eoat, "known_issues", "")):
                add("known-eoat-issue", "warning", "Known issue noted", getattr(selected_eoat, "known_issues", ""))
        if machine is not None and not display_value(getattr(machine, "robot_type", "")) and not display_value(getattr(machine, "robot_model", "")):
            add("missing-machine-robot", "warning", "Machine robot model missing", "Robot compatibility cannot be fully verified.")
        if selected_eoat is not None and not display_value(getattr(selected_eoat, "eoat_type", "")):
            add("missing-eoat-type", "warning", "EOAT type missing", "EOAT type should be indexed for setup decisions.")
        return tuple(warnings)

    def _candidate_eoats_for(self, tool: ToolRecord | None, machine: MachineRecord | None) -> tuple[EOATRecord, ...]:
        keys: list[str] = []
        if tool is not None:
            keys.extend(getattr(tool, "compatible_eoats", ()) or ())
        if machine is not None:
            machine_keys = list(getattr(machine, "compatible_eoats", ()) or ())
            keys = [key for key in keys if _contains_eoat(machine_keys, key)] if keys else machine_keys
        records = [self._eoat(key) for key in dict.fromkeys(keys)]
        return tuple(record for record in records if record is not None)

    def _alternatives(
        self,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        selected_eoat: EOATRecord | None,
        best_eoat: EOATRecord | None,
    ) -> FitCheckAlternatives:
        machines: list[FitCheckAlternativeMachine] = []
        eoats: list[FitCheckAlternativeEOAT] = []
        seen_machines: set[str] = set()
        seen_eoats: set[str] = set()

        machine_candidates: list[MachineRecord] = []
        if tool is not None:
            machine_candidates.extend(record for key in getattr(tool, "compatible_machines", ()) or () if (record := self._machine(key)))
        eoat_context = selected_eoat or best_eoat
        if eoat_context is not None:
            machine_candidates.extend(record for key in getattr(eoat_context, "machines", ()) or () if (record := self._machine(key)))
        if machine is not None:
            machine_candidates.insert(0, machine)
        machine_records: list[MachineRecord] = []
        for candidate in machine_candidates:
            key = normalized_machine_key(candidate.machine)
            if not key or key in seen_machines:
                continue
            seen_machines.add(key)
            machine_records.append(candidate)
        best_machine_key = self._best_machine_key(machine_records, selected_machine=machine, tool=tool, eoat=eoat_context)
        for candidate in machine_records:
            label, status, reason = self._machine_alt_status(candidate, machine, tool, eoat_context, best_machine_key)
            machines.append(FitCheckAlternativeMachine(candidate, label, status, reason))

        eoat_candidates: list[EOATRecord] = []
        if tool is not None:
            eoat_candidates.extend(record for key in getattr(tool, "compatible_eoats", ()) or () if (record := self._eoat(key)))
        if machine is not None:
            eoat_candidates.extend(record for key in getattr(machine, "compatible_eoats", ()) or () if (record := self._eoat(key)))
        if best_eoat is not None:
            eoat_candidates.insert(0, best_eoat)
        if selected_eoat is not None:
            eoat_candidates.insert(0, selected_eoat)
        eoat_records: list[EOATRecord] = []
        for candidate in eoat_candidates:
            key = normalized_eoat_key(candidate.eoat_id)
            if not key or key in seen_eoats:
                continue
            seen_eoats.add(key)
            eoat_records.append(candidate)
        best_eoat_key = ""
        if best_eoat is not None and self._eoat_is_compatible(best_eoat, tool, machine):
            best_eoat_key = normalized_eoat_key(best_eoat.eoat_id)
        for candidate in eoat_records:
            label, status, reason = self._eoat_alt_status(candidate, selected_eoat, best_eoat_key, tool, machine)
            eoats.append(FitCheckAlternativeEOAT(candidate, label, status, reason))

        selected_machine_key = normalized_machine_key(getattr(machine, "machine", ""))
        selected_eoat_key = normalized_eoat_key(getattr(selected_eoat, "eoat_id", ""))
        machines.sort(
            key=lambda item: (
                0 if selected_machine_key and normalized_machine_key(item.machine.machine) == selected_machine_key else 1,
                _alternative_rank(item.status),
                _machine_sort_key(item.machine.machine),
            )
        )
        eoats.sort(
            key=lambda item: (
                0 if selected_eoat_key and normalized_eoat_key(item.eoat.eoat_id) == selected_eoat_key else 1,
                _alternative_rank(item.status),
                item.eoat.eoat_id.casefold(),
            )
        )
        return FitCheckAlternatives(tuple(machines[:12]), tuple(eoats[:12]))

    def _best_machine_key(
        self,
        candidates: list[MachineRecord],
        *,
        selected_machine: MachineRecord | None,
        tool: ToolRecord | None,
        eoat: EOATRecord | None,
    ) -> str:
        selected_key = normalized_machine_key(getattr(selected_machine, "machine", ""))
        compatible = [
            candidate
            for candidate in candidates
            if self._machine_is_compatible(candidate, tool, eoat)
            and normalized_machine_key(candidate.machine) != selected_key
        ]
        compatible.sort(key=lambda candidate: _machine_sort_key(candidate.machine))
        return normalized_machine_key(compatible[0].machine) if compatible else ""

    def _machine_alt_status(
        self,
        candidate: MachineRecord,
        selected_machine: MachineRecord | None,
        tool: ToolRecord | None,
        eoat: EOATRecord | None,
        best_machine_key: str,
    ) -> tuple[str, AlternativeStatus, str]:
        candidate_key = normalized_machine_key(candidate.machine)
        is_selected = selected_machine is not None and candidate_key == normalized_machine_key(selected_machine.machine)
        supports_tool, supports_eoat = self._machine_support_flags(candidate, tool, eoat)
        is_compatible = supports_tool and supports_eoat
        if is_selected and not is_compatible:
            return "Incompatible", "incompatible", "Selected machine conflicts with the setup context"
        if is_selected and is_compatible:
            return "Current", "current", "Selected machine"
        if candidate_key and candidate_key == best_machine_key and is_compatible:
            return "Best Match", "best", "Strongest compatible machine for current context"
        if is_compatible:
            return "Available", "available", "Supports selected setup context"
        if not getattr(candidate, "compatible_eoats", ()) and not getattr(candidate, "compatible_tools", ()):
            return "Missing Data", "missing_data", "Machine compatibility data is incomplete"
        if tool is not None and eoat is not None:
            return "Incompatible", "incompatible", "Machine is not compatible with the selected context"
        if supports_tool:
            return "Verify EOAT", "verify", "Tool relationship is indexed; EOAT relationship needs verification"
        if supports_eoat:
            return "Verify Tool", "verify", "EOAT relationship is indexed; Tool relationship needs verification"
        return "Incompatible", "incompatible", "Machine is not compatible with the selected context"

    def _eoat_alt_status(
        self,
        candidate: EOATRecord,
        selected_eoat: EOATRecord | None,
        best_eoat_key: str,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
    ) -> tuple[str, AlternativeStatus, str]:
        candidate_key = normalized_eoat_key(candidate.eoat_id)
        is_selected = selected_eoat is not None and candidate_key == normalized_eoat_key(selected_eoat.eoat_id)
        supports_tool, supports_machine = self._eoat_support_flags(candidate, tool, machine)
        is_compatible = supports_tool and supports_machine
        if is_selected and not is_compatible:
            return "Incompatible", "incompatible", "Selected EOAT conflicts with the setup context"
        if is_selected and is_compatible:
            return "Current", "current", "Selected EOAT"
        if candidate_key and candidate_key == best_eoat_key and is_compatible:
            return "Best Match", "best", "Highest ranked compatible EOAT for current context"
        if is_compatible:
            return "Available", "available", "Supports selected setup context"
        if not getattr(candidate, "tools", ()) and not getattr(candidate, "machines", ()):
            return "Missing Data", "missing_data", "EOAT relationship data is incomplete"
        if tool is not None and machine is not None:
            return "Incompatible", "incompatible", "EOAT is not compatible with the selected context"
        if supports_tool:
            return "Verify Machine", "verify", "Tool relationship is indexed; machine relationship needs verification"
        if supports_machine:
            return "Verify Tool", "verify", "Machine relationship is indexed; Tool relationship needs verification"
        return "Incompatible", "incompatible", "EOAT is not compatible with the selected context"

    def _machine_support_flags(
        self,
        candidate: MachineRecord,
        tool: ToolRecord | None,
        eoat: EOATRecord | None,
    ) -> tuple[bool, bool]:
        supports_tool = tool is None or _machine_supports_tool(candidate, tool) or _record_supports_machine(tool, candidate)
        supports_eoat = eoat is None or _machine_supports_eoat(candidate, eoat) or _record_supports_machine(eoat, candidate)
        return supports_tool, supports_eoat

    def _machine_is_compatible(
        self,
        candidate: MachineRecord,
        tool: ToolRecord | None,
        eoat: EOATRecord | None,
    ) -> bool:
        supports_tool, supports_eoat = self._machine_support_flags(candidate, tool, eoat)
        return supports_tool and supports_eoat

    def _eoat_support_flags(
        self,
        candidate: EOATRecord,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
    ) -> tuple[bool, bool]:
        supports_tool = tool is None or _record_supports_tool(candidate, tool) or _tool_supports_eoat(tool, candidate)
        supports_machine = machine is None or _record_supports_machine(candidate, machine) or _machine_supports_eoat(machine, candidate)
        return supports_tool, supports_machine

    def _eoat_is_compatible(
        self,
        candidate: EOATRecord,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
    ) -> bool:
        supports_tool, supports_machine = self._eoat_support_flags(candidate, tool, machine)
        return supports_tool and supports_machine

    def _compatibility(
        self,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        eoat: EOATRecord | None,
        input_completeness: FitCheckInputCompleteness,
        validity: FitCheckValidity,
    ) -> FitCheckCompatibility:
        if not input_completeness.complete() or not validity.valid_for_inputs(input_completeness):
            return FitCheckCompatibility()
        tool_machine = self._tool_machine_status(tool, machine)
        tool_eoat = self._tool_eoat_status(tool, eoat)
        machine_eoat = self._machine_eoat_status(machine, eoat)
        pair_statuses = (tool_machine, tool_eoat, machine_eoat)
        if any(status == "fail" for status in pair_statuses):
            full_setup: CompatibilityStatus = "fail"
        elif any(status == "unknown" for status in pair_statuses):
            full_setup = "unknown"
        elif all(status == "pass" for status in pair_statuses):
            full_setup = "pass"
        else:
            full_setup = "not_evaluated"
        return FitCheckCompatibility(
            tool_machine=tool_machine,
            tool_eoat=tool_eoat,
            machine_eoat=machine_eoat,
            full_setup=full_setup,
        )

    def _tool_machine_status(self, tool: ToolRecord | None, machine: MachineRecord | None) -> CompatibilityStatus:
        if tool is None or machine is None:
            return "not_evaluated"
        if _record_supports_machine(tool, machine) or _machine_supports_tool(machine, tool):
            return "pass"
        if not getattr(tool, "compatible_machines", ()) and not getattr(machine, "compatible_tools", ()):
            return "unknown"
        return "fail"

    def _tool_eoat_status(self, tool: ToolRecord | None, eoat: EOATRecord | None) -> CompatibilityStatus:
        if tool is None or eoat is None:
            return "not_evaluated"
        if _record_supports_tool(eoat, tool) or _tool_supports_eoat(tool, eoat):
            return "pass"
        if not getattr(tool, "compatible_eoats", ()) and not getattr(eoat, "tools", ()):
            return "unknown"
        return "fail"

    def _machine_eoat_status(self, machine: MachineRecord | None, eoat: EOATRecord | None) -> CompatibilityStatus:
        if machine is None or eoat is None:
            return "not_evaluated"
        if _record_supports_machine(eoat, machine) or _machine_supports_eoat(machine, eoat):
            return "pass"
        if not getattr(machine, "compatible_eoats", ()) and not getattr(eoat, "machines", ()):
            return "unknown"
        return "fail"

    def _confidence(
        self,
        *,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        eoat: EOATRecord | None,
        requirements: tuple[FitCheckRequirement, ...],
        warnings: tuple[FitCheckWarning, ...],
    ) -> tuple[Confidence, tuple[str, ...]]:
        reasons: list[str] = []
        if tool is None or machine is None or eoat is None:
            return "unknown", ("Select Tool, Machine, and EOAT context for confidence scoring.",)
        direct = (
            (_record_supports_machine(tool, machine) or _machine_supports_tool(machine, tool))
            and (_record_supports_tool(eoat, tool) or _tool_supports_eoat(tool, eoat))
            and (_record_supports_machine(eoat, machine) or _machine_supports_eoat(machine, eoat))
        )
        if direct:
            reasons.append("Tool, Machine, and EOAT relationships are directly indexed.")
        else:
            reasons.append("One or more setup relationships are inferred or missing.")
        if any(requirement.status == "fail" for requirement in requirements):
            return "low", tuple(reasons)
        critical_or_many = any(warning.severity == "critical" for warning in warnings) or len(warnings) >= 3
        setup_uncertain = any(requirement.status in {"warning", "unknown"} for requirement in requirements)
        if direct and not critical_or_many and not setup_uncertain:
            return "high", tuple(reasons)
        if direct and not any(requirement.status == "fail" for requirement in requirements):
            return "medium", tuple(reasons)
        return "low", tuple(reasons)

    def _summary(
        self,
        *,
        input_values: FitCheckInputValues,
        input_completeness: FitCheckInputCompleteness,
        validity: FitCheckValidity,
        compatibility: FitCheckCompatibility,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        eoat: EOATRecord | None,
        recommended_eoat: EOATRecord | None,
        requirements: tuple[FitCheckRequirement, ...],
        warnings: tuple[FitCheckWarning, ...],
    ) -> tuple[FitCheckStatus, str, str]:
        if not input_completeness.complete():
            missing = []
            if not input_completeness.has_tool:
                missing.append("Tool")
            if not input_completeness.has_machine:
                missing.append("Machine")
            if not input_completeness.has_eoat:
                missing.append("EOAT")
            if len(missing) == 1:
                return "insufficient_data", "Insufficient Data", f"Select a {missing[0]} to complete validation."
            return "insufficient_data", "Insufficient Data", f"Select {' + '.join(missing)} to complete validation."

        invalid = []
        if input_completeness.has_tool and not validity.tool_exists:
            invalid.append(f"Tool {input_values.tool_id}")
        if input_completeness.has_machine and not validity.machine_exists:
            invalid.append(f"Machine {input_values.machine_id}")
        if input_completeness.has_eoat and not validity.eoat_exists:
            invalid.append(f"EOAT {input_values.eoat_id}")
        if invalid:
            return "invalid_input", "Invalid Input", f"{'; '.join(invalid)} is not indexed in the loaded Atlas dataset."

        if compatibility.full_setup == "fail":
            if compatibility.tool_machine == "pass" and (compatibility.tool_eoat == "fail" or compatibility.machine_eoat == "fail"):
                return (
                    "not_compatible",
                    "Not Compatible",
                    f"Tool {tool.tool} and Machine {machine.machine} are compatible, but EOAT {eoat.eoat_id} is not compatible with this setup.",
                )
            return "not_compatible", "Not Compatible", "The selected Tool, Machine, and EOAT combination is not compatible."
        if compatibility.full_setup == "unknown":
            return "unknown", "Needs Review", "Atlas cannot confirm compatibility because relationship data is incomplete."
        if any(requirement.status == "fail" for requirement in requirements):
            return "not_compatible", "Not Compatible", "This setup is not confirmed as compatible."
        if warnings or any(requirement.status == "warning" for requirement in requirements):
            return "warning", "Compatible with setup warnings", "This setup appears compatible, but has setup warnings to review."
        return "compatible", "Compatible", "This setup is compatible and ready to run."

    def _details(
        self,
        tool: ToolRecord | None,
        machine: MachineRecord | None,
        eoat: EOATRecord | None,
        confidence_explanation: tuple[str, ...],
    ) -> FitCheckDetails:
        return FitCheckDetails(
            tool_details=_tool_details(tool),
            machine_details=_machine_details(machine),
            eoat_details=_eoat_details(eoat),
            air_details={
                "eoat_air": _air_blob(eoat),
                "machine_air": _machine_air_blob(machine),
                "external_air_required": "external" in _air_blob(eoat),
            },
            sensor_details={"sensor_summary": display_value(getattr(eoat, "sensor_info", "")) if eoat is not None else ""},
            documentation_details={
                "tool_documentation_score": _documentation_score(tool),
                "machine_documentation_score": _documentation_score(machine),
                "eoat_documentation_score": _documentation_score(eoat),
                "eoat_photo_count": _photo_count(eoat),
                "tool_last_audit": _last_audit(tool),
                "machine_last_audit": _last_audit(machine),
                "eoat_last_audit": _last_audit(eoat),
                "data_quality_notes": _documentation_notes(tool, machine, eoat),
            },
            confidence_explanation=confidence_explanation,
        )


def run_fit_check(
    bundle: AtlasDataBundle | None,
    request: FitCheckRequest | dict[str, Any] | None = None,
    **kwargs: Any,
) -> FitCheckResult | None:
    return FitCheckService(bundle).run_fit_check(request, **kwargs)


class _WarningAccumulator:
    def __init__(self, warnings: list[FitCheckWarning]):
        self.warnings = warnings
        self.seen: set[str] = set()

    def __call__(self, warning_id: str, severity: str, title: str, message: str) -> None:
        key = re.sub(r"\W+", "-", str(warning_id or title).casefold()).strip("-")
        if not key or key in self.seen:
            return
        self.seen.add(key)
        safe_severity = "critical" if severity == "critical" else ("info" if severity == "info" else "warning")
        self.warnings.append(FitCheckWarning(key, safe_severity, str(title or "").strip(), str(message or "").strip()))


def _record_supports_tool(record: EOATRecord, tool: ToolRecord) -> bool:
    return _contains_tool(getattr(record, "tools", ()) or (), tool.tool)


def _tool_supports_eoat(tool: ToolRecord, eoat: EOATRecord) -> bool:
    return _contains_eoat(getattr(tool, "compatible_eoats", ()) or (), eoat.eoat_id)


def _record_supports_machine(record: EOATRecord | ToolRecord, machine: MachineRecord) -> bool:
    keys = getattr(record, "machines", None)
    if keys is None:
        keys = getattr(record, "compatible_machines", ()) or ()
    return _contains_machine(keys or (), machine.machine)


def _machine_supports_tool(machine: MachineRecord, tool: ToolRecord) -> bool:
    return _contains_tool(getattr(machine, "compatible_tools", ()) or (), tool.tool)


def _machine_supports_eoat(machine: MachineRecord, eoat: EOATRecord) -> bool:
    return _contains_eoat(getattr(machine, "compatible_eoats", ()) or (), eoat.eoat_id)


def _contains_tool(values: Any, target: str) -> bool:
    key = normalized_tool_key(target)
    return bool(key and any(normalized_tool_key(value) == key for value in values or ()))


def _contains_machine(values: Any, target: str) -> bool:
    key = normalized_machine_key(target)
    return bool(key and any(normalized_machine_key(value) == key for value in values or ()))


def _contains_eoat(values: Any, target: str) -> bool:
    key = normalized_eoat_key(target)
    return bool(key and any(normalized_eoat_key(value) == key for value in values or ()))


def _rows_blob(rows: Any) -> str:
    pieces: list[str] = []
    for row in rows or ():
        if isinstance(row, dict):
            pieces.extend(display_value(value) for value in row.values() if display_value(value))
    return " ".join(pieces)


def _first_row_value(record: Any, *aliases: str) -> str:
    for row in getattr(record, "source_rows", ()) or ():
        if isinstance(row, dict):
            value = row_value(row, aliases)
            if value:
                return value
    return ""


def _last_audit(record: Any) -> str:
    if record is None:
        return ""
    direct = _first_row_value(record, "Audit Date", "Last Audit Date", "Last Audit", "Date")
    if direct:
        return direct
    audit_ids = getattr(record, "audit_ids", ()) or ()
    return display_value(audit_ids[0]) if audit_ids else ""


def _documentation_score(record: Any) -> int:
    if record is None:
        return 0
    documentation = getattr(record, "documentation", None)
    if documentation is not None:
        return int(getattr(documentation, "score", 0) or 0)
    return int(getattr(record, "documentation_score", 0) or 0)


def _photo_count(record: Any) -> int:
    if record is None:
        return 0
    return int(getattr(record, "photo_count", 0) or 0)


def _has_real_known_issue(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", display_value(value).casefold()).strip()
    return bool(
        normalized
        and normalized
        not in {
            "no",
            "none",
            "n a",
            "na",
            "unknown",
            "not checked",
            "unknown not checked",
            "unchecked",
            "not indexed",
            "not available",
            "no issues observed",
        }
    )


def _is_setup_warning(warning: WarningItem) -> bool:
    title = display_value(getattr(warning, "title", "")).casefold()
    message = display_value(getattr(warning, "message", "")).casefold()
    source = display_value(getattr(warning, "source", "")).casefold()
    blob = " ".join((title, message, source))
    if "known issue" in title:
        return _has_real_known_issue(message)
    if any(token in blob for token in ("photo", "documentation", "audit date", "last audit", "assembly id")):
        return False
    return any(
        token in blob
        for token in (
            "tool",
            "machine",
            "eoat",
            "robot",
            "air",
            "vacuum",
            "sensor",
            "quick disconnect",
            "drop",
            "mis-pick",
            "mispick",
            "repair",
            "mechanical",
            "compatib",
        )
    )


def _documentation_notes(tool: ToolRecord | None, machine: MachineRecord | None, eoat: EOATRecord | None) -> tuple[str, ...]:
    notes: list[str] = []
    for record, label in ((tool, "Tool"), (machine, "Machine"), (eoat, "EOAT")):
        if record is None:
            continue
        if not _last_audit(record):
            notes.append(f"{label} last audit is not indexed.")
    if eoat is not None:
        if _photo_count(eoat) <= 0:
            notes.append("EOAT has no linked or folder-indexed photos.")
        score = _documentation_score(eoat)
        if score and score < 75:
            notes.append(f"EOAT documentation score is {score}%.")
    return tuple(notes)


def _air_blob(eoat: EOATRecord | None) -> str:
    if eoat is None:
        return ""
    return " ".join(
        display_value(value)
        for value in (
            getattr(eoat, "connection_type", ""),
            getattr(eoat, "vacuum_info", ""),
            getattr(eoat, "pressure_info", ""),
            getattr(eoat, "gripper_info", ""),
            _first_row_value(eoat, "Air Circuit Architecture"),
            _first_row_value(eoat, "External Pressure Circuits"),
            _first_row_value(eoat, "External Vacuum Circuits"),
        )
        if display_value(value)
    ).casefold()


def _machine_air_blob(machine: MachineRecord | None) -> str:
    if machine is None:
        return ""
    return " ".join(
        value
        for value in (
            _first_row_value(machine, "Air Circuit Architecture"),
            _first_row_value(machine, "External Pressure Circuits"),
            _first_row_value(machine, "External Vacuum Circuits"),
            _rows_blob(getattr(machine, "source_rows", ()) or ()),
        )
        if value
    ).casefold()


def _has_negative_external_air(machine_air: str) -> bool:
    return any(token in machine_air for token in ("no external", "none", "0 external", "not available"))


def _parts_picked(record: Any) -> int:
    if record is None:
        return 0
    for alias in ("Number of Parts Picked", "# Parts Picked", "Parts Picked", "# of Cups", "# of Grippers"):
        value = _first_row_value(record, alias)
        parsed = _first_int(value)
        if parsed:
            return parsed
    text = " ".join(
        display_value(value)
        for value in (
            getattr(record, "vacuum_info", ""),
            getattr(record, "pressure_info", ""),
            getattr(record, "gripper_info", ""),
        )
        if display_value(value)
    )
    return _first_int(text)


def _first_int(value: str) -> int:
    match = re.search(r"\b(\d+)\b", str(value or ""))
    return int(match.group(1)) if match else 0


def _token_overlap(value: str, haystack: str) -> bool:
    folded = str(value or "").casefold()
    tokens = [token for token in re.split(r"[^a-z0-9]+", folded) if len(token) >= 3]
    return any(token in haystack for token in tokens)


def _machine_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip()
    return (0, int(text)) if text.isdigit() else (1, text.casefold())


def _alternative_rank(status: AlternativeStatus) -> int:
    return {
        "best": 0,
        "current": 1,
        "available": 2,
        "verify": 3,
        "missing_data": 4,
        "incompatible": 5,
        "not_recommended": 6,
    }.get(status, 6)


def _tool_details(tool: ToolRecord | None) -> dict[str, Any]:
    if tool is None:
        return {}
    return {
        "tool": tool.tool,
        "label": tool.label,
        "molds": tool.molds,
        "parts": tool.parts,
        "part_family": tool.part_family,
        "part_description": tool.part_description,
        "compatible_eoats": tool.compatible_eoats,
        "compatible_machines": tool.compatible_machines,
        "source": tool.source,
    }


def _machine_details(machine: MachineRecord | None) -> dict[str, Any]:
    if machine is None:
        return {}
    return {
        "machine": machine.machine,
        "label": machine.label,
        "robot_type": machine.robot_type,
        "robot_model": machine.robot_model,
        "controller": machine.controller,
        "current_eoat": machine.current_eoat,
        "current_eoat_status": machine.current_eoat_status,
        "current_eoat_source": machine.current_eoat_source,
        "current_eoat_confidence": machine.current_eoat_confidence,
        "compatible_eoats": machine.compatible_eoats,
        "compatible_tools": machine.compatible_tools,
    }


def _eoat_details(eoat: EOATRecord | None) -> dict[str, Any]:
    if eoat is None:
        return {}
    return {
        "eoat_id": eoat.eoat_id,
        "display_id": eoat.display_id,
        "tools": eoat.tools,
        "molds": eoat.molds,
        "parts": eoat.parts,
        "machines": eoat.machines,
        "part_family": eoat.part_family,
        "part_description": eoat.part_description,
        "eoat_type": eoat.eoat_type,
        "status": eoat.status,
        "connection_type": eoat.connection_type,
        "vacuum_info": eoat.vacuum_info,
        "pressure_info": eoat.pressure_info,
        "gripper_info": eoat.gripper_info,
        "sensor_info": eoat.sensor_info,
        "documentation_score": _documentation_score(eoat),
        "photo_count": _photo_count(eoat),
    }


def _warning_from_model(warning: WarningItem) -> FitCheckWarning:
    severity = "critical" if str(warning.severity).casefold() in {"critical", "error"} else "warning"
    return FitCheckWarning(re.sub(r"\W+", "-", warning.title.casefold()).strip("-"), severity, warning.title, warning.message)


__all__ = [
    "FitCheckAlternativeEOAT",
    "FitCheckAlternativeMachine",
    "FitCheckAlternatives",
    "FitCheckDetails",
    "FitCheckCompatibility",
    "FitCheckInputCompleteness",
    "FitCheckInputValues",
    "FitCheckPathSegment",
    "FitCheckRequest",
    "FitCheckRequirement",
    "FitCheckResult",
    "FitCheckValidity",
    "FitCheckService",
    "FitCheckWarning",
    "run_fit_check",
]
