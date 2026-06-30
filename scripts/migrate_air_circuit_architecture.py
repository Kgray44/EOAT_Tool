from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.audit_entries import migrate_air_circuit_architecture
from core.config import load_config


def _default_project_root() -> str:
    config_root = Path(load_config().project_root)
    if config_root.exists():
        return str(config_root)
    standard_project = ROOT / "EOAT_Standardization_Project"
    if standard_project.exists():
        return str(standard_project)
    return str(ROOT / "examples" / "demo_project")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate EOAT air circuit architecture workbook columns and rows.")
    parser.add_argument(
        "project_root",
        nargs="?",
        default=_default_project_root(),
        help="Project root containing 01_EOAT_Audit/EOAT_Audit_Database/EOAT_Master_Tracker.xlsx.",
    )
    args = parser.parse_args()
    result = migrate_air_circuit_architecture(args.project_root)
    print(result.summary)
    for detail in result.details:
        print(f"- {detail}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    if result.errors:
        print("Errors:")
        for error in result.errors:
            print(f"- {error}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
