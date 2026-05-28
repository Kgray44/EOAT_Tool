from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook

from core.workbook_schema import get_expected_headers, get_expected_sheets


def _row(sheet_name: str, values: dict[str, Any]) -> list[Any]:
    return [values.get(header, "") for header in get_expected_headers(sheet_name)]


def create_fake_master_workbook(path: str | Path) -> Path:
    workbook_path = Path(path)
    workbook_path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in get_expected_sheets():
        ws = workbook.create_sheet(sheet_name)
        ws.append(get_expected_headers(sheet_name))

    inventory = workbook["EOAT Inventory"]
    inventory.append(
        _row(
            "EOAT Inventory",
            {
                "Audit ID": "AUD-20260518-001",
                "Audit Date": "2026-05-18",
                "Auditor": "Fake Intern",
                "Plant/Area": "Molding",
                "Press/Machine #": "Press 101",
                "Robot Type": "Wittmann R9",
                "Robot Model/Controller": "Wittmann R9 / R8 controller",
                "Tool #": "TOOL-A",
                "Part Family": "Part family A",
                "Part Name/Description": "Vacuum EOAT family A sample",
                "Cleanroom/Non-Cleanroom": "Non-cleanroom",
                "EOAT Type": "Vacuum",
                "Number of Parts Picked": 8,
                "# of Cups": 8,
                "Cup Type/Material": "Nitrile bellows cup",
                "Cup Diameter/Size": "20 mm",
                "Vacuum Generator Type": "Venturi",
                "EOAT Vacuum Circuits": "2",
                "Sensors Present?": "Yes",
                "Sensor Type": "Vacuum switch",
                "Sensor Brand/Model": "SMC ZSE20",
                "Vacuum Confirmation Present?": "Yes",
                "Part-Present Detection Present?": "Yes",
                "Quick Disconnects Present?": "Yes",
                "Pneumatic Quick Disconnect Type": "Push-to-connect",
                "Electrical Quick Disconnect Type": "M12",
                "Tubing Condition": "Leaking",
                "Tubing Routing Notes": "Tubing wear near wrist rotation.",
                "Cable Management Condition": "Loose",
                "Mounting Hardware Condition": "Good",
                "EOAT Alignment Condition": "Needs verification",
                "Fastener/Locking Hardware Present?": "Yes",
                "Known Issues": "Vacuum loss; part drops; tubing wear",
                "Drop/Mis-Pick History": "Recurring part drops on startup.",
                "Maintenance Frequency": "Weekly",
                "Cycle Time Concern?": "Yes",
                "Scrap/Quality Concern?": "Yes",
                "Changeover Difficulty": "Medium",
                "Spare Parts Identified?": "Yes",
                "Drawing/CAD Available?": "Yes",
                "BOM Available?": "Yes",
                "Process Binder Complete?": "Yes",
                "Photos Taken?": "Yes",
                "Photo Folder/Link": "01_EOAT_Audit/Cell_Photos/Overall",
                "Status": "Candidate for pilot",
                "Priority": "High",
                "Pilot Candidate?": "Yes",
                "Follow-Up Needed": "Yes",
                "Notes": "Known issue cell with strong pilot potential.",
            },
        )
    )
    inventory.append(
        _row(
            "EOAT Inventory",
            {
                "Audit ID": "AUD-20260518-002",
                "Audit Date": "2026-05-18",
                "Auditor": "Fake Intern",
                "Plant/Area": "Molding",
                "Press/Machine #": "Press 102",
                "Robot Type": "Engel Viper",
                "Robot Model/Controller": "Engel Viper 20",
                "Tool #": "TOOL-B",
                "Part Family": "Part family B",
                "Part Name/Description": "Gripper EOAT family B sample",
                "EOAT Type": "Mechanical gripper",
                "# of Cups": "N/A",
                "# of Grippers": 2,
                "Gripper Type": "Single Pressure",
                "Gripper Model": "MHZL2-10S",
                "Sensors Present?": "Yes",
                "Sensor Type": "Part-present sensor",
                "Tubing Condition": "Good",
                "Cable Management Condition": "Good",
                "Mounting Hardware Condition": "Good",
                "EOAT Alignment Condition": "Good",
                "Known Issues": "Sensor failure during intermittent cable flex.",
                "Maintenance Frequency": "Monthly",
                "Spare Parts Identified?": "Yes",
                "Drawing/CAD Available?": "No",
                "BOM Available?": "No",
                "Process Binder Complete?": "No",
                "Photos Taken?": "No",
                "Status": "Audited",
                "Priority": "Medium",
                "Pilot Candidate?": "Maybe",
                "Follow-Up Needed": "Yes",
                "Notes": "Missing documentation fields are intentional fake data.",
            },
        )
    )
    inventory.append(
        _row(
            "EOAT Inventory",
            {
                "Audit ID": "AUD-20260518-003",
                "Audit Date": "2026-05-18",
                "Auditor": "Fake Intern",
                "Plant/Area": "Molding",
                "Press/Machine #": "Press 103",
                "Robot Type": "Other",
                "Robot Model/Controller": "Hybrid robot",
                "Tool #": "TOOL-C",
                "Part Family": "Part family C",
                "Part Name/Description": "Hybrid EOAT family C sample",
                "EOAT Type": "Hybrid",
                "Number of Parts Picked": 4,
                "# of Cups": 4,
                "Cup Type/Material": "Silicone flat cup",
                "# of Grippers": 1,
                "Gripper Type": "Double Pressure",
                "Gripper Model": "MHZL2-16D",
                "Sensors Present?": "Yes",
                "Sensor Type": "Vacuum and part-present",
                "Tubing Condition": "Fair",
                "Cable Management Condition": "Good",
                "Mounting Hardware Condition": "Good",
                "EOAT Alignment Condition": "Good",
                "Known Issues": "Cable management issue previously corrected.",
                "Maintenance Frequency": "Monthly",
                "Spare Parts Identified?": "Yes",
                "Drawing/CAD Available?": "Yes",
                "BOM Available?": "Yes",
                "Process Binder Complete?": "Yes",
                "Photos Taken?": "Yes",
                "Status": "Audited",
                "Priority": "Low",
                "Pilot Candidate?": "No",
                "Follow-Up Needed": "No",
                "Notes": "Complete documentation control row.",
            },
        )
    )

    issue_log = workbook["Issue Log"]
    for values in [
        {
            "Issue ID": "ISS-001",
            "Date Found": "2026-05-18",
            "Plant/Area": "Molding",
            "Press/Machine #": "Press 101",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Issue Category": "Vacuum loss",
            "Issue Description": "Vacuum drops during robot transfer.",
            "Suspected Cause": "Worn cups and tubing leak",
            "Evidence/Observation": "Audible leak and drop history.",
            "Impact": "Downtime and scrap",
            "Severity": 8,
            "Frequency": 7,
            "Detectability": 4,
            "Temporary Fix": "Replace cup",
            "Recommended Permanent Fix": "Standardize cup and tubing route",
            "Assigned To": "Maintenance",
            "Status": "Open",
            "Follow-Up Date": "2026-05-21",
            "Notes": "High RPN seed data.",
        },
        {
            "Issue ID": "ISS-002",
            "Date Found": "2026-05-18",
            "Plant/Area": "Molding",
            "Press/Machine #": "Press 102",
            "Robot Type": "Engel Viper",
            "EOAT Type": "Mechanical gripper",
            "Issue Category": "Sensor failure",
            "Issue Description": "Part-present signal intermittent.",
            "Suspected Cause": "Cable flex near wrist",
            "Evidence/Observation": "Signal dropout during cycle.",
            "Impact": "Mis-picks",
            "Status": "Open",
            "Notes": "Missing risk numbers are intentional.",
        },
        {
            "Issue ID": "ISS-003",
            "Date Found": "2026-05-18",
            "Plant/Area": "Molding",
            "Press/Machine #": "Press 101",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Issue Category": "Tubing wear",
            "Issue Description": "Tubing rubs on bracket.",
            "Severity": 5,
            "Frequency": 6,
            "Detectability": 5,
            "Status": "In progress",
        },
    ]:
        issue_log.append(_row("Issue Log", values))

    kpis = workbook["KPI Baseline"]
    for values in [
        {
            "KPI ID": "KPI-001",
            "Date": "2026-05-18",
            "Plant/Area": "Molding",
            "Press/Machine #": "Press 101",
            "Tool #": "TOOL-A",
            "Part Family": "Part family A",
            "EOAT Type": "Vacuum",
            "Downtime Minutes": 42,
            "EOAT-Related Downtime?": "Yes",
            "Part Drops": 9,
            "Mis-Picks": 3,
            "Scrap Quantity": 14,
            "Scrap Reason": "Part drops",
            "Cycle Time": 18.4,
            "Maintenance Event Count": 3,
            "Data Source": "Fake MES extract",
        },
        {
            "KPI ID": "KPI-002",
            "Date": "2026-05-18",
            "Plant/Area": "Molding",
            "Press/Machine #": "Press 102",
            "Tool #": "TOOL-B",
            "Part Family": "Part family B",
            "EOAT Type": "Mechanical gripper",
            "Downtime Minutes": 17,
            "EOAT-Related Downtime?": "Yes",
            "Part Drops": 1,
            "Mis-Picks": 7,
            "Scrap Quantity": 4,
            "Cycle Time": 21.0,
            "Maintenance Event Count": 2,
            "Data Source": "Fake shift notes",
        },
        {"KPI ID": "KPI-003", "Date": "2026-05-18", "Press/Machine #": "Press 103"},
    ]:
        kpis.append(_row("KPI Baseline", values))

    workbook["Interview Notes"].append(
        _row(
            "Interview Notes",
            {
                "Interview ID": "INT-001",
                "Date": "2026-05-18",
                "Person Interviewed": "Synthetic Technician",
                "Role/Department": "Maintenance",
                "Shift": "A",
                "Plant/Area": "Molding",
                "Press/Machine #": "Press 101",
                "Main Question/Topic": "Vacuum EOAT recurring issues",
                "Notes": "Vacuum loss and tubing wear are repeat problems.",
                "Known EOAT Issues Mentioned": "Vacuum loss; part drops; tubing wear",
                "Suggested Improvements": "Standard tubing route and cup selection.",
                "Follow-Up Needed": "Yes",
                "Follow-Up Owner": "Fake Intern",
            },
        )
    )

    workbook["Pilot Candidates"].append(
        _row(
            "Pilot Candidates",
            {
                "Candidate ID": "PILOT-001",
                "Date Added": "2026-05-18",
                "Plant/Area": "Molding",
                "Press/Machine #": "Press 101",
                "Robot Type": "Wittmann R9",
                "Tool #": "TOOL-A",
                "Part Family": "Part family A",
                "EOAT Type": "Vacuum",
                "Main Problem": "Vacuum loss and part drops",
                "Evidence": "Issue log and KPI downtime",
                "Estimated Impact": "High",
                "Ease of Implementation": "Medium",
                "Safety/Quality Risk": "Medium",
                "Required Parts/Resources": "Vacuum cups, tubing, fittings",
                "Expected KPI Improvement": "Reduce drops and downtime",
                "Recommended Action": "Pilot standard vacuum-cup and tubing kit",
                "Approval Status": "Proposed",
                "Notes": "Intentionally strong candidate.",
            },
        )
    )

    for values in [
        {
            "FMEA ID": "FMEA-001",
            "Plant/Area": "Molding",
            "Press/Machine #": "Press 101",
            "EOAT Function": "Grip part by vacuum",
            "Failure Mode": "Vacuum loss",
            "Failure Effect": "Part drops",
            "Potential Cause": "Worn cup or tubing leak",
            "Current Controls": "Operator visual check",
            "Severity": 8,
            "Frequency": 7,
            "Detectability": 4,
            "RPN": 224,
            "Recommended Action": "Standardize cup/tubing PM interval",
            "Owner": "Maintenance",
            "Status": "Open",
        },
        {
            "FMEA ID": "FMEA-002",
            "Plant/Area": "Molding",
            "Press/Machine #": "Press 102",
            "EOAT Function": "Confirm part present",
            "Failure Mode": "Sensor failure",
            "Failure Effect": "Mis-pick",
            "Potential Cause": "Cable flex",
            "Status": "Draft",
        },
    ]:
        workbook["FMEA Draft"].append(_row("FMEA Draft", values))

    workbook["Action Items"].append(
        _row(
            "Action Items",
            {
                "Action ID": "ACT-001",
                "Date Added": "2026-05-18",
                "Action Item": "Follow up on Press 101 tubing wear.",
                "Related Cell/Press": "Press 101",
                "Owner": "Fake Intern",
                "Priority": "High",
                "Due Date": "2026-05-21",
                "Status": "In progress",
                "Notes": "Carryover action item for morning plan.",
            },
        )
    )

    workbook["Photo Index"].append(
        _row(
            "Photo Index",
            {
                "Photo ID": "PHO-20260518-001",
                "Date Taken": "2026-05-18",
                "Plant/Area": "Molding",
                "Press/Machine #": "Press 101",
                "EOAT Area Shown": "Overall",
                "Photo Filename": "Molding_Press101_EOAT_2026-05-18_Overall_001.png",
                "Folder Path": "01_EOAT_Audit/Cell_Photos/Overall",
                "Description": "Fake indexed photo.",
                "Related Audit ID": "AUD-20260518-001",
                "Notes": "Seed row.",
            },
        )
    )

    workbook.save(workbook_path)
    workbook.close()
    return workbook_path
