from __future__ import annotations

from pathlib import Path

APP_NAME = "EOAT Command Center"
TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = TOOLKIT_ROOT / "examples" / "demo_project"
DEFAULT_CONFIG_PATH = TOOLKIT_ROOT / "config" / "local_config.json"
LEGACY_CONFIG_PATH = TOOLKIT_ROOT / "config" / "user_config.json"
CONFIG_EXAMPLE_PATH = TOOLKIT_ROOT / "config" / "config.example.json"
DEFAULT_GIT_EXECUTABLE = Path("git")

EXPECTED_NUMBERED_FOLDERS = [
    "00_Project_Admin",
    "01_EOAT_Audit",
    "02_KPI_Data",
    "03_Standards",
    "04_FMEA",
    "05_Pilot_Project",
    "06_Final_Handoff",
]

EXPECTED_WORKBOOK_RELATIVE = (
    "01_EOAT_Audit",
    "EOAT_Audit_Database",
    "EOAT_Master_Tracker.xlsx",
)

DEFAULT_MASTER_PRESS_LIST_FILE = "master_press_list.xlsx"
DEFAULT_PRESS_CAPACITY_FILE = "press_capacity.xlsx"
