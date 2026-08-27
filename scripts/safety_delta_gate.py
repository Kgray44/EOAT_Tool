"""Keep inherited repository-safety findings visible while rejecting new blockers.

The auditor policy is loaded from the exact base commit and must be byte-for-byte
identical in the candidate. This prevents a pull request from changing its way
out of the safety gate while allowing pre-existing findings to remain visible.
"""

from __future__ import annotations

import argparse
import filecmp
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_auditor(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("base_repo_safety_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load repository safety auditor: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _normalize_finding(finding: Any, root: Path) -> dict[str, Any]:
    try:
        filename = Path(finding.path).resolve().relative_to(root).as_posix()
    except (AttributeError, ValueError) as exc:
        raise RuntimeError("Safety auditor returned a finding outside the repository root.") from exc
    return {
        "severity": str(finding.severity),
        "filename": filename,
        "line": int(finding.line or 0),
        "message": str(finding.message),
    }


def _sort_key(item: dict[str, Any]) -> tuple[str, str, int, str]:
    return (str(item["severity"]), str(item["filename"]), int(item["line"]), str(item["message"]))


def _fingerprint(item: dict[str, Any]) -> tuple[str, str, str]:
    return (str(item["severity"]), str(item["filename"]), str(item["message"]))


def _audit(root: Path, safety_script: Path) -> list[dict[str, Any]]:
    module = _load_auditor(safety_script)
    policy_relative = (Path("scripts") / safety_script.name).as_posix()
    findings = [_normalize_finding(finding, root) for finding in module.audit_repo(root)]
    # The upstream auditor intentionally skips its own source. When running the
    # base policy against the candidate, retain that same exclusion. The gate
    # separately fails if the candidate changes this policy file.
    return [item for item in findings if item["filename"] != policy_relative]


def _read_inventory(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Safety inventory is unreadable: {path}") from exc
    diagnostics = payload.get("findings") if isinstance(payload, dict) else payload
    if not isinstance(diagnostics, list) or not all(isinstance(item, dict) for item in diagnostics):
        raise ValueError(f"Safety inventory has an invalid finding list: {path}")
    return diagnostics


def _write_inventory(path: Path, findings: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "findings": sorted(findings, key=_sort_key)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compare(
    baseline: list[dict[str, Any]], current: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    baseline_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    current_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in baseline:
        baseline_by_key[_fingerprint(item)].append(item)
    for item in current:
        current_by_key[_fingerprint(item)].append(item)
    inherited: list[dict[str, Any]] = []
    introduced: list[dict[str, Any]] = []
    resolved = 0
    for key in sorted(baseline_by_key.keys() | current_by_key.keys()):
        base_items = sorted(baseline_by_key[key], key=_sort_key)
        current_items = sorted(current_by_key[key], key=_sort_key)
        shared = min(len(base_items), len(current_items))
        inherited.extend(current_items[:shared])
        introduced.extend(current_items[shared:])
        resolved += len(base_items) - shared
    return inherited, introduced, resolved


def _emit(level: str, item: dict[str, Any]) -> None:
    print(
        f"::{level} file={item['filename']},line={item['line']},"
        f"title=Safety audit {item['severity']}::{item['message']}"
    )


def _candidate_policy_path(root: Path, safety_script: Path) -> Path:
    return root / "scripts" / safety_script.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--safety-script", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    safety_script = args.safety_script.resolve()
    if not safety_script.is_file():
        raise ValueError(f"Safety auditor does not exist: {safety_script}")
    current = _audit(root, safety_script)
    if args.write_baseline:
        _write_inventory(args.baseline, current)
        print(f"Wrote safety baseline with {len(current)} findings to {args.baseline}.")
        return 0
    candidate_policy = _candidate_policy_path(root, safety_script)
    if not candidate_policy.is_file() or not filecmp.cmp(safety_script, candidate_policy, shallow=False):
        raise RuntimeError("Candidate changes the repository safety policy; that requires separate security review.")
    baseline = _read_inventory(args.baseline)
    inherited, introduced, resolved = _compare(baseline, current)
    if args.report:
        _write_inventory(args.report, current)
    blockers = [item for item in introduced if item["severity"] == "BLOCKER"]
    print(
        f"Safety inventory: {len(current)} current; {len(inherited)} inherited; "
        f"{len(introduced)} introduced; {resolved} resolved; {len(blockers)} introduced blockers."
    )
    for item in inherited:
        _emit("warning", item)
    for item in introduced:
        _emit("error" if item["severity"] == "BLOCKER" else "warning", item)
    if blockers:
        print("Safety delta gate failed: new blocker findings require remediation.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
