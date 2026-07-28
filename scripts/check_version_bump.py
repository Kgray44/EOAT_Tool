from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_tools.versioning import (  # noqa: E402
    CANONICAL_VERSION_PATH,
    RELEASE_LEDGER_PATH,
    Version,
    application_change_paths,
    canonical_version_from_payload,
    read_json_object,
    validate_version_sources,
)


def _git(root: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if check and completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout


def _reader_from_git(root: Path, revision: str) -> Callable[[Path], bytes]:
    def read(relative: Path) -> bytes:
        completed = subprocess.run(
            ["git", "show", f":{relative.as_posix()}" if revision == ":" else f"{revision}:{relative.as_posix()}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise OSError(completed.stderr.decode(errors="replace").strip())
        return completed.stdout

    return read


def _version_at(root: Path, revision: str) -> Version:
    data = _reader_from_git(root, revision)(CANONICAL_VERSION_PATH)
    return canonical_version_from_payload(read_json_object(data, source=f"{revision}:{CANONICAL_VERSION_PATH}"))


def _ledger_versions(read_bytes: Callable[[Path], bytes]) -> list[Version]:
    payload = read_json_object(read_bytes(RELEASE_LEDGER_PATH), source=str(RELEASE_LEDGER_PATH))
    releases = payload.get("releases")
    if not isinstance(releases, list):
        raise ValueError("Release ledger has no releases list")
    return [Version.parse(str(item.get("application_version", ""))) for item in releases if isinstance(item, dict)]


def _event_baseline() -> str | None:
    explicit = os.environ.get("EOAT_VERSION_BASE", "").strip()
    if explicit:
        return explicit
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if event_path:
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
            pull_base = payload.get("pull_request", {}).get("base", {}).get("sha")
            before = payload.get("before")
            candidate = pull_base or before
            if candidate and set(str(candidate)) != {"0"}:
                return str(candidate)
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    return None


def _changed_paths(root: Path, base: str, *, staged: bool) -> list[str]:
    if staged:
        output = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", base)
        return [line for line in output.splitlines() if line]
    output = _git(root, "diff", "--name-only", "--diff-filter=ACMR", base)
    paths = [line for line in output.splitlines() if line]
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(paths + untracked))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enforce EOAT Atlas application version increments")
    parser.add_argument("--base", help="Git baseline; defaults to CI base or HEAD~1")
    parser.add_argument("--staged", action="store_true", help="Validate the staged snapshot against HEAD")
    parser.add_argument("--skip-change-check", action="store_true", help="Validate metadata consistency only")
    parser.add_argument("--allow-governed-component-change", action="store_true", help="Permit the explicitly governed 0.24.0 signing/trust component foundation without a second product release")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    try:
        if args.staged:
            current = validate_version_sources(root, read_bytes=_reader_from_git(root, ":"))
        else:
            current = validate_version_sources(root)
        if args.skip_change_check:
            print(f"PASS: EOAT Atlas version metadata is consistent at {current}.")
            return 0
        base = args.base or ("HEAD" if args.staged else _event_baseline() or "HEAD~1")
        baseline = _version_at(root, base)
        changed = _changed_paths(root, base, staged=args.staged)
        application_paths = application_change_paths(changed)
        if current < baseline:
            raise ValueError(f"Application version decreased from {baseline} to {current}")
        governed_component_paths = (
            "deployment/convergence/production_signing.py",
            "deployment/convergence/cli.py",
            "deployment/convergence/release_set.py",
            "deployment/convergence/sealing.py",
            "deployment/convergence/services.py",
            "deployment/convergence/phase1c.py",
            "deployment/web_release.py",
            "EOAT_Atlas_Bootstrap.spec",
            "EOAT_Atlas_Launcher.spec",
            "bootstrap/cli.py",
            "launcher/default_config.json",
            "installer/installer_config.json",
            "installer/Build_Installer_Exe.ps1",
            "release_trust/",
            "scripts/check_version_bump.py",
            "scripts/export_windows_attachment.py",
            "github/workflows/unified-release-train-final-integration.yml",
        )
        governed_component_change = args.allow_governed_component_change and current == baseline == Version.parse("0.24.0") and application_paths and all(path.startswith(governed_component_paths) for path in application_paths)
        if application_paths and current == baseline and not governed_component_change:
            sample = "\n  ".join(application_paths[:20])
            raise ValueError(
                "Application files changed, but the EOAT Atlas version did not change.\n\n"
                f"Baseline version: {baseline}\nCurrent version:  {current}\nChanged application files:\n  {sample}\n\n"
                "Run one of:\n  python scripts\\bump_version.py patch\n"
                "  python scripts\\bump_version.py minor\n  python scripts\\bump_version.py major"
            )
        if not application_paths and current > baseline:
            raise ValueError("EOAT Atlas version changed even though no application files changed")
        try:
            baseline_ledger = _ledger_versions(_reader_from_git(root, base))
        except (OSError, ValueError):
            baseline_ledger = []
        current_reader = _reader_from_git(root, ":") if args.staged else lambda path: (root / path).read_bytes()
        current_ledger = _ledger_versions(current_reader)
        if baseline_ledger:
            added = current_ledger[len(baseline_ledger) :]
            if application_paths and not governed_component_change and len(added) != 1:
                raise ValueError(
                    f"A modifying task must finalize exactly one ledger entry; found {len(added)} new entries"
                )
            if application_paths and not governed_component_change and added[0] != current:
                raise ValueError("The finalized task ledger entry does not match the canonical version")
        print(f"PASS: EOAT Atlas version {baseline} -> {current}; application changes: {len(application_paths)}.")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
