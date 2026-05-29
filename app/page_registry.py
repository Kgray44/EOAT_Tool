from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from .event_bus import (
    EVENT_ANNOTATION_CHANGED,
    EVENT_AUDIT_SAVED,
    EVENT_COMPATIBILITY_REGENERATED,
    EVENT_DASHBOARD_CACHE_INVALIDATED,
    EVENT_OPEN_ITEMS_CHANGED,
    EVENT_PROJECT_ROOT_CHANGED,
    EVENT_REPORT_GENERATED,
    EVENT_SCHEDULED_REPORT_RAN,
    EVENT_SETTINGS_CHANGED,
    EVENT_TAG_CHANGED,
    EVENT_WORKBOOK_VALIDATED,
)


@dataclass(frozen=True)
class PageSpec:
    key: str
    label: str
    section: str
    factory_path: str
    requires_config: bool = True
    refresh_on_show: bool = False
    listens_to: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


PAGE_SPECS: tuple[PageSpec, ...] = (
    PageSpec(
        "home",
        "Home",
        "Overview",
        "app.pages.home:HomePage",
        listens_to=(
            EVENT_PROJECT_ROOT_CHANGED,
            EVENT_SETTINGS_CHANGED,
            EVENT_AUDIT_SAVED,
            EVENT_WORKBOOK_VALIDATED,
            EVENT_REPORT_GENERATED,
            EVENT_DASHBOARD_CACHE_INVALIDATED,
        ),
        description="Dashboard cockpit and workflow launcher.",
    ),
    PageSpec("schedule", "Schedule", "Overview", "app.pages.schedule:SchedulePage", description="Project schedule and morning planning."),
    PageSpec(
        "audit",
        "EOAT Audit",
        "Capture",
        "app.pages.audit:AuditPage",
        listens_to=(EVENT_PROJECT_ROOT_CHANGED,),
        description="Audit entry, interview notes, annotations, and compatibility tools.",
    ),
    PageSpec(
        "press_view",
        "Press View",
        "Capture",
        "app.pages.press_view:PressViewPage",
        refresh_on_show=True,
        listens_to=(EVENT_AUDIT_SAVED, EVENT_COMPATIBILITY_REGENERATED, EVENT_OPEN_ITEMS_CHANGED, EVENT_WORKBOOK_VALIDATED),
        description="App-native press/machine grouping of physical audits, compatible entries, and follow-ups.",
    ),
    PageSpec(
        "machine_360",
        "Machine 360",
        "Capture",
        "app.pages.machine_360:Machine360Page",
        refresh_on_show=True,
        listens_to=(EVENT_AUDIT_SAVED, EVENT_COMPATIBILITY_REGENERATED, EVENT_OPEN_ITEMS_CHANGED, EVENT_WORKBOOK_VALIDATED),
        description="Machine-centered audit, compatibility, evidence, and open-item context.",
    ),
    PageSpec(
        "notes",
        "Notes",
        "Capture",
        "app.pages.notes:NotesPage",
        refresh_on_show=True,
        listens_to=(EVENT_ANNOTATION_CHANGED, EVENT_TAG_CHANGED),
        description="Annotation notes.",
    ),
    PageSpec(
        "tags",
        "Tags",
        "Capture",
        "app.pages.tags:TagsPage",
        refresh_on_show=True,
        listens_to=(EVENT_ANNOTATION_CHANGED, EVENT_TAG_CHANGED),
        description="Annotation tags and assignments.",
    ),
    PageSpec(
        "open_items",
        "Open Items",
        "Capture",
        "app.pages.open_items:OpenItemsPage",
        refresh_on_show=True,
        listens_to=(EVENT_ANNOTATION_CHANGED, EVENT_TAG_CHANGED, EVENT_OPEN_ITEMS_CHANGED, EVENT_AUDIT_SAVED, EVENT_WORKBOOK_VALIDATED),
        description="Unified notes, tags, validation findings, follow-ups, and action board.",
    ),
    PageSpec("photos", "Photos", "Capture", "app.pages.photos:PhotosPage", description="Photo intake and photo index updates."),
    PageSpec(
        "audit_progress",
        "Audit Progress",
        "Capture",
        "app.pages.audit_progress:AuditProgressPage",
        refresh_on_show=True,
        listens_to=(EVENT_AUDIT_SAVED, EVENT_COMPATIBILITY_REGENERATED),
        description="Audit progress metrics and reports.",
    ),
    PageSpec(
        "compatibility_matrix",
        "Compatibility Matrix",
        "Analysis",
        "app.pages.compatibility_matrix:CompatibilityMatrixPage",
        refresh_on_show=True,
        listens_to=(EVENT_AUDIT_SAVED, EVENT_COMPATIBILITY_REGENERATED, EVENT_WORKBOOK_VALIDATED),
        description="Machine/tool compatibility matrix with source audit and review details.",
    ),
    PageSpec("issue_analysis", "Issues", "Analysis", "app.pages.issue_analysis:IssueAnalysisPage", description="Issue log analysis."),
    PageSpec("fmea", "FMEA-Lite", "Analysis", "app.pages.fmea:FmeaPage", description="FMEA-lite analysis."),
    PageSpec("pilot_candidates", "Pilot Candidates", "Analysis", "app.pages.pilot_candidates:PilotCandidatesPage", description="Pilot candidate scoring."),
    PageSpec("kpi_dashboard", "KPI Dashboard", "Analysis", "app.pages.kpi_dashboard:KpiDashboardPage", description="KPI summary reports."),
    PageSpec("standards_docs", "Standards Docs", "Standards", "app.pages.standards_docs:StandardsDocsPage", description="Documentation gap reports."),
    PageSpec("pm_checklists", "PM Checklists", "Standards", "app.pages.pm_checklists:PmChecklistsPage", description="PM checklist generation."),
    PageSpec("bom_spares", "BOM / Spare Parts", "Standards", "app.pages.bom_spares:BomSparesPage", description="BOM and spare part analysis."),
    PageSpec(
        "reports",
        "Reports",
        "Output",
        "app.pages.reports:ReportsPage",
        refresh_on_show=True,
        listens_to=(EVENT_REPORT_GENERATED, EVENT_SCHEDULED_REPORT_RAN),
        description="Report browsing and summary generation.",
    ),
    PageSpec(
        "scheduled_reports",
        "Scheduled Reports",
        "Output",
        "app.pages.scheduled_reports:ScheduledReportsPage",
        refresh_on_show=True,
        listens_to=(EVENT_SCHEDULED_REPORT_RAN, EVENT_REPORT_GENERATED),
        description="Scheduled daily and weekly summary status.",
    ),
    PageSpec("handoff", "Final Handoff", "Output", "app.pages.handoff:HandoffPage", description="Final deliverable and handoff package tools."),
    PageSpec("tool_registry", "Tool Registry", "System", "app.pages.tool_registry:ToolRegistryPage", requires_config=False, description="Registered tools."),
    PageSpec(
        "workbook_health",
        "Workbook Health",
        "System",
        "app.pages.workbook_health:WorkbookHealthPage",
        listens_to=(EVENT_WORKBOOK_VALIDATED,),
        description="Workbook validation and repair actions.",
    ),
    PageSpec(
        "performance",
        "Performance",
        "System",
        "app.pages.performance:PerformancePage",
        refresh_on_show=True,
        description="Dashboard cache and performance diagnostics.",
    ),
    PageSpec(
        "backup_manager",
        "Backup Manager",
        "System",
        "app.pages.backup_manager:BackupManagerPage",
        refresh_on_show=True,
        description="Workbook backup inventory, retention preview, and confirmed cleanup.",
    ),
    PageSpec(
        "release_readiness",
        "Release Readiness",
        "System",
        "app.pages.release_readiness:ReleaseReadinessPage",
        refresh_on_show=True,
        description="Git, staged-file, safety-audit, and release checks.",
    ),
    PageSpec(
        "settings",
        "Settings",
        "System",
        "app.pages.settings:SettingsPage",
        listens_to=(EVENT_SETTINGS_CHANGED, EVENT_PROJECT_ROOT_CHANGED),
        description="Project root, theme, Git, checks, and backup settings.",
    ),
)

PAGE_BY_KEY = {spec.key: spec for spec in PAGE_SPECS}


def get_page_spec(page_key: str) -> PageSpec:
    try:
        return PAGE_BY_KEY[page_key]
    except KeyError as exc:
        raise KeyError(f"Unknown dashboard page: {page_key}") from exc


def page_specs_by_section() -> list[tuple[str, list[PageSpec]]]:
    sections: list[tuple[str, list[PageSpec]]] = []
    by_section: dict[str, list[PageSpec]] = {}
    for spec in PAGE_SPECS:
        if spec.section not in by_section:
            by_section[spec.section] = []
            sections.append((spec.section, by_section[spec.section]))
        by_section[spec.section].append(spec)
    return sections


def load_page_factory(spec: PageSpec):
    module_name, _, attribute = spec.factory_path.partition(":")
    if not module_name or not attribute:
        raise ValueError(f"Invalid page factory path for {spec.key}: {spec.factory_path}")
    module = import_module(module_name)
    return getattr(module, attribute)


def create_page(spec: PageSpec, config: Any | None = None):
    page_class = load_page_factory(spec)
    if spec.requires_config:
        if config is None:
            raise ValueError(f"Page {spec.key} requires a config object.")
        return page_class(config)
    return page_class()
