from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import total_ordering
from pathlib import Path

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CANONICAL_VERSION_PATH = Path("app/atlas/version.json")
# Compatibility export for callers that previously treated version.json as a
# derived copy of tracked release metadata. It is now the only source version.
DERIVED_VERSION_PATH = CANONICAL_VERSION_PATH
RELEASE_DEFAULTS_PATH = Path("release_defaults.json")
RELEASE_LEDGER_PATH = Path("release_history.json")


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        match = _SEMVER.fullmatch(str(value).strip())
        if not match:
            raise ValueError(f"Invalid semantic version {value!r}; expected MAJOR.MINOR.PATCH")
        return cls(*(int(part) for part in match.groups()))

    def bump(self, part: str = "patch") -> Version:
        if part == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        if part == "minor":
            return Version(self.major, self.minor + 1, 0)
        if part == "major":
            return Version(self.major + 1, 0, 0)
        raise ValueError(f"Unsupported version bump: {part}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)


def build_identifier(version: Version | str, commit_sha: str, timestamp: datetime) -> str:
    parsed = version if isinstance(version, Version) else Version.parse(version)
    utc = timestamp.astimezone(timezone.utc)
    return f"eoat-atlas-{parsed}-{(commit_sha[:7] or 'unknown')}-{utc.strftime('%Y%m%dT%H%M%SZ')}"


def read_json_object(data: str | bytes, *, source: str) -> dict[str, object]:
    try:
        payload = json.loads(data)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{source} must contain a JSON object")
    return payload


def canonical_version_from_payload(payload: dict[str, object], *, source: str = "app/atlas/version.json") -> Version:
    app_name = payload.get("appName") or payload.get("app_name")
    if app_name != "EOAT Atlas":
        raise ValueError(f"{source} is not EOAT Atlas version metadata")
    return Version.parse(str(payload.get("version") or payload.get("app_version") or ""))


def read_canonical_version(root: Path) -> Version:
    path = root / CANONICAL_VERSION_PATH
    try:
        payload = read_json_object(path.read_bytes(), source=str(path))
    except OSError as exc:
        raise ValueError(f"Canonical version source is unavailable: {path}") from exc
    return canonical_version_from_payload(payload, source=str(path))


def validate_version_sources(
    root: Path,
    *,
    read_bytes: Callable[[Path], bytes] | None = None,
) -> Version:
    reader = read_bytes or (lambda relative: (root / relative).read_bytes())
    try:
        canonical = read_json_object(reader(CANONICAL_VERSION_PATH), source=str(CANONICAL_VERSION_PATH))
    except OSError as exc:
        raise ValueError(f"Canonical version source is unavailable: {CANONICAL_VERSION_PATH}") from exc
    version = canonical_version_from_payload(canonical)
    try:
        defaults = read_json_object(reader(RELEASE_DEFAULTS_PATH), source=str(RELEASE_DEFAULTS_PATH))
    except OSError as exc:
        raise ValueError(f"Required release defaults are unavailable: {RELEASE_DEFAULTS_PATH}") from exc
    if defaults.get("app_name") != canonical.get("appName"):
        raise ValueError("Release defaults app name does not match canonical version metadata")
    forbidden = {"app_version", "release_id", "build_id", "build_timestamp", "git_commit", "source_git_commit"}
    present = sorted(field for field in forbidden if field in defaults)
    if present:
        raise ValueError("release_defaults.json contains generated identity fields: " + ", ".join(present))
    _validate_component_snapshots(root, defaults)
    try:
        ledger = read_json_object(reader(RELEASE_LEDGER_PATH), source=str(RELEASE_LEDGER_PATH))
    except OSError as exc:
        raise ValueError(f"Required release ledger is unavailable: {RELEASE_LEDGER_PATH}") from exc
    _validate_release_ledger(ledger, version)
    _reject_unexpected_authoritative_sources(root)
    return version


def _validate_component_snapshots(root: Path, defaults: dict[str, object]) -> None:
    expected = {
        "api_contract_version": _python_assignment(root / "core/versioning/compatibility.py", "EXPECTED_API_VERSION"),
        "database_schema_revision": _python_assignment(
            root / "core/versioning/compatibility.py", "EXPECTED_SCHEMA_REVISION"
        ),
        "launcher_version": _json_field(root / "launcher/launcher_version.json", "launcher_version"),
        "installer_version": _json_field(root / "installer/installer_config.json", "installer_version"),
    }
    mismatches = [
        f"{field}: release_defaults={defaults.get(field)!r}, component={value!r}"
        for field, value in expected.items()
        if value and defaults.get(field) != value
    ]
    if mismatches:
        raise ValueError("Release component snapshots disagree: " + "; ".join(mismatches))


def _python_assignment(path: Path, name: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(rf"^{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    return match.group(1) if match else ""


def _json_field(path: Path, field: str) -> str:
    try:
        payload = read_json_object(path.read_bytes(), source=str(path))
    except (OSError, ValueError):
        return ""
    return str(payload.get(field) or "")


def _validate_release_ledger(ledger: dict[str, object], current: Version) -> None:
    if ledger.get("schema_version") != 1 or not isinstance(ledger.get("releases"), list):
        raise ValueError("release_history.json must use schema_version 1 with a releases list")
    versions: list[Version] = []
    release_ids: set[str] = set()
    task_ids: set[str] = set()
    for index, raw in enumerate(ledger["releases"]):
        if not isinstance(raw, dict):
            raise ValueError(f"Release ledger entry {index} is not an object")
        version = Version.parse(str(raw.get("application_version", "")))
        release_id = str(raw.get("release_id") or "")
        task_id = str(raw.get("task_id") or "")
        if release_id != f"eoat-atlas-{version}":
            raise ValueError(f"Release ledger entry {version} has a mismatched release_id")
        if release_id in release_ids or task_id in task_ids:
            raise ValueError("Release ledger reuses a release ID or task receipt")
        if versions and version <= versions[-1]:
            raise ValueError("Release ledger versions must be strictly increasing")
        if raw.get("state") not in {"historical", "finalized"}:
            raise ValueError(f"Release ledger entry {version} has an invalid state")
        versions.append(version)
        release_ids.add(release_id)
        task_ids.add(task_id)
    if not versions or versions[-1] != current:
        raise ValueError(f"Release ledger latest version must equal canonical version {current}")


def _reject_unexpected_authoritative_sources(root: Path) -> None:
    excluded = {
        ".git",
        ".venv",
        "build",
        "dist",
        "tmp",
        "output",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "docs",
        "reports",
        "tests",
    }
    assignment = re.compile(r"(?:__version__|APP_VERSION)\s*=\s*['\"]\d+\.\d+\.\d+['\"]")
    conflicts: list[str] = []
    for directory, names, filenames in os.walk(root):
        names[:] = [name for name in names if name not in excluded]
        directory_path = Path(directory)
        for filename in filenames:
            path = directory_path / filename
            if filename.casefold() == "version.txt":
                conflicts.append(path.relative_to(root).as_posix())
            elif path.suffix.casefold() == ".py":
                try:
                    if assignment.search(path.read_text(encoding="utf-8")):
                        conflicts.append(path.relative_to(root).as_posix())
                except OSError:
                    continue
    if conflicts:
        raise ValueError("Unexpected authoritative version source(s): " + ", ".join(sorted(conflicts)))


def _replace_json_string(text: str, field: str, value: str, *, source: str) -> str:
    pattern = re.compile(rf'("{re.escape(field)}"\s*:\s*)"[^"]*"')
    updated, count = pattern.subn(lambda match: f'{match.group(1)}"{value}"', text, count=1)
    if count != 1:
        raise ValueError(f"{source} must contain exactly one string field named {field!r}")
    return updated


def _atomic_replace_texts(updates: dict[Path, str]) -> None:
    originals = {path: path.read_bytes() for path in updates}
    temporary: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, text in updates.items():
            handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            temporary[path] = Path(name)
        for path, temp in temporary.items():
            temp.replace(path)
            replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            path.write_bytes(originals[path])
        raise
    finally:
        for temp in temporary.values():
            temp.unlink(missing_ok=True)


def bump_repository_version(
    root: Path,
    *,
    part: str | None = None,
    explicit: str | None = None,
    operation_id: str | None = None,
) -> tuple[Version, Version, bool]:
    root = root.resolve()
    lock_path = _git_path(root, "eoat-version-bump.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(
            f"Another version finalization is active ({lock_path}); retry after it completes"
        ) from exc
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()}\noperation_id={operation_id or 'manual'}\n")
            stream.flush()
            os.fsync(stream.fileno())
        return _bump_repository_version_locked(
            root,
            part=part,
            explicit=explicit,
            operation_id=operation_id,
        )
    finally:
        lock_path.unlink(missing_ok=True)


def _bump_repository_version_locked(
    root: Path,
    *,
    part: str | None,
    explicit: str | None,
    operation_id: str | None,
) -> tuple[Version, Version, bool]:
    current = validate_version_sources(root)
    task_id = operation_id or f"manual-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
    receipt = _operation_receipt(root, task_id)
    if receipt.is_file():
        payload = read_json_object(receipt.read_bytes(), source=str(receipt))
        recorded = Version.parse(str(payload.get("current", "")))
        if recorded != current:
            raise ValueError(f"Operation {task_id!r} was already used for version {recorded}; current is {current}")
        return Version.parse(str(payload["previous"])), current, False
    if bool(part) == bool(explicit):
        raise ValueError("Specify exactly one bump type or --set version")
    target = current.bump(part or "") if part else Version.parse(explicit or "")
    if target <= current:
        raise ValueError(f"New version {target} must be greater than current version {current}")
    canonical_path = root / CANONICAL_VERSION_PATH
    ledger_path = root / RELEASE_LEDGER_PATH
    original_canonical = canonical_path.read_bytes().decode("utf-8")
    original_ledger = ledger_path.read_bytes().decode("utf-8")
    finalized = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp = finalized.strftime("%Y-%m-%dT%H:%M:%SZ")
    canonical_text = _replace_json_string(
        original_canonical, "version", str(target), source=str(canonical_path)
    )
    ledger = read_json_object(original_ledger, source=str(ledger_path))
    releases = list(ledger.get("releases") or [])
    releases.append(
        {
            "application_version": str(target),
            "release_id": f"eoat-atlas-{target}",
            "state": "finalized",
            "task_id": task_id,
            "finalized_at_utc": timestamp,
        }
    )
    ledger["releases"] = releases
    ledger_text = json.dumps(ledger, indent=2) + "\n"
    updates = {
        canonical_path: canonical_text,
        ledger_path: ledger_text,
    }
    _atomic_replace_texts(updates)
    try:
        validate_version_sources(root)
    except Exception:
        _atomic_replace_texts(
            {
                canonical_path: original_canonical,
                ledger_path: original_ledger,
            }
        )
        raise
    receipt_temp: Path | None = None
    try:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=f".{receipt.name}.", suffix=".tmp", dir=receipt.parent)
        receipt_temp = Path(name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {
                    "operation_id": task_id,
                    "state": "finalized",
                    "previous": str(current),
                    "current": str(target),
                    "release_id": f"eoat-atlas-{target}",
                    "finalized_at_utc": timestamp,
                },
                stream,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        receipt_temp.replace(receipt)
    except Exception:
        _atomic_replace_texts(
            {
                canonical_path: original_canonical,
                ledger_path: original_ledger,
            }
        )
        raise
    finally:
        if receipt_temp is not None:
            receipt_temp.unlink(missing_ok=True)
    return current, target, True


def _git_value(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _operation_receipt(root: Path, operation_id: str | None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", operation_id or "").strip(".-")
    if not safe:
        raise ValueError("operation_id must contain at least one letter or number")
    return _git_path(root, "eoat-version-operations") / f"{safe}.json"


def _git_path(root: Path, name: str) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-path", name],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    path = Path(completed.stdout.strip()) if completed.returncode == 0 else root / ".git" / name
    return path if path.is_absolute() else root / path


def application_change_paths(paths: Iterable[str]) -> list[str]:
    exempt_roots = {
        ".github",
        ".pytest_cache",
        ".ruff_cache",
        "00_Project_Admin",
        "docs",
        "reports",
        "tests",
        "tmp",
        "output",
        "build",
        "dist",
        "_migration_logs",
    }
    exempt_files = {
        ".gitignore",
        ".gitattributes",
        "AGENTS.md",
        "README.md",
        "README_MIGRATION.md",
        "pytest.ini",
        "requirements-dev.txt",
        str(CANONICAL_VERSION_PATH).replace("\\", "/"),
        str(RELEASE_DEFAULTS_PATH).replace("\\", "/"),
        str(RELEASE_LEDGER_PATH).replace("\\", "/"),
    }
    result: list[str] = []
    for raw in paths:
        normalized = raw.replace("\\", "/").lstrip("./")
        first = normalized.split("/", 1)[0]
        name = normalized.rsplit("/", 1)[-1]
        if normalized in exempt_files or first in exempt_roots:
            continue
        if name.endswith((".log", ".pyc", ".tmp", ".bak")) or "__pycache__" in normalized.split("/"):
            continue
        result.append(normalized)
    return sorted(set(result))
