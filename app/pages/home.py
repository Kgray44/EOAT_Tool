from __future__ import annotations

import time
from pathlib import Path

try:
    from PySide6.QtCore import QTimer, Signal
    from PySide6.QtWidgets import (
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QTimer = Signal = None
    QGridLayout = QGroupBox = QHBoxLayout = QLabel = QMessageBox = QPushButton = QScrollArea = QVBoxLayout = QWidget = (
        None
    )

from app.event_bus import EVENT_AUDIT_SAVED
from app.task_runner import TaskRequest, get_task_manager
from app.ui_constants import PAGE_MARGIN, SECTION_SPACING
from app.widgets.file_picker import select_directory
from app.widgets.open_items_panel import OpenItemsPanel
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from app.widgets.workflow_card import WorkflowCard
from core.config import save_config
from core.dashboard_cache import cached_snapshot_status, save_dashboard_cache
from core.git_activity import get_git_status_short, is_git_repo
from core.logging import read_recent_activity
from core.openers import open_path
from core.paths import resolve_project_paths, validate_looks_like_eoat_project_root
from core.performance import log_performance
from core.project_root_status import validate_project_root
from core.reports import list_recent_files
from core.schedule import available_schedule_weeks, load_week_schedule, resolve_project_day_for_project
from core.scheduled_reports import get_scheduled_report_status


def collect_home_status_snapshot(
    project_root: str,
    git_executable: str,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> dict:
    from core.audit_progress import calculate_audit_progress
    from core.bom_standardization import analyze_bom_standardization
    from core.documentation_gaps import scan_documentation_gaps
    from core.fmea_analysis import analyze_fmea
    from core.kpi_analysis import analyze_kpis
    from core.tool_registry import ToolRegistry
    from core.validation import validate_project_foundation
    from core.workbook_cache import row_dicts_cached as row_dicts

    started = time.perf_counter()
    root = Path(project_root)
    paths = resolve_project_paths(root)
    root_status = validate_project_root(root)
    valid, missing = validate_looks_like_eoat_project_root(root)
    git_repo, git_warning = is_git_repo(root, git_executable) if root.exists() else (False, "Project root missing")
    status_lines, status_warning = get_git_status_short(root, git_executable) if git_repo else ([], git_warning)
    registry = ToolRegistry.load()
    activities, activity_warning = read_recent_activity(root, limit=10)
    validation = validate_project_foundation(root)
    weeks = available_schedule_weeks(root)
    resolved_day = resolve_project_day_for_project(
        root, project_start_date=project_start_date, skip_weekends=skip_weekends, holidays=holidays or []
    )
    progress, progress_error = calculate_audit_progress(root)
    doc_summary, _doc_error = scan_documentation_gaps(root)
    fmea_summary, _fmea_error = analyze_fmea(root)
    kpi_summary, _kpi_error = analyze_kpis(root)
    bom_data, _bom_warnings, _bom_details = analyze_bom_standardization(root)

    cards: dict[str, str] = {}
    cards["Active Project Root"] = str(root)
    cards["Data Mode"] = root_status.mode_label
    cards["Master Workbook Path"] = str(root_status.master_workbook)
    cards["Project Root"] = "OK" if valid else f"Warning: {len(missing)} issue(s)"
    cards["Master Workbook"] = "OK" if paths.master_workbook.exists() else "Missing"
    git_text = "OK"
    if not git_repo:
        git_text = "Not detected"
    elif status_lines:
        git_text = f"OK; {len(status_lines)} uncommitted change(s)"
    if status_warning and not git_repo:
        git_text = f"Warning: {status_warning}"
    cards["Git Status"] = git_text
    cards["Workbook Health"] = "OK" if validation.success and not validation.warnings else "Warning"
    cards["Tool Registry"] = f"OK: {len(registry.list_tools())} tools registered"
    cards["Activity Log"] = "OK" if activities else ("Warning" if activity_warning else "Not checked")

    cards["Resolved Project Day"] = f"Week {resolved_day.week} Day {resolved_day.day} from {resolved_day.source}"
    if resolved_day.warning:
        cards["Resolved Project Day"] = f"Week {resolved_day.week} Day {resolved_day.day}; {resolved_day.warning}"

    if weeks:
        current_week = resolved_day.week if resolved_day.week in weeks else weeks[0]
        current = load_week_schedule(root, current_week)
        counts = ", ".join(f"{key}: {value}" for key, value in current.status_counts.items() if value)
        cards["Current Schedule"] = f"Week {current_week}: {counts or 'tasks loaded'}"
        cards["Not Started"] = str(current.status_counts.get("Not started", 0))
        cards["In Progress"] = str(current.status_counts.get("In progress", 0))
        cards["Blocked"] = str(current.status_counts.get("Blocked", 0))
        cards["Complete"] = str(current.status_counts.get("Complete", 0))
    else:
        cards["Current Schedule"] = "Not configured"
        for key in ["Not Started", "In Progress", "Blocked", "Complete"]:
            cards[key] = "No schedule"

    if progress:
        metrics = progress.metrics
        cards["EOAT Documentation Rows"] = str(metrics.get("physical_audit_rows", 0))
        cards["Photos Indexed"] = str(metrics.get("photos_indexed_count", 0))
        cards["Interviews Logged"] = str(metrics.get("interviews_logged_count", 0))
        cards["Issues Logged"] = str(metrics.get("issues_logged_count", 0))
        cards["Pilot Candidates"] = (
            f"Yes: {metrics.get('pilot_candidate_yes_count', 0)}, Maybe: {metrics.get('pilot_candidate_maybe_count', 0)}"
        )
    else:
        for key in [
            "EOAT Documentation Rows",
            "Photos Indexed",
            "Interviews Logged",
            "Issues Logged",
            "Pilot Candidates",
        ]:
            cards[key] = "Not checked" if progress_error else "0"
    cards["Documentation Gaps"] = str(doc_summary.metrics.get("total_gaps", 0)) if doc_summary else "No data yet"
    cards["KPI Rows"] = f"{kpi_summary.metrics.get('kpi_rows', 0)}" if kpi_summary else "No data yet"

    try:
        actions = row_dicts(paths.master_workbook, "Action Items") if paths.master_workbook.exists() else []
    except Exception:
        actions = []
    open_statuses = {"", "open", "not started", "needs follow-up", "in progress", "blocked", "new"}
    open_actions = [row for row in actions if str(row.get("Status") or "").strip().lower() in open_statuses]
    cards["Open Action Items"] = str(len(open_actions))
    weekly = list_recent_files(paths.weekly_reports, limit=1)
    cards["Current Week Summary Status"] = weekly[0].name if weekly else "No weekly summary yet"
    scheduled_status = get_scheduled_report_status(root, check_tasks=False)
    daily_status = scheduled_status.get("daily", {})
    weekly_status = scheduled_status.get("weekly", {})
    cards["Daily Summary Schedule"] = daily_status.get("schedule", "Monday-Thursday at 7:00 PM")
    cards["Latest Daily Summary"] = daily_status.get("last_report_date") or "No daily summary yet"
    cards["Missed Daily Summaries"] = ", ".join(daily_status.get("missed_dates", [])) or "None detected"
    cards["Weekly Summary Schedule"] = weekly_status.get("schedule", "Friday at 7:00 PM")
    cards["Latest Weekly Summary"] = weekly_status.get("last_report_date") or "No weekly summary yet"
    cards["Missed Weekly Summaries"] = ", ".join(weekly_status.get("missed_dates", [])) or "None detected"
    morning = list_recent_files(paths.morning_plans, limit=1)
    cards["Latest Morning Plan"] = morning[0].name if morning else "No morning plan yet"
    mentor = list_recent_files(paths.mentor_briefs, limit=1)
    cards["Latest Mentor Brief"] = mentor[0].name if mentor else "No mentor brief yet"
    checklists = list_recent_files(paths.pm_generated_checklists, limit=1)
    cards["PM Checklist Status"] = checklists[0].name if checklists else "No checklist yet"
    cards["BOM/Spare Parts Data Status"] = (
        f"{len(bom_data['missing_rows'])} rows missing data" if bom_data.get("rows") else "No data yet"
    )
    presentation = (
        [path for path in paths.presentation_assets_root.glob("Presentation_Assets_*") if path.is_dir()]
        if paths.presentation_assets_root.exists()
        else []
    )
    cards["Presentation Assets"] = presentation[-1].name if presentation else "No package yet"
    final_reports = list_recent_files(paths.final_report, limit=1)
    cards["Final Summary Draft"] = final_reports[0].name if final_reports else "No summary yet"
    legacy_handoffs = (
        [path for path in paths.handoff_package_root.glob("Final_Handoff_*") if path.is_dir()]
        if paths.handoff_package_root.exists()
        else []
    )
    phase11_handoffs = (
        [path for path in paths.final_handoff.glob("Final_Handoff_Package_*") if path.is_dir()]
        if paths.final_handoff.exists()
        else []
    )
    handoffs = sorted([*phase11_handoffs, *legacy_handoffs], key=lambda path: path.stat().st_mtime)
    cards["Handoff Package"] = handoffs[-1].name if handoffs else "No handoff package yet"

    recommendations: list[str] = []
    audited_count = progress.metrics.get("physical_audit_rows", 0) if progress else 0
    photos_count = progress.metrics.get("photos_indexed_count", 0) if progress else 0
    issues_count = progress.metrics.get("issues_logged_count", 0) if progress else 0
    fmea_rows = fmea_summary.metrics.get("existing_fmea_rows", 0) if fmea_summary else 0
    if root_status.mode == "demo":
        recommendations.append(
            "Demo project is active. Choose your real EOAT project folder before entering real audit data."
        )
    elif not root_status.is_usable:
        recommendations.append(root_status.message)
    if not valid:
        recommendations.append("Run foundation validation or select the correct project root.")
    if audited_count == 0:
        recommendations.append("Start by adding the first EOAT documentation audit entry.")
    if audited_count > 0 and photos_count == 0:
        recommendations.append("Add photos after the first EOAT documentation audit to build visual evidence.")
    if validation.warnings:
        recommendations.append("Review workbook/project validation warnings.")
    if issues_count > 0 and fmea_rows == 0:
        recommendations.append("Run FMEA-lite analysis after issue data is entered.")
    if not handoffs:
        recommendations.append("Run the final deliverable check before final handoff work.")
    if not recommendations:
        recommendations.append("Project cockpit looks ready. Continue with the current schedule or workflow.")

    lines = ["Recent activity:"]
    for entry in activities[:10]:
        lines.append(
            f"- {entry.get('timestamp', '')} | {entry.get('tool_name', '')} | "
            f"{'OK' if entry.get('success') else 'Failed'} | {entry.get('summary', '')}"
        )
    if activity_warning:
        lines.append(f"Activity warning: {activity_warning}")
    lines.extend(["", f"Data mode: {root_status.mode_label}", root_status.message])
    if not valid:
        lines.extend(["", "Project root issues:", *[f"- {item}" for item in missing]])
    if not activities and valid:
        lines.append("- No activity entries yet.")

    snapshot = {
        "project_root": str(root),
        "cards": cards,
        "recommendations": recommendations[:6],
        "activity_text": "\n".join(lines),
        "root_status_message": root_status.message,
        "resolved_week": resolved_day.week,
        "resolved_day": resolved_day.day,
        "resolved_source": resolved_day.source,
        "resolved_warning": resolved_day.warning,
    }
    try:
        cache_path = save_dashboard_cache(root, snapshot)
        snapshot["cards"]["Dashboard Cache"] = f"Updated {cache_path.name}"
    except Exception as exc:
        snapshot["cards"]["Dashboard Cache"] = f"Cache update failed: {exc}"
    log_performance(
        root,
        "dashboard.deep_refresh",
        time.perf_counter() - started,
        source="home",
        page_tool="home",
        details={"cache_updated": True, "card_count": len(cards), "recommendation_count": len(recommendations[:6])},
    )
    return snapshot


def collect_home_quick_status_snapshot(
    project_root: str,
    git_executable: str,
    project_start_date: str = "",
    skip_weekends: bool = True,
    holidays: list[str] | None = None,
) -> dict:
    started = time.perf_counter()
    root = Path(project_root)
    paths = resolve_project_paths(root)
    root_status = validate_project_root(root)
    cache_status = cached_snapshot_status(root)
    snapshot = cache_status.snapshot
    stale = cache_status.stale
    if snapshot:
        cards = dict(snapshot.get("cards", {}))
        cards["Dashboard Cache"] = "Stale; deep refresh available" if stale else "Fresh"
        cards["Active Project Root"] = str(root)
        cards["Data Mode"] = root_status.mode_label
        cards["Master Workbook Path"] = str(root_status.master_workbook)
        recommendations = list(snapshot.get("recommendations", []))
        activity_text = snapshot.get("activity_text", "Showing cached dashboard data.")
    else:
        valid, missing = validate_looks_like_eoat_project_root(root)
        activities, activity_warning = read_recent_activity(root, limit=10)
        scheduled_status = get_scheduled_report_status(root, check_tasks=False)
        cards = {
            "Active Project Root": str(root),
            "Data Mode": root_status.mode_label,
            "Master Workbook Path": str(root_status.master_workbook),
            "Project Root": "OK" if valid else f"Warning: {len(missing)} issue(s)",
            "Master Workbook": "OK" if paths.master_workbook.exists() else "Missing",
            "Activity Log": "OK" if activities else ("Warning" if activity_warning else "Not checked"),
            "Dashboard Cache": cache_status.warning or "No cache yet",
            "Daily Summary Schedule": scheduled_status.get("daily", {}).get("schedule", "Monday-Thursday at 7:00 PM"),
            "Latest Daily Summary": scheduled_status.get("daily", {}).get("last_report_date") or "No daily summary yet",
            "Missed Daily Summaries": ", ".join(scheduled_status.get("daily", {}).get("missed_dates", []))
            or "None detected",
            "Weekly Summary Schedule": scheduled_status.get("weekly", {}).get("schedule", "Friday at 7:00 PM"),
            "Latest Weekly Summary": scheduled_status.get("weekly", {}).get("last_report_date")
            or "No weekly summary yet",
            "Missed Weekly Summaries": ", ".join(scheduled_status.get("weekly", {}).get("missed_dates", []))
            or "None detected",
        }
        recommendations = [root_status.message]
        lines = ["Showing quick project status. Use Deep Refresh to recompute workbook metrics."]
        if activity_warning:
            lines.append(f"Activity warning: {activity_warning}")
        for entry in activities[:5]:
            lines.append(
                f"- {entry.get('timestamp', '')} | {entry.get('tool_name', '')} | "
                f"{'OK' if entry.get('success') else 'Failed'} | {entry.get('summary', '')}"
            )
        activity_text = "\n".join(lines)

    if cache_status.stale:
        activity_text = f"{cache_status.stale_explanation}\n\n{activity_text}"

    scheduled_status = get_scheduled_report_status(root, check_tasks=False)
    cards["Daily Summary Schedule"] = scheduled_status.get("daily", {}).get("schedule", "Monday-Thursday at 7:00 PM")
    cards["Latest Daily Summary"] = scheduled_status.get("daily", {}).get("last_report_date") or "No daily summary yet"
    cards["Missed Daily Summaries"] = (
        ", ".join(scheduled_status.get("daily", {}).get("missed_dates", [])) or "None detected"
    )
    cards["Weekly Summary Schedule"] = scheduled_status.get("weekly", {}).get("schedule", "Friday at 7:00 PM")
    cards["Latest Weekly Summary"] = (
        scheduled_status.get("weekly", {}).get("last_report_date") or "No weekly summary yet"
    )
    cards["Missed Weekly Summaries"] = (
        ", ".join(scheduled_status.get("weekly", {}).get("missed_dates", [])) or "None detected"
    )
    resolved_day = resolve_project_day_for_project(
        root, project_start_date=project_start_date, skip_weekends=skip_weekends, holidays=holidays or []
    )
    cards["Resolved Project Day"] = f"Week {resolved_day.week} Day {resolved_day.day} from {resolved_day.source}"
    snapshot_out = {
        "project_root": str(root),
        "cards": cards,
        "recommendations": recommendations[:6] or ["Dashboard loaded from quick status."],
        "activity_text": activity_text,
        "root_status_message": root_status.message,
        "resolved_week": resolved_day.week,
        "resolved_day": resolved_day.day,
        "resolved_source": resolved_day.source,
        "resolved_warning": resolved_day.warning,
    }
    cache_state = "stale" if cache_status.cache_hit and stale else "hit" if cache_status.cache_hit else "miss"
    log_performance(
        root,
        "dashboard.quick_refresh",
        time.perf_counter() - started,
        source="home",
        page_tool="home",
        details={
            "cache_status": cache_state,
            "stale_reason_count": len(cache_status.stale_reasons),
            "quick_metadata_only": True,
        },
    )
    return snapshot_out


class HomePage(QWidget):
    project_root_changed = Signal(str)
    navigate_requested = Signal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.project_root_label = QLabel()
        self.project_root_label.setWordWrap(True)
        self.result_panel = ToolRunPanel()
        self.cards: dict[str, StatusCard] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        content_layout.setSpacing(SECTION_SPACING)

        title = QLabel("EOAT Command Center")
        title.setStyleSheet("font-size: 22pt; font-weight: 700;")
        content_layout.addWidget(title)
        self.project_root_label.setStyleSheet("color: #627d98;")
        content_layout.addWidget(self.project_root_label)

        top_actions = QHBoxLayout()
        for label, callback in [
            ("Choose Real Project Folder", self.select_project_root),
            ("Refresh", self.refresh_status),
            ("Deep Refresh", self.deep_refresh_status),
            (
                "Open Project Folder",
                lambda: self.open_path(resolve_project_paths(self.config.project_root).project_root),
            ),
            (
                "Open Activity Log Folder",
                lambda: self.open_path(resolve_project_paths(self.config.project_root).activity_logs),
            ),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            top_actions.addWidget(button)
        top_actions.addStretch(1)
        content_layout.addLayout(top_actions)

        self._add_card_section(
            content_layout,
            "Today's Work",
            [
                "Resolved Project Day",
                "Current Schedule",
                "Not Started",
                "In Progress",
                "Blocked",
                "Complete",
                "Latest Morning Plan",
            ],
        )
        daily_actions = QHBoxLayout()
        self.morning_plan_button = QPushButton("Generate Morning Plan")
        self.morning_plan_button.clicked.connect(self.run_morning_plan)
        daily_actions.addWidget(self.morning_plan_button)
        for label, callback in [
            ("Open Schedule", lambda: self.navigate_requested.emit("schedule")),
            ("Run Daily Start Workflow", lambda: self.run_workflow_action("daily-start")),
            ("Run Daily End Workflow", lambda: self.run_workflow_action("daily-end")),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            daily_actions.addWidget(button)
        daily_actions.addStretch(1)
        content_layout.addLayout(daily_actions)

        self._add_card_section(
            content_layout,
            "Project Health",
            [
                "Data Mode",
                "Active Project Root",
                "Master Workbook Path",
                "Project Root",
                "Master Workbook",
                "Git Status",
                "Workbook Health",
                "Tool Registry",
                "Activity Log",
                "Dashboard Cache",
            ],
        )
        self._add_card_section(
            content_layout,
            "Automation",
            [
                "Daily Summary Schedule",
                "Latest Daily Summary",
                "Missed Daily Summaries",
                "Weekly Summary Schedule",
                "Latest Weekly Summary",
                "Missed Weekly Summaries",
            ],
        )
        self._add_card_section(
            content_layout,
            "Data Progress",
            [
                "EOAT Documentation Rows",
                "Photos Indexed",
                "Interviews Logged",
                "Issues Logged",
                "Documentation Gaps",
                "KPI Rows",
                "Pilot Candidates",
            ],
        )
        self.open_items_panel = OpenItemsPanel(self.config, self.navigate_requested.emit)
        content_layout.addWidget(self.open_items_panel)

        workflow_grid = QGridLayout()
        workflow_cards = [
            WorkflowCard(
                "Capture Data",
                "Add EOAT audits, interview notes, and photos.",
                [
                    ("Add Audit Entry", lambda: self.navigate_requested.emit("audit")),
                    ("Open Notes", lambda: self.navigate_requested.emit("notes")),
                    ("Open Tags", lambda: self.navigate_requested.emit("tags")),
                    ("Intake Photos", lambda: self.navigate_requested.emit("photos")),
                    ("Add Interview Note", lambda: self.navigate_requested.emit("audit")),
                    (
                        "Open Master Workbook",
                        lambda: self.open_path(resolve_project_paths(self.config.project_root).master_workbook),
                    ),
                ],
            ),
            WorkflowCard(
                "Validate & Clean",
                "Check structure, workbook health, and missing documentation.",
                [
                    ("Validate Project Foundation", self.run_validation),
                    ("Run Documentation Gap Scan", self.run_documentation_gap_scan),
                    ("Run Full System Audit", self.run_system_audit),
                ],
            ),
            WorkflowCard(
                "Analyze",
                "Turn audit data into issue, risk, KPI, and pilot insight.",
                [
                    ("Run Issue Analysis", self.run_issue_analysis),
                    ("Run FMEA-Lite Analysis", self.run_fmea_analysis),
                    ("Rank Pilot Candidates", self.run_pilot_ranking),
                    ("Build KPI Dashboard", self.run_kpi_dashboard),
                ],
            ),
            WorkflowCard(
                "Standardize",
                "Generate PM, BOM, and standards outputs.",
                [
                    ("Generate PM Checklist", self.run_pm_checklist),
                    ("Run BOM/Spare Parts Report", self.run_bom_report),
                    ("Open Standards Docs", lambda: self.navigate_requested.emit("standards_docs")),
                ],
            ),
            WorkflowCard(
                "Report & Handoff",
                "Prepare summaries, presentation assets, and final package checks.",
                [
                    ("Generate Weekly Summary", self.run_weekly_summary),
                    ("Generate Mentor Brief", self.run_mentor_brief),
                    ("Generate Presentation Assets", self.run_presentation_assets),
                    ("Build Final Handoff Package", self.run_final_handoff_dry_run),
                ],
            ),
            WorkflowCard(
                "Admin Tools",
                "Setup, backups, registry, and release readiness.",
                [
                    ("Create/Verify Project Structure", self.create_or_verify_project),
                    ("Run Weekly Review Workflow", lambda: self.run_workflow_action("weekly-review")),
                    ("Run Final Review Workflow", lambda: self.run_workflow_action("final-review")),
                    ("Open Tool Registry", lambda: self.navigate_requested.emit("tool_registry")),
                    ("Open Backup Manager", lambda: self.navigate_requested.emit("backup_manager")),
                    ("Open Release Readiness", lambda: self.navigate_requested.emit("release_readiness")),
                ],
            ),
        ]
        for index, card in enumerate(workflow_cards):
            workflow_grid.addWidget(card, index // 3, index % 3)
        content_layout.addWidget(QLabel("Primary Workflows"))
        content_layout.addLayout(workflow_grid)

        self.recommendations_label = QLabel("Recommended next actions will appear after refresh.")
        self.recommendations_label.setWordWrap(True)
        box = QGroupBox("Recommended Next Actions")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.recommendations_label)
        content_layout.addWidget(box)

        self.result_panel.setMaximumHeight(230)
        content_layout.addWidget(QLabel("Recent Activity"))
        content_layout.addWidget(self.result_panel)
        root_status = validate_project_root(self.config.project_root)
        self.project_root_label.setText(
            f"Active project root: {self.config.project_root}\nData mode: {root_status.mode_label}\n{root_status.message}"
        )
        self.result_panel.show_text("Dashboard loaded. Showing quick cached status...")
        if QTimer is not None:
            QTimer.singleShot(0, self.open_items_panel.refresh_async)
            QTimer.singleShot(100, self.refresh_status)

    def _add_card_section(self, layout: QVBoxLayout, title: str, keys: list[str]) -> None:
        label = QLabel(title)
        label.setStyleSheet("font-size: 12pt; font-weight: 700;")
        layout.addWidget(label)
        grid = QGridLayout()
        for index, key in enumerate(keys):
            card = StatusCard(key)
            self.cards[key] = card
            grid.addWidget(card, index // 6, index % 6)
        layout.addLayout(grid)

    def _set_card(self, key: str, value: str) -> None:
        if key in self.cards:
            self.cards[key].set_value(str(value))

    def refresh_status(self) -> None:
        self.result_panel.show_text("Refreshing dashboard quick status from cache and cheap checks...")
        get_task_manager().run_task(
            TaskRequest(
                id="home_quick_refresh",
                name="Dashboard Quick Refresh",
                category="home",
                callable=collect_home_quick_status_snapshot,
                args=(
                    self.config.project_root,
                    self.config.git_executable,
                    self.config.project_start_date,
                    self.config.skip_weekends,
                    self.config.holidays,
                ),
            ),
            on_finished=self._apply_status_result,
        )

    def on_event(self, event) -> bool:
        if getattr(event, "event_type", "") == EVENT_AUDIT_SAVED:
            self.result_panel.show_text(
                "Audit saved. Dashboard cache marked stale; use Refresh when you want updated overview metrics."
            )
            return True
        self.refresh_status()
        return True

    def deep_refresh_status(self) -> None:
        self.result_panel.show_text("Running deep dashboard refresh. Workbook metrics will update in the background...")
        get_task_manager().run_task(
            TaskRequest(
                id="home_deep_refresh",
                name="Dashboard Deep Refresh",
                category="home",
                callable=collect_home_status_snapshot,
                args=(
                    self.config.project_root,
                    self.config.git_executable,
                    self.config.project_start_date,
                    self.config.skip_weekends,
                    self.config.holidays,
                ),
            ),
            on_finished=self._apply_status_result,
        )

    def _apply_status_result(self, task_result) -> None:
        if not task_result.ok:
            self.result_panel.show_text(task_result.message)
            return
        snapshot = task_result.result_data
        self.project_root_label.setText(
            f"Active project root: {snapshot['project_root']}\n"
            f"Data mode: {snapshot['cards'].get('Data Mode', 'Unknown')}\n"
            f"{snapshot.get('root_status_message', '')}"
        )
        for key, value in snapshot["cards"].items():
            self._set_card(key, value)
        if hasattr(self, "open_items_panel"):
            self.open_items_panel.refresh_async()
        self.morning_plan_button.setText(
            f"Generate Morning Plan for Week {snapshot['resolved_week']} Day {snapshot['resolved_day']}"
        )
        self.recommendations_label.setText("\n".join(f"- {item}" for item in snapshot["recommendations"]))
        self.result_panel.show_text(snapshot["activity_text"])

    def select_project_root(self) -> None:
        selected = select_directory(self, "Select EOAT Project Root", self.config.project_root)
        if selected:
            self.config.project_root = selected
            save_config(self.config)
            status = validate_project_root(selected)
            self.result_panel.show_text(status.message)
            self.project_root_changed.emit(selected)
            self.deep_refresh_status()

    def create_or_verify_project(self) -> None:
        from core.project_setup import run_project_setup_safe

        root = Path(self.config.project_root)
        if root.exists():
            answer = QMessageBox.question(
                self,
                "Create/Verify Project Structure",
                "This will run setup in safe mode for the selected project root. Existing files, reports, and workbooks will be left unchanged. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._run_tool_task(
            "home_project_setup",
            "Create/Verify Project Structure",
            lambda: run_project_setup_safe(root),
            modifies_files=True,
        )

    def run_validation(self) -> None:
        from core.validation import run_foundation_validation

        self._run_tool_task(
            "home_foundation_validation",
            "Foundation Validation",
            lambda: run_foundation_validation(self.config.project_root),
            modifies_files=True,
        )

    def generate_audit_progress_report(self) -> None:
        from core.audit_progress import generate_audit_progress_report

        self._run_tool_task(
            "home_audit_progress",
            "Audit Progress Report",
            lambda: generate_audit_progress_report(self.config.project_root),
            modifies_files=True,
        )

    def run_issue_analysis(self) -> None:
        from core.issue_analysis import generate_issue_analysis_report

        self._run_tool_task(
            "home_issue_analysis",
            "Issue Analysis",
            lambda: generate_issue_analysis_report(self.config.project_root),
            modifies_files=True,
        )

    def run_documentation_gap_scan(self) -> None:
        from core.documentation_gaps import generate_documentation_gap_report

        self._run_tool_task(
            "home_documentation_gap",
            "Documentation Gap Scan",
            lambda: generate_documentation_gap_report(self.config.project_root),
            modifies_files=True,
        )

    def run_fmea_analysis(self) -> None:
        from core.fmea_analysis import generate_fmea_report

        self._run_tool_task(
            "home_fmea",
            "FMEA-Lite Analysis",
            lambda: generate_fmea_report(self.config.project_root),
            modifies_files=True,
        )

    def run_pilot_ranking(self) -> None:
        from core.pilot_scoring import generate_pilot_ranking_report

        self._run_tool_task(
            "home_pilot_ranking",
            "Pilot Candidate Ranking",
            lambda: generate_pilot_ranking_report(self.config.project_root),
            modifies_files=True,
        )

    def run_kpi_dashboard(self) -> None:
        from core.kpi_analysis import generate_kpi_dashboard_report

        self._run_tool_task(
            "home_kpi_dashboard",
            "KPI Dashboard Report",
            lambda: generate_kpi_dashboard_report(self.config.project_root),
            modifies_files=True,
        )

    def run_morning_plan(self) -> None:
        from core.morning_planner import generate_morning_plan

        self._run_tool_task(
            "home_morning_plan",
            "Morning Plan",
            lambda: generate_morning_plan(
                self.config.project_root,
                detail_level="todo",
                project_start_date=self.config.project_start_date,
                skip_weekends=self.config.skip_weekends,
                holidays=self.config.holidays,
                manual_override=False,
            ),
            modifies_files=True,
        )

    def run_weekly_summary(self) -> None:
        from core.weekly_summary import generate_weekly_summary

        weeks = available_schedule_weeks(self.config.project_root)
        week = weeks[0] if weeks else 1
        self._run_tool_task(
            "home_weekly_summary",
            "Weekly Summary",
            lambda: generate_weekly_summary(self.config.project_root, week=week),
            modifies_files=True,
        )

    def run_mentor_brief(self) -> None:
        from core.mentor_brief import generate_mentor_brief

        self._run_tool_task(
            "home_mentor_brief",
            "Mentor Brief",
            lambda: generate_mentor_brief(self.config.project_root, days=7),
            modifies_files=True,
        )

    def run_pm_checklist(self) -> None:
        from core.pm_checklists import generate_pm_checklists

        self._run_tool_task(
            "home_pm_checklist",
            "PM Checklist",
            lambda: generate_pm_checklists(self.config.project_root, generic=True),
            modifies_files=True,
        )

    def run_bom_report(self) -> None:
        from core.bom_standardization import generate_bom_standardization_report

        self._run_tool_task(
            "home_bom_report",
            "BOM/Spare Parts Report",
            lambda: generate_bom_standardization_report(self.config.project_root),
            modifies_files=True,
        )

    def run_final_deliverable_check(self) -> None:
        from core.deliverable_check import run_final_deliverable_check

        self._run_tool_task(
            "home_final_deliverable_check",
            "Final Deliverable Check",
            lambda: run_final_deliverable_check(self.config.project_root),
            modifies_files=True,
        )

    def run_presentation_assets(self) -> None:
        from core.presentation_export import export_presentation_assets

        self._run_tool_task(
            "home_presentation_assets",
            "Presentation Assets",
            lambda: export_presentation_assets(self.config.project_root),
            modifies_files=True,
        )

    def run_final_summary(self) -> None:
        from core.final_summary import generate_final_project_summary

        self._run_tool_task(
            "home_final_summary",
            "Final Summary Draft",
            lambda: generate_final_project_summary(self.config.project_root),
            modifies_files=True,
        )

    def run_final_handoff_dry_run(self) -> None:
        from core.final_handoff import build_final_handoff_package

        self._run_tool_task(
            "home_final_handoff_dry_run",
            "Final Handoff Dry Run",
            lambda: build_final_handoff_package(self.config.project_root, dry_run=True),
            modifies_files=False,
        )

    def run_system_audit(self) -> None:
        from core.system_audit import run_system_audit

        self._run_tool_task(
            "home_system_audit",
            "Full System Audit",
            lambda: run_system_audit(self.config.project_root, check_cli_help=False),
            modifies_files=True,
        )

    def run_workflow_action(self, workflow: str) -> None:
        from core.workflows import run_workflow

        resolved_day = resolve_project_day_for_project(
            self.config.project_root,
            project_start_date=self.config.project_start_date,
            skip_weekends=self.config.skip_weekends,
            holidays=self.config.holidays,
        )
        self._run_tool_task(
            f"home_workflow_{workflow}",
            f"{workflow.replace('-', ' ').title()} Workflow",
            lambda: run_workflow(self.config.project_root, workflow, week=resolved_day.week, day=resolved_day.day),
            modifies_files=True,
        )

    def open_path(self, path: Path) -> None:
        result = open_path(path)
        if not result.success:
            self.result_panel.show_result(result)

    def _run_tool_task(
        self, task_id: str, name: str, func, modifies_files: bool = False, workbook_lock: bool = False
    ) -> None:
        self.result_panel.show_text(f"Running: {name}...")
        get_task_manager().run_task(
            TaskRequest(
                id=task_id,
                name=name,
                category="home",
                callable=func,
                modifies_files=modifies_files,
                requires_project_lock=modifies_files,
                requires_workbook_lock=workbook_lock,
            ),
            on_finished=self._show_tool_task_result,
        )

    def _show_tool_task_result(self, task_result) -> None:
        self.result_panel.show_result(task_result.to_tool_result())
        self.refresh_status()
