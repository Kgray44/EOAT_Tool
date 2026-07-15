from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".tsv",
    ".yaml",
    ".yml",
}

WORKBOOK_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".xlsb"}
DATA_SUFFIXES = {".csv", ".tsv", *WORKBOOK_SUFFIXES, ".jsonl", ".zip"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".webp"}
IGNORED_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "ENV",
}
IGNORED_TOP_LEVEL = {
    "EOAT_Standardization_Project",
    "Project_Help_Documents",
    "real_project",
    "real_projects",
    "project_data",
    "private_data",
    "local_data",
}
ALLOW_PREFIXES = (
    ("examples", "demo_project"),
    ("templates",),
    ("tests",),
    ("data_templates",),
    ("reports", "sanitized"),
    ("reports", "templates"),
    ("reports", "examples"),
)
DATA_ALLOW_PREFIXES = (
    ("examples", "demo_project"),
    ("templates",),
    ("tests",),
    ("data_templates",),
    ("reports", "sanitized"),
    ("reports", "templates"),
    ("reports", "examples"),
)
IMAGE_ALLOW_PREFIXES = (
    ("app", "atlas", "logo"),
    ("EOAT_Atlas_pages",),
    ("examples", "demo_project"),
    ("templates",),
    ("tests",),
    ("data_templates",),
    ("docs",),
)


@dataclass(frozen=True)
class Finding:
    severity: str
    path: Path
    message: str
    line: int | None = None

    def format(self, root: Path) -> str:
        rel = self.path.relative_to(root) if self.path.is_absolute() else self.path
        location = f"{rel}:{self.line}" if self.line else str(rel)
        return f"{self.severity}: {location} - {self.message}"


LINE_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "BLOCKER",
        "Internal shared-drive or UNC path detected.",
        re.compile(r"(?:(?<![A-Za-z0-9_.-])\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9$_.-]+\\|gwplastics\.com)", re.IGNORECASE),
    ),
    (
        "BLOCKER",
        "Local user or company workstation path detected.",
        re.compile(r"\b[A-Z]:\\Users\\[^\\\s]+\\", re.IGNORECASE),
    ),
    (
        "BLOCKER",
        "Secret-like value detected.",
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|passwd)\b\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{8,}['\"]"
        ),
    ),
    (
        "WARNING",
        "Mold-number-like value detected; review before publishing.",
        re.compile(r"(?i)\bmold\s*(?:number|no\.?|#)\s*[:=]\s*[A-Z0-9][A-Z0-9_-]{3,}"),
    ),
    (
        "WARNING",
        "Part-number-like value detected outside an allowed demo/template/test area.",
        re.compile(r"(?i)\bpart\s*(?:number|no\.?|#)\s*[:=]\s*[A-Z0-9][A-Z0-9_-]{3,}"),
    ),
    (
        "WARNING",
        "Customer field detected outside an allowed demo/template/test area.",
        re.compile(r"(?i)\b(?:bill-to|customer name|customer)\b\s*[:=]\s*[A-Z][A-Za-z0-9 ._-]{3,}"),
    ),
    (
        "WARNING",
        "Public company reference appears near operational context; review before publishing.",
        re.compile(
            r"(?i)\b(?:nolato|gw\s*plastics|gwplastics)\b.{0,120}\b(?:capacity|cycle\s*time|downtime|scrap|mold|part\s*(?:number|no\.?|#)|customer|press|maintenance)\b"
        ),
    ),
]

PATH_BLOCKERS = [
    ("config/local_config.json", "Local config file must not be committed."),
    ("config/user_config.json", "Local config file must not be committed."),
    ("config/config.json", "Local config file must not be committed."),
    ("local_config.json", "Local config file must not be committed."),
    ("user_config.json", "Local config file must not be committed."),
    (".env", "Environment file must not be committed."),
    (".env.*", "Environment file must not be committed."),
    ("*.pem", "Certificate or private-key material must not be committed."),
    ("*.key", "Certificate or private-key material must not be committed."),
    ("*credentials*.json", "Credential file must not be committed."),
]

SENSITIVE_PATH_WORDS = [
    "audit_database",
    "activity_logs",
    "auto_exported_content",
    "backups",
    "candidate_cells",
    "capacity",
    "cycle_time_data",
    "dashboard_exports",
    "daily_status_reports",
    "downtime_data",
    "eoat_audit_database",
    "final_report",
    "handoff_package",
    "issue_analysis_reports",
    "maintenance_data",
    "mentor_briefs",
    "press list",
    "reference_data",
    "scrap_data",
    "snapshots",
    "validation_reports",
    "weekly_status_reports",
]

GENERATED_PATH_PARTS = {
    "reports",
    "logs",
    "cache",
    "activity_logs",
    "daily_status_reports",
    "weekly_status_reports",
    "validation_reports",
    "mentor_briefs",
    "dashboard_exports",
    "audit_progress_reports",
    "issue_analysis_reports",
    "documentation_gap_reports",
    "bom_standardization_reports",
    "fmea_reports",
    "candidate_cells",
    "auto_exported_content",
    "handoff_package",
    "final_report",
    "backups",
    "_backups",
    "snapshots",
    "exports",
}

REAL_PROJECT_ROOT_PARTS = {
    "eoat_standardization_project",
    "real_project",
    "real_projects",
    "private_data",
    "local_data",
}

LOCAL_CONFIG_NAMES = {
    "local_config.json",
    "user_config.json",
    "config.json",
}

LEGACY_PRIVATE_FILENAMES = [
    re.compile(r"Royalton.*Master Press List", re.IGNORECASE),
    re.compile(r"Plant\s*4.*Press Capacity", re.IGNORECASE),
]


def _rel_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return path.relative_to(root).parts
    except ValueError:
        return path.parts


def is_allowed_repo_artifact(path: Path, root: Path) -> bool:
    parts = _rel_parts(path, root)
    return any(parts[: len(prefix)] == prefix for prefix in ALLOW_PREFIXES)


def is_allowed_data_artifact(path: Path, root: Path) -> bool:
    parts = _rel_parts(path, root)
    return any(parts[: len(prefix)] == prefix for prefix in DATA_ALLOW_PREFIXES)


def is_allowed_image_artifact(path: Path, root: Path) -> bool:
    parts = _rel_parts(path, root)
    return any(parts[: len(prefix)] == prefix for prefix in IMAGE_ALLOW_PREFIXES)


def should_skip_dir(path: Path, root: Path) -> bool:
    parts = _rel_parts(path, root)
    if not parts:
        return False
    if path.name in IGNORED_DIRS:
        return True
    if len(parts) == 1 and parts[0] in IGNORED_TOP_LEVEL:
        return True
    return False


def _path_matches_blocker(rel: str, pattern: str) -> bool:
    return rel == pattern or fnmatch.fnmatch(rel, pattern)


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current_text, dirs, names in os.walk(root):
        current = Path(current_text)
        dirs[:] = [name for name in dirs if not should_skip_dir(current / name, root)]
        for name in names:
            path = current / name
            if path.name.startswith("~$"):
                continue
            files.append(path)
    return files


def git_repo_files(root: str | Path, git_executable: str = "git") -> tuple[list[Path] | None, str | None]:
    root_path = Path(root).resolve()
    if not (root_path / ".git").exists():
        return None, None
    try:
        completed = subprocess.run(
            [git_executable, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root_path,
            check=False,
            capture_output=True,
            text=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"Could not list git candidate files: {exc}"
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        return None, f"Could not list git candidate files: {error or completed.returncode}"
    names = [name.decode("utf-8", errors="replace") for name in completed.stdout.split(b"\0") if name]
    return [root_path / name for name in names], None


def git_staged_files(root: str | Path, git_executable: str = "git") -> tuple[list[Path], str | None]:
    root_path = Path(root).resolve()
    try:
        completed = subprocess.run(
            [git_executable, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
            cwd=root_path,
            check=False,
            capture_output=True,
            text=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"Could not list staged files: {exc}"
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        return [], f"Could not list staged files: {error or completed.returncode}"
    names = [name.decode("utf-8", errors="replace") for name in completed.stdout.split(b"\0") if name]
    return [root_path / name for name in names], None


def audit_paths(root: str | Path, paths: list[str | Path]) -> list[Finding]:
    root_path = Path(root).resolve()
    findings: list[Finding] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = root_path / path
        if path.exists() and path.is_file():
            findings.extend(audit_file(path.resolve(), root_path))
    return findings


def audit_staged_files(root: str | Path, git_executable: str = "git") -> list[Finding]:
    root_path = Path(root).resolve()
    files, warning = git_staged_files(root_path, git_executable)
    if warning:
        return [Finding("BLOCKER", root_path, warning)]
    return audit_paths(root_path, files)


def audit_file(path: Path, root: Path, *, max_large_file_bytes: int = 5_000_000) -> list[Finding]:
    findings: list[Finding] = []
    if path.resolve() == Path(__file__).resolve():
        return findings
    rel = path.relative_to(root).as_posix()
    rel_lower = rel.lower()
    allowed = is_allowed_repo_artifact(path, root)
    allowed_data = is_allowed_data_artifact(path, root)
    allowed_image = is_allowed_image_artifact(path, root)
    is_test_file = _rel_parts(path, root)[:1] == ("tests",)
    parts_lower = tuple(part.lower().replace("-", "_").replace(" ", "_") for part in _rel_parts(path, root))

    if parts_lower[:1] == ("reports",) and not allowed:
        findings.append(Finding("BLOCKER", path, "Operational report artifact is outside reports/sanitized, templates, or examples."))

    for pattern, message in PATH_BLOCKERS:
        if path.name.casefold().endswith(".example") and pattern == ".env.*":
            continue
        if _path_matches_blocker(rel_lower, pattern.lower()):
            findings.append(Finding("BLOCKER", path, message))
    if (path.name.lower() in LOCAL_CONFIG_NAMES or path.name.lower().endswith(".local.json")) and not any(
        finding.message == "Local config file must not be committed." for finding in findings
    ):
        findings.append(Finding("BLOCKER", path, "Local config file must not be committed."))

    if not allowed:
        if any(part in REAL_PROJECT_ROOT_PARTS for part in parts_lower):
            findings.append(Finding("BLOCKER", path, "Real project root path is outside the committed repo boundary."))

        for pattern in LEGACY_PRIVATE_FILENAMES:
            if pattern.search(path.name):
                findings.append(Finding("BLOCKER", path, "Private reference workbook filename detected."))

        normalized = rel_lower.replace("-", "_").replace(" ", "_")
        if any(part in GENERATED_PATH_PARTS for part in parts_lower):
            findings.append(
                Finding(
                    "BLOCKER",
                    path,
                    "Generated reports/logs/cache/backups/exports path is outside the demo/template/test allowlist.",
                )
            )

        if any(word.replace(" ", "_") in normalized for word in SENSITIVE_PATH_WORDS):
            if path.suffix.lower() in DATA_SUFFIXES | IMAGE_SUFFIXES or "reports" in normalized or "logs" in normalized:
                findings.append(
                    Finding(
                        "BLOCKER", path, "Operational data/output path is outside the demo/template/test allowlist."
                    )
                )

        if path.suffix.lower() in DATA_SUFFIXES | IMAGE_SUFFIXES and path.stat().st_size > max_large_file_bytes:
            findings.append(
                Finding(
                    "WARNING",
                    path,
                    "Large data/media file found outside the allowlist; review for real operational content.",
                )
            )

    if path.suffix.lower() in WORKBOOK_SUFFIXES and not allowed_data:
        findings.append(
            Finding("BLOCKER", path, "Workbook file is outside allowed demo/template/test/data-template paths.")
        )
    if path.suffix.lower() in IMAGE_SUFFIXES and not allowed_image:
        findings.append(Finding("BLOCKER", path, "Photo/image file is outside allowed demo/template/test/docs paths."))

    if path.suffix.lower() not in TEXT_SUFFIXES:
        return findings

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        findings.append(Finding("WARNING", path, f"Could not read file for content scan: {exc.__class__.__name__}"))
        return findings

    for number, line in enumerate(lines, start=1):
        for severity, message, pattern in LINE_RULES:
            if is_test_file:
                continue
            if allowed and severity == "WARNING":
                continue
            if (
                severity == "WARNING"
                and path.suffix.casefold() == ".py"
                and re.search(r"\bcustomer\s*(?::\s*(?:Mapped|str)|=\s*(?:entity|record|row|tool)\.customer)", line)
            ):
                continue
            if pattern.search(line):
                findings.append(Finding(severity, path, message, number))
    return findings


def audit_repo(root: str | Path) -> list[Finding]:
    root_path = Path(root).resolve()
    findings: list[Finding] = []
    files, warning = git_repo_files(root_path)
    if warning:
        findings.append(Finding("WARNING", root_path, warning))
    for path in files if files is not None else iter_files(root_path):
        # Deleted tracked files remain in `git ls-files` until committed. Their
        # former content is unavailable and must not crash a pre-commit scan.
        if path.is_file():
            findings.extend(audit_file(path, root_path))
    return findings


def print_findings(findings: list[Finding], root: Path) -> None:
    if not findings:
        print("INFO: repo safety audit found no blocking or warning findings.")
        return
    for finding in findings:
        print(finding.format(root))
    blockers = sum(1 for finding in findings if finding.severity == "BLOCKER")
    warnings = sum(1 for finding in findings if finding.severity == "WARNING")
    print(f"INFO: repo safety audit completed with {blockers} blocker(s), {warnings} warning(s).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan the EOAT toolkit repository for NDA-sensitive files or content before commit."
    )
    parser.add_argument("--root", default=".", help="Repository root to scan. Defaults to the current directory.")
    parser.add_argument("--staged", action="store_true", help="Scan only staged files using git diff --cached.")
    parser.add_argument("--git", default="git", help="Git executable to use with --staged.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    findings = audit_staged_files(root, args.git) if args.staged else audit_repo(root)
    print_findings(findings, root)
    return 1 if any(finding.severity == "BLOCKER" for finding in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
