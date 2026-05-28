from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.command_registry import build_dashboard_command_registry
from app.feature_registry import build_feature_registry
from scripts.repo_safety_audit import audit_repo


@dataclass
class _Config:
    project_root: str


class _SmokeWindow:
    def __init__(self, project_root: str | Path):
        self.config = _Config(str(project_root))
        self.pages = {}
        self.navigated: list[str] = []

    def navigate_to_page(self, page_key: str) -> None:
        self.navigated.append(page_key)


def run_registry_checks(project_root: str | Path = REPO_ROOT) -> list[str]:
    feature_registry = build_feature_registry()
    command_registry = build_dashboard_command_registry(_SmokeWindow(project_root))
    command_ids = [command.command_id for command in command_registry.commands]
    findings = feature_registry.validate(command_ids=command_ids)
    for required in ["home", "audit", "reports", "settings"]:
        if feature_registry.get(required) is None:
            findings.append(f"Required feature is missing: {required}")
    return findings


def run_safety_checks(repo_root: str | Path = REPO_ROOT) -> list[str]:
    return [finding.format(Path(repo_root)) for finding in audit_repo(repo_root)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local CI smoke checks for registries and repository safety.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to inspect.")
    parser.add_argument("--registry-only", action="store_true", help="Skip repository safety audit.")
    args = parser.parse_args(argv)

    root = Path(args.root)
    findings = run_registry_checks(root)
    if not args.registry_only:
        findings.extend(run_safety_checks(root))
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        return 1
    print("CI smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
