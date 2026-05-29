from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .analysis_common import table_from_rows, write_timestamped_csv, write_timestamped_report
from .audit_entries import repair_legacy_audit_lookup_shift
from .constants import TOOLKIT_ROOT
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_io import row_dicts

TOOL_ID = "standardization_opportunity_finder"
TOOL_NAME = "Standardization Opportunity Finder and BOM/Spare Parts Engine"

DEFAULT_ALIAS_FILE = TOOLKIT_ROOT / "data_templates" / "part_aliases.example.json"
PROJECT_ALIAS_RELATIVE_PATHS = (
    Path("00_Project_Admin") / "part_aliases.json",
    Path("03_Standards") / "BOM_Template_Draft" / "part_aliases.json",
)

DEFAULT_PART_ALIASES: dict[str, dict[str, str]] = {
    "Gripper Model": {
        "Large Double Gripper": "MHZL2-16D",
        "Small Double Gripper": "MHZL2-10S",
    }
}

COMPONENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("cup types", "Cup Type/Material"),
    ("cup sizes", "Cup Diameter/Size"),
    ("vacuum generators", "Vacuum Generator Type"),
    ("gripper models", "Gripper Model"),
    ("gripper types", "Gripper Type"),
    ("sensor types", "Sensor Type"),
    ("sensor brands/models", "Sensor Brand/Model"),
    ("pneumatic quick disconnect types", "Pneumatic Quick Disconnect Type"),
    ("electrical quick disconnect types", "Electrical Quick Disconnect Type"),
    ("connection types", "Connection Type"),
    ("spare parts identified status", "Spare Parts Identified?"),
)

PART_NUMBER_FIELDS = {
    "Cup Type/Material",
    "Cup Diameter/Size",
    "Vacuum Generator Type",
    "Gripper Model",
    "Gripper Type",
    "Sensor Brand/Model",
    "Pneumatic Quick Disconnect Type",
    "Electrical Quick Disconnect Type",
    "Connection Type",
}

DOCUMENTATION_FIELDS = (
    "Spare Parts Identified?",
    "BOM Available?",
    "Drawing/CAD Available?",
    "Process Binder Complete?",
)

UNKNOWN_TOKENS = {
    "",
    "unknown",
    "unknown / not checked",
    "not checked",
    "needs review",
    "tbd",
    "to be determined",
    "n/a",
    "na",
    "none",
}


@dataclass(frozen=True)
class ComponentObservation:
    category: str
    field: str
    raw_value: str
    normalized_value: str
    audit_id: str
    machine: str
    plant_area: str
    eoat_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StandardizationAnalysis:
    rows: list[dict[str, Any]]
    observations: list[ComponentObservation]
    component_frequency_table: list[dict[str, Any]]
    unknown_missing_part_number_table: list[dict[str, Any]]
    suggested_controlled_vocabulary: list[dict[str, Any]]
    recommended_standard_parts_list: list[dict[str, Any]]
    candidate_bom_cleanup_actions: list[dict[str, Any]]
    documentation_gap_table: list[dict[str, Any]]
    opportunities: list[str]
    aliases: dict[str, dict[str, str]]
    warnings: list[str]
    details: list[str]

    @property
    def counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for row in self.component_frequency_table:
            counts.setdefault(str(row["Category"]), {})[str(row["Component"])] = int(row["Count"])
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "observations": [observation.to_dict() for observation in self.observations],
            "component_frequency_table": self.component_frequency_table,
            "unknown_missing_part_number_table": self.unknown_missing_part_number_table,
            "suggested_controlled_vocabulary": self.suggested_controlled_vocabulary,
            "recommended_standard_parts_list": self.recommended_standard_parts_list,
            "candidate_bom_cleanup_actions": self.candidate_bom_cleanup_actions,
            "documentation_gap_table": self.documentation_gap_table,
            "opportunities": self.opportunities,
            "aliases": self.aliases,
            "warnings": self.warnings,
            "details": self.details,
            "counts": self.counts,
        }


def load_part_aliases(project_root: str | Path | None = None, alias_path: str | Path | None = None) -> dict[str, dict[str, str]]:
    aliases = _copy_aliases(DEFAULT_PART_ALIASES)
    for path in _alias_candidate_paths(project_root, alias_path):
        if not path.exists():
            continue
        try:
            aliases = _merge_aliases(aliases, _parse_alias_file(path))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return aliases


def normalize_part_alias(field: str, value: Any, aliases: dict[str, dict[str, str]] | None = None) -> str:
    text = _clean(value)
    if not text:
        return ""
    aliases = aliases or DEFAULT_PART_ALIASES
    candidate_maps = [aliases.get(field, {}), aliases.get("*", {})]
    normalized_lookup = _normalize_for_lookup(text)
    for alias_map in candidate_maps:
        for raw_alias, canonical in alias_map.items():
            if _normalize_for_lookup(raw_alias) == normalized_lookup:
                return _clean(canonical)
    return text


def analyze_standardization_opportunities(
    project_root: str | Path,
    *,
    alias_path: str | Path | None = None,
) -> StandardizationAnalysis:
    paths = resolve_project_paths(project_root)
    warnings: list[str] = []
    if not paths.master_workbook.exists():
        warning = f"Master workbook not found: {paths.master_workbook}"
        return StandardizationAnalysis([], [], [], [], [], [], [], [], ["Start by auditing representative EOATs before standardizing parts."], load_part_aliases(project_root, alias_path), [warning], [])

    try:
        rows = [repair_legacy_audit_lookup_shift(row) for row in row_dicts(paths.master_workbook, "EOAT Inventory")]
    except Exception as exc:
        warning = f"Could not read EOAT Inventory: {exc}"
        return StandardizationAnalysis([], [], [], [], [], [], [], [], ["Start by auditing representative EOATs before standardizing parts."], load_part_aliases(project_root, alias_path), [warning], [])

    aliases = load_part_aliases(project_root, alias_path)
    observations = _component_observations(rows, aliases)
    frequency_rows = _component_frequency_table(observations)
    unknown_rows = _unknown_missing_part_number_table(rows)
    vocabulary_rows = _suggested_controlled_vocabulary(frequency_rows)
    recommendation_rows = _recommended_standard_parts(frequency_rows)
    documentation_gap_rows = _documentation_gap_table(rows)
    cleanup_rows = _candidate_cleanup_actions(rows, observations, unknown_rows, documentation_gap_rows)
    opportunities = _opportunities(rows, frequency_rows, unknown_rows, documentation_gap_rows, cleanup_rows)
    details = [f"Read {len(rows)} EOAT Inventory row(s).", f"Analyzed {len(observations)} component observation(s)."]
    return StandardizationAnalysis(
        rows=rows,
        observations=observations,
        component_frequency_table=frequency_rows,
        unknown_missing_part_number_table=unknown_rows,
        suggested_controlled_vocabulary=vocabulary_rows,
        recommended_standard_parts_list=recommendation_rows,
        candidate_bom_cleanup_actions=cleanup_rows,
        documentation_gap_table=documentation_gap_rows,
        opportunities=opportunities,
        aliases=aliases,
        warnings=warnings,
        details=details,
    )


def build_standardization_report_markdown(analysis: StandardizationAnalysis) -> str:
    lines = [
        "# Standardization Opportunities and BOM/Spare Parts Report",
        "",
        "## Executive Summary",
        f"- EOAT records scanned: {len(analysis.rows)}",
        f"- Component observations analyzed: {len(analysis.observations)}",
        f"- Standard part recommendations: {len(analysis.recommended_standard_parts_list)}",
        f"- Unknown/missing part rows: {len(analysis.unknown_missing_part_number_table)}",
        f"- Candidate cleanup actions: {len(analysis.candidate_bom_cleanup_actions)}",
    ]
    if analysis.warnings:
        lines.extend(f"- Warning: {warning}" for warning in analysis.warnings)
    lines.extend(["", "## Standardization Opportunities"])
    lines.extend(f"- {item}" for item in analysis.opportunities)
    lines.extend(["", "## Component Frequency Table"])
    lines.extend(
        table_from_rows(
            analysis.component_frequency_table[:50],
            ["Category", "Component", "Count", "Machines", "Audits", "Raw Values"],
        )
    )
    lines.extend(["", "## Unknown / Missing Part Numbers"])
    lines.extend(
        table_from_rows(
            analysis.unknown_missing_part_number_table[:50],
            ["Audit ID", "Press/Machine #", "EOAT Type", "Field", "Reason"],
        )
    )
    lines.extend(["", "## Suggested Controlled Vocabulary"])
    lines.extend(table_from_rows(analysis.suggested_controlled_vocabulary[:50], ["Category", "Field", "Suggested Values"]))
    lines.extend(["", "## Recommended Standard Parts"])
    lines.extend(
        table_from_rows(
            analysis.recommended_standard_parts_list[:50],
            ["Category", "Field", "Recommended Part", "Count", "Machines", "Audits"],
        )
    )
    lines.extend(["", "## Candidate BOM Cleanup Actions"])
    lines.extend(
        table_from_rows(
            analysis.candidate_bom_cleanup_actions[:75],
            ["Action Type", "Audit ID", "Press/Machine #", "Field", "Current Value", "Recommended Value", "Reason"],
        )
    )
    lines.extend(
        [
            "",
            "## Guardrails",
            "- Treat recommendations as review candidates, not automatic workbook edits.",
            "- Verify actual manufacturer part numbers from the EOAT, approved BOM, or controlled documentation before changing workbook values.",
            "- Keep alias mappings local and review them with maintenance/engineering before broad cleanup.",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_standardization_report(project_root: str | Path, *, alias_path: str | Path | None = None) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.bom_standardization_reports)
    analysis = analyze_standardization_opportunities(project_root, alias_path=alias_path)
    report = write_timestamped_report(
        paths.bom_standardization_reports,
        "Standardization_Opportunities_Report",
        build_standardization_report_markdown(analysis),
    )
    files_created = [str(report)]
    csv_outputs = [
        ("Component_Frequency_Table", analysis.component_frequency_table),
        ("Unknown_Missing_Part_Number_Table", analysis.unknown_missing_part_number_table),
        ("Suggested_Controlled_Vocabulary", analysis.suggested_controlled_vocabulary),
        ("Recommended_Standard_Parts_List", analysis.recommended_standard_parts_list),
        ("Candidate_BOM_Cleanup_Actions", analysis.candidate_bom_cleanup_actions),
    ]
    for name, rows in csv_outputs:
        if rows:
            files_created.append(str(write_timestamped_csv(paths.bom_standardization_reports, name, rows)))

    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Generated standardization opportunities and BOM/spare parts report.",
        details=analysis.details,
        warnings=analysis.warnings,
        files_created=files_created,
        output_reports=files_created,
        structured_data=analysis.to_dict(),
        metrics={
            "inventory_rows": len(analysis.rows),
            "component_observations": len(analysis.observations),
            "component_frequency_rows": len(analysis.component_frequency_table),
            "unknown_missing_part_rows": len(analysis.unknown_missing_part_number_table),
            "recommendation_count": len(analysis.recommended_standard_parts_list),
            "cleanup_action_count": len(analysis.candidate_bom_cleanup_actions),
            "opportunity_count": len(analysis.opportunities),
        },
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result


def _component_observations(rows: list[dict[str, Any]], aliases: dict[str, dict[str, str]]) -> list[ComponentObservation]:
    observations: list[ComponentObservation] = []
    for row in rows:
        audit_id = _clean(row.get("Audit ID"))
        machine = _clean(row.get("Press/Machine #"))
        plant = _clean(row.get("Plant/Area"))
        eoat_type = _clean(row.get("EOAT Type"))
        for category, field in COMPONENT_FIELDS:
            raw_value = _clean(row.get(field))
            if _is_unknown(raw_value):
                continue
            observations.append(
                ComponentObservation(
                    category=category,
                    field=field,
                    raw_value=raw_value,
                    normalized_value=normalize_part_alias(field, raw_value, aliases),
                    audit_id=audit_id,
                    machine=machine,
                    plant_area=plant,
                    eoat_type=eoat_type,
                )
            )
    return observations


def _component_frequency_table(observations: list[ComponentObservation]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[ComponentObservation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.category, observation.field, observation.normalized_value)].append(observation)
    rows: list[dict[str, Any]] = []
    for (category, field, component), items in grouped.items():
        raw_values = sorted({item.raw_value for item in items if item.raw_value})
        machines = sorted({item.machine for item in items if item.machine})
        audits = sorted({item.audit_id for item in items if item.audit_id})
        rows.append(
            {
                "Category": category,
                "Field": field,
                "Component": component,
                "Count": len(items),
                "Raw Values": ", ".join(raw_values),
                "Machines": ", ".join(machines),
                "Audits": ", ".join(audits),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["Count"]), str(row["Category"]), str(row["Component"])))


def _unknown_missing_part_number_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for row in rows:
        for field in sorted(PART_NUMBER_FIELDS):
            value = _clean(row.get(field))
            if not _is_unknown(value):
                continue
            missing.append(
                {
                    "Audit ID": _clean(row.get("Audit ID")),
                    "Plant/Area": _clean(row.get("Plant/Area")),
                    "Press/Machine #": _clean(row.get("Press/Machine #")),
                    "EOAT Type": _clean(row.get("EOAT Type")),
                    "Field": field,
                    "Current Value": value,
                    "Reason": "Missing or unknown part/model value.",
                }
            )
    return sorted(missing, key=lambda row: (str(row["Audit ID"]), str(row["Field"])))


def _suggested_controlled_vocabulary(frequency_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_category: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in frequency_rows:
        by_category[(str(row["Category"]), str(row["Field"]))].append(row)
    vocabulary: list[dict[str, Any]] = []
    for (category, field), rows in by_category.items():
        values = [str(row["Component"]) for row in sorted(rows, key=lambda item: (-int(item["Count"]), str(item["Component"])))]
        vocabulary.append({"Category": category, "Field": field, "Suggested Values": "; ".join(values[:12])})
    return sorted(vocabulary, key=lambda row: str(row["Category"]))


def _recommended_standard_parts(frequency_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for row in frequency_rows:
        count = int(row["Count"])
        if count < 2:
            continue
        recommendations.append(
            {
                "Category": row["Category"],
                "Field": row["Field"],
                "Recommended Part": row["Component"],
                "Count": count,
                "Machines": row["Machines"],
                "Audits": row["Audits"],
                "Reason": f"Observed on {count} audited EOAT record(s).",
            }
        )
    return sorted(recommendations, key=lambda row: (-int(row["Count"]), str(row["Category"]), str(row["Recommended Part"])))


def _documentation_gap_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for row in rows:
        missing_fields = [field for field in DOCUMENTATION_FIELDS if _is_missing_documentation_status(row.get(field))]
        if not missing_fields:
            continue
        gaps.append(
            {
                "Audit ID": _clean(row.get("Audit ID")),
                "Plant/Area": _clean(row.get("Plant/Area")),
                "Press/Machine #": _clean(row.get("Press/Machine #")),
                "EOAT Type": _clean(row.get("EOAT Type")),
                "Missing Field Count": len(missing_fields),
                "Missing Fields": ", ".join(missing_fields),
            }
        )
    return sorted(gaps, key=lambda row: (-int(row["Missing Field Count"]), str(row["Audit ID"])))


def _candidate_cleanup_actions(
    rows: list[dict[str, Any]],
    observations: list[ComponentObservation],
    unknown_rows: list[dict[str, Any]],
    documentation_gap_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for observation in observations:
        if observation.raw_value == observation.normalized_value:
            continue
        actions.append(
            {
                "Action Type": "Alias normalization",
                "Audit ID": observation.audit_id,
                "Press/Machine #": observation.machine,
                "EOAT Type": observation.eoat_type,
                "Field": observation.field,
                "Current Value": observation.raw_value,
                "Recommended Value": observation.normalized_value,
                "Reason": "Alias maps this value to a controlled part/model.",
            }
        )
    for row in unknown_rows:
        actions.append(
            {
                "Action Type": "Part/model lookup",
                "Audit ID": row["Audit ID"],
                "Press/Machine #": row["Press/Machine #"],
                "EOAT Type": row["EOAT Type"],
                "Field": row["Field"],
                "Current Value": row["Current Value"],
                "Recommended Value": "",
                "Reason": "Verify the physical component or approved documentation and record the controlled value.",
            }
        )
    for row in documentation_gap_rows:
        actions.append(
            {
                "Action Type": "Documentation status cleanup",
                "Audit ID": row["Audit ID"],
                "Press/Machine #": row["Press/Machine #"],
                "EOAT Type": row["EOAT Type"],
                "Field": row["Missing Fields"],
                "Current Value": "",
                "Recommended Value": "Confirm Yes/No status",
                "Reason": "BOM/CAD/process binder/spares status is missing or unknown.",
            }
        )
    return sorted(actions, key=lambda row: (str(row["Action Type"]), str(row["Audit ID"]), str(row["Field"])))


def _opportunities(
    rows: list[dict[str, Any]],
    frequency_rows: list[dict[str, Any]],
    unknown_rows: list[dict[str, Any]],
    documentation_gap_rows: list[dict[str, Any]],
    cleanup_rows: list[dict[str, Any]],
) -> list[str]:
    if not rows:
        return ["Start by auditing representative EOATs before standardizing parts."]
    opportunities: list[str] = []
    for row in frequency_rows:
        count = int(row["Count"])
        if count >= 2:
            opportunities.append(f"Review common {row['Category']}: {row['Component']} appears on {count} EOAT record(s).")
    if unknown_rows:
        opportunities.append(f"Resolve unknown or missing component/model values on {len(unknown_rows)} field(s).")
    if documentation_gap_rows:
        opportunities.append(f"Close BOM/CAD/process binder/spare-parts status gaps on {len(documentation_gap_rows)} EOAT record(s).")
    alias_actions = [row for row in cleanup_rows if row["Action Type"] == "Alias normalization"]
    if alias_actions:
        opportunities.append(f"Normalize {len(alias_actions)} aliased component value(s) to controlled part/model names.")
    return _dedupe(opportunities) or ["No obvious standardization opportunity was detected from current workbook fields."]


def _alias_candidate_paths(project_root: str | Path | None, alias_path: str | Path | None) -> list[Path]:
    paths: list[Path] = [DEFAULT_ALIAS_FILE]
    if project_root is not None:
        root = Path(project_root)
        paths.extend(root / relative for relative in PROJECT_ALIAS_RELATIVE_PATHS)
    if alias_path is not None:
        paths.append(Path(alias_path))
    return paths


def _parse_alias_file(path: Path) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_aliases = payload.get("aliases", payload) if isinstance(payload, dict) else {}
    if not isinstance(raw_aliases, dict):
        raise ValueError("Alias file must contain an object.")
    parsed: dict[str, dict[str, str]] = {}
    for field, alias_map in raw_aliases.items():
        if not isinstance(alias_map, dict):
            continue
        parsed[str(field)] = {str(raw): str(canonical) for raw, canonical in alias_map.items()}
    return parsed


def _copy_aliases(aliases: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {field: dict(alias_map) for field, alias_map in aliases.items()}


def _merge_aliases(base: dict[str, dict[str, str]], updates: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    merged = _copy_aliases(base)
    for field, alias_map in updates.items():
        merged.setdefault(field, {}).update(alias_map)
    return merged


def _is_unknown(value: Any) -> bool:
    return _normalize_for_lookup(value) in UNKNOWN_TOKENS


def _is_missing_documentation_status(value: Any) -> bool:
    text = _normalize_for_lookup(value)
    return text in UNKNOWN_TOKENS or text == "unknown not checked"


def _normalize_for_lookup(value: Any) -> str:
    return " ".join(_clean(value).replace("_", " ").replace("-", " ").casefold().split())


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


__all__ = [
    "COMPONENT_FIELDS",
    "DEFAULT_PART_ALIASES",
    "StandardizationAnalysis",
    "ComponentObservation",
    "analyze_standardization_opportunities",
    "build_standardization_report_markdown",
    "generate_standardization_report",
    "load_part_aliases",
    "normalize_part_alias",
]
