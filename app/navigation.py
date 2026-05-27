from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    label: str
    page_key: str


@dataclass(frozen=True)
class NavSection:
    label: str
    items: list[NavItem]


NAV_SECTIONS = [
    NavSection("Overview", [NavItem("Home", "home"), NavItem("Schedule", "schedule")]),
    NavSection("Capture", [NavItem("EOAT Audit", "audit"), NavItem("Notes", "notes"), NavItem("Tags", "tags"), NavItem("Photos", "photos"), NavItem("Audit Progress", "audit_progress")]),
    NavSection("Analysis", [NavItem("Issues", "issue_analysis"), NavItem("FMEA-Lite", "fmea"), NavItem("Pilot Candidates", "pilot_candidates"), NavItem("KPI Dashboard", "kpi_dashboard")]),
    NavSection("Standards", [NavItem("Standards Docs", "standards_docs"), NavItem("PM Checklists", "pm_checklists"), NavItem("BOM / Spare Parts", "bom_spares")]),
    NavSection("Output", [NavItem("Reports", "reports"), NavItem("Scheduled Reports", "scheduled_reports"), NavItem("Final Handoff", "handoff")]),
    NavSection("System", [NavItem("Tool Registry", "tool_registry"), NavItem("Workbook Health", "workbook_health"), NavItem("Settings", "settings")]),
]

NAV_ITEMS = [item for section in NAV_SECTIONS for item in section.items]
