"""Keep inherited Ruff debt visible while rejecting new diagnostics.

CI generates its baseline from the exact base commit for each run.  It is not
an ignore list: CI emits every inherited finding as a warning and uploads the
complete current report.  A candidate fails only when it adds a new finding.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _fingerprint(item: dict[str, Any]) -> tuple[str, str, int, int, str]:
    location = item.get("location") or {}
    return (
        str(item.get("filename", "")).replace("\\", "/"),
        str(item.get("code", "")),
        int(location.get("row", 0)),
        int(location.get("column", 0)),
        str(item.get("message", "")),
    )


def _read_inventory(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Ruff inventory is unreadable: {path}") from exc
    diagnostics = payload.get("diagnostics") if isinstance(payload, dict) else payload
    if not isinstance(diagnostics, list) or not all(isinstance(item, dict) for item in diagnostics):
        raise ValueError(f"Ruff inventory has an invalid diagnostic list: {path}")
    return diagnostics


def _write_inventory(path: Path, diagnostics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "diagnostics": sorted(diagnostics, key=_fingerprint)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _emit(level: str, item: dict[str, Any]) -> None:
    filename, code, row, column, message = _fingerprint(item)
    print(f"::{level} file={filename},line={row},col={column},title=Ruff {code}::{message}")


def _run_ruff(root: Path, config: Path | None = None) -> list[dict[str, Any]]:
    command = [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"]
    if config is not None:
        command.extend(["--config", str(config)])
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or "Ruff could not complete.")
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ruff did not produce JSON output.") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RuntimeError("Ruff produced an invalid diagnostic list.")
    for item in payload:
        filename = Path(str(item.get("filename", "")))
        try:
            item["filename"] = filename.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise RuntimeError("Ruff reported a diagnostic outside the repository root.") from exc
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ruff-config", type=Path)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    current = _run_ruff(root, args.ruff_config)
    if args.write_baseline:
        _write_inventory(args.baseline, current)
        print(f"Wrote Ruff baseline with {len(current)} diagnostics to {args.baseline}.")
        return 0
    baseline = _read_inventory(args.baseline)
    current_by_key = {_fingerprint(item): item for item in current}
    baseline_keys = {_fingerprint(item) for item in baseline}
    introduced = [current_by_key[key] for key in sorted(current_by_key.keys() - baseline_keys)]
    inherited = [current_by_key[key] for key in sorted(current_by_key.keys() & baseline_keys)]
    resolved = sorted(baseline_keys - current_by_key.keys())
    if args.report:
        _write_inventory(args.report, current)
    print(
        f"Ruff inventory: {len(current)} current; {len(inherited)} inherited; "
        f"{len(introduced)} introduced; {len(resolved)} resolved."
    )
    for item in inherited:
        _emit("warning", item)
    for item in introduced:
        _emit("error", item)
    if introduced:
        print("Ruff delta gate failed: new diagnostics require remediation or an approved baseline refresh.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
