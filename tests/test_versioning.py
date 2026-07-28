from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from build_tools.version_metadata import windows_version_text
from core.versioning.version_info import get_version_info
from launcher.core import VersionReader
from release_tools.versioning import (
    Version,
    application_change_paths,
    bump_repository_version,
    read_canonical_version,
    validate_version_sources,
)
from scripts.check_version_bump import main as check_version_main


def make_repository(root: Path, version: str = "1.2.3") -> Path:
    (root / "app" / "atlas").mkdir(parents=True, exist_ok=True)
    (root / "core" / "versioning").mkdir(parents=True, exist_ok=True)
    (root / "launcher").mkdir(parents=True, exist_ok=True)
    (root / "installer").mkdir(parents=True, exist_ok=True)
    (root / "release_defaults.json").write_text(
        json.dumps(
            {
                "app_name": "EOAT Atlas",
                "environment": "test",
                "api_contract_version": "1.3.0",
                "database_schema_revision": "test_revision",
                "launcher_version": "0.1.0",
                "installer_version": "0.1.0",
                "release_channel": "test",
                "metadata_schema_version": 2,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "app" / "atlas" / "version.json").write_text(
        json.dumps(
            {
                "appName": "EOAT Atlas",
                "version": version,
                "channel": "test",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "release_history.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "releases": [
                    {
                        "application_version": version,
                        "release_id": f"eoat-atlas-{version}",
                        "state": "historical",
                        "task_id": "fixture-baseline",
                        "finalized_at_utc": None,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "core" / "versioning" / "compatibility.py").write_text(
        'EXPECTED_API_VERSION = "1.3.0"\nEXPECTED_SCHEMA_REVISION = "test_revision"\n', encoding="utf-8"
    )
    (root / "launcher" / "launcher_version.json").write_text(
        json.dumps({"launcher_version": "0.1.0"}), encoding="utf-8"
    )
    (root / "installer" / "installer_config.json").write_text(
        json.dumps({"installer_version": "0.1.0"}), encoding="utf-8"
    )
    return root


@pytest.mark.parametrize(
    ("current", "part", "expected"),
    [
        ("1.2.3", "patch", "1.2.4"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
        ("1.9.9", "patch", "1.9.10"),
        ("1.9.9", "minor", "1.10.0"),
        ("9.9.9", "major", "10.0.0"),
    ],
)
def test_semantic_version_increment(current: str, part: str, expected: str) -> None:
    assert str(Version.parse(current).bump(part)) == expected


@pytest.mark.parametrize("malformed", ["1", "1.2", "1.2.3.4", "v1.2.3", "1.02.3", "1.2.3-dev", ""])
def test_malformed_version_rejected(malformed: str) -> None:
    with pytest.raises(ValueError, match="Invalid semantic version"):
        Version.parse(malformed)


def test_explicit_version_decrease_and_reuse_are_rejected(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    for value in ("1.2.2", "1.2.3"):
        with pytest.raises(ValueError, match="must be greater"):
            bump_repository_version(root, explicit=value)
    assert str(read_canonical_version(root)) == "1.2.3"


def test_missing_canonical_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "app" / "atlas").mkdir(parents=True)
    with pytest.raises(ValueError, match="Canonical version source is unavailable"):
        validate_version_sources(tmp_path)


def test_conflicting_and_duplicate_version_sources_are_rejected(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    canonical = root / "app" / "atlas" / "version.json"
    canonical.write_text(canonical.read_text(encoding="utf-8").replace("1.2.3", "bad"), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid semantic version"):
        validate_version_sources(root)
    make_repository(root)
    (root / "core").mkdir(exist_ok=True)
    (root / "core" / "duplicate.py").write_text('APP_VERSION = "1.2.3"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected authoritative"):
        validate_version_sources(root)


def test_component_and_release_ledger_mismatches_are_rejected(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    defaults = root / "release_defaults.json"
    defaults.write_text(
        defaults.read_text(encoding="utf-8").replace('"api_contract_version": "1.3.0"', '"api_contract_version": "9.9.9"'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="component snapshots disagree"):
        validate_version_sources(root)
    make_repository(root)
    ledger = json.loads((root / "release_history.json").read_text(encoding="utf-8"))
    ledger["releases"].append(dict(ledger["releases"][0]))
    (root / "release_history.json").write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(ValueError, match="reuses|strictly increasing"):
        validate_version_sources(root)


def test_bump_synchronizes_derived_metadata_and_is_idempotent_per_operation(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    previous, current, changed = bump_repository_version(root, part="minor", operation_id="test-task")
    repeated_previous, repeated_current, repeated_changed = bump_repository_version(
        root, part="minor", operation_id="test-task"
    )
    derived = json.loads((root / "app" / "atlas" / "version.json").read_text(encoding="utf-8"))
    assert (str(previous), str(current), changed) == ("1.2.3", "1.3.0", True)
    assert (str(repeated_previous), str(repeated_current), repeated_changed) == ("1.2.3", "1.3.0", False)
    assert derived["version"] == "1.3.0"
    assert validate_version_sources(root) == Version(1, 3, 0)


def test_concurrent_finalization_lock_prevents_version_reuse(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    lock = root / ".git" / "eoat-version-bump.lock"
    lock.parent.mkdir()
    lock.write_text("another task\n", encoding="utf-8")
    before = (root / "app" / "atlas" / "version.json").read_bytes()
    with pytest.raises(ValueError, match="Another version finalization is active"):
        bump_repository_version(root, part="minor", operation_id="concurrent-task")
    assert (root / "app" / "atlas" / "version.json").read_bytes() == before


def test_validation_failure_does_not_partially_modify_repository(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    canonical = root / "app" / "atlas" / "version.json"
    canonical.write_text(canonical.read_text(encoding="utf-8").replace('"version": "1.2.3"', '"version": "bad"'), encoding="utf-8")
    before = {path: path.read_bytes() for path in (root / "release_defaults.json", canonical)}
    with pytest.raises(ValueError):
        bump_repository_version(root, part="patch")
    assert {path: path.read_bytes() for path in before} == before


def test_application_change_classification_is_repository_specific() -> None:
    changed = [
        "app/main.py",
        "assets/icons/app.png",
        "scripts/build_package.py",
        "tests/test_main.py",
        "docs/design_notes.md",
        "docs/RELEASE_NOTES.md",
        "reports/test-output.json",
        "AGENTS.md",
        "build/temp.bin",
    ]
    assert application_change_paths(changed) == [
        "app/main.py",
        "assets/icons/app.png",
        "docs/RELEASE_NOTES.md",
        "scripts/build_package.py",
    ]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_application_change_without_bump_fails_but_developer_docs_only_pass(tmp_path: Path) -> None:
    root = make_repository(tmp_path)
    (root / "app" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text("initial\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "config", "user.email", "version-test@example.invalid")
    _git(root, "config", "user.name", "Version Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")

    (root / "app" / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert check_version_main(["--root", str(root), "--base", "HEAD"]) == 1
    _git(root, "checkout", "--", "app/main.py")
    (root / "docs" / "notes.md").write_text("developer analysis only\n", encoding="utf-8")
    assert check_version_main(["--root", str(root), "--base", "HEAD"]) == 0


def test_governed_component_exception_is_explicit_and_never_applies_to_app_code(tmp_path: Path) -> None:
    root = make_repository(tmp_path, "0.24.1")
    (root / "deployment" / "convergence").mkdir(parents=True)
    governed = root / "deployment" / "convergence" / "services.py"
    governed.write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "config", "user.email", "version-test@example.invalid")
    _git(root, "config", "user.name", "Version Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    governed.write_text("VALUE = 2\n", encoding="utf-8")
    assert check_version_main(["--root", str(root), "--base", "HEAD", "--allow-governed-component-change"]) == 0
    (root / "app" / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert check_version_main(["--root", str(root), "--base", "HEAD", "--allow-governed-component-change"]) == 1
    (root / "app" / "main.py").unlink()
    ledger_path = root / "release_history.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["releases"].append(dict(ledger["releases"][0]))
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    assert check_version_main(["--root", str(root), "--base", "HEAD", "--allow-governed-component-change"]) == 1


def test_runtime_launcher_and_build_reader_consume_canonical_without_gui(tmp_path: Path) -> None:
    root = make_repository(tmp_path, "4.5.6")
    commit = "a" * 40
    (root / "release_metadata.json").write_text(
        json.dumps(
            {
                **json.loads((root / "release_defaults.json").read_text(encoding="utf-8")),
                "metadata_role": "release_artifact",
                "app_version": "4.5.6",
                "release_id": "eoat-atlas-4.5.6",
                "build_id": "eoat-atlas-4.5.6-aaaaaaa-20260715T000000Z",
                "build_date": "2026-07-15",
                "build_timestamp": "2026-07-15T00:00:00Z",
                "source_git_commit": commit,
                "git_commit": commit,
                "branch_name": "test",
                    "database_schema_revision": "20260721_0008",
                "api_contract_version": "1.4.0",
            }
        ),
        encoding="utf-8",
    )
    get_version_info.cache_clear()
    runtime = get_version_info(root)
    launcher = VersionReader().read(root)
    assert runtime.application_version == "4.5.6"
    assert launcher is not None and launcher.version == "4.5.6"
    assert read_canonical_version(root) == Version(4, 5, 6)
    version_resource = windows_version_text(root)
    assert "filevers=(4, 5, 6, 0)" in version_resource
    assert "ProductVersion', '4.5.6'" in version_resource
