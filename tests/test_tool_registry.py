from __future__ import annotations

from core.tool_registry import ToolRegistry


def test_tool_registry_loads_seed_data():
    registry = ToolRegistry.load()
    tools = registry.list_tools()

    assert len(tools) >= 16
    assert registry.get("workbook_validator") is not None
    assert registry.get("final_handoff_builder") is not None
    assert registry.get("foundation_validation").implementation_status == "implemented"
    assert registry.get("daily_status_summary").implementation_status == "implemented"


def test_tool_registry_contains_all_planned_phase_tools():
    registry = ToolRegistry.load()
    names = {tool.name for tool in registry.list_tools()}
    planned = {
        "EOAT Audit Form Tool",
        "EOAT Photo Intake and Renaming Tool",
        "EOAT Workbook Validator",
        "Weekly Summary Generator",
        "KPI Dashboard Builder",
        "FMEA-Lite Builder",
        "Pilot Candidate Ranking Tool",
        "EOAT PM Checklist Generator",
        "BOM and Spare Parts Standardization Tool",
        "EOAT Documentation Gap Scanner",
        "EOAT Audit Progress Dashboard Tool",
        "Mentor Meeting Prep Tool",
        "Operator/Technician Interview Form Tool",
        "Daily What Should I Work On? Morning Planner",
        "Final Presentation Builder Helper",
    }

    assert planned.issubset(names)
