from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
REQUIRED_PATHS = (
    "run_atlas.py",
    "scripts/repo_safety_audit.py",
    "scripts/ci_atlas_smoke_check.py",
    "scripts/build_package.py",
    "scripts/smoke_test_package.py",
    "scripts/bump_version.py",
    "scripts/check_version_bump.py",
    "server/alembic.ini",
)
CURRENT_DOCS = {
    "README.md",
    "ARCHITECTURE.md",
    "DEVELOPMENT_SETUP.md",
    "DATABASE_MIGRATIONS.md",
    "RELEASE_PROCESS.md",
    "IT_DEPLOYMENT.md",
    "SECURITY_BOUNDARY.md",
    "DISASTER_RECOVERY.md",
}
RETIRED_COMMANDS = ("run_dashboard.py", "scripts/ci_smoke_check.py", "--dashboard-smoke")


def validate() -> list[str]:
    errors = [f"Documented path does not exist: {path}" for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    for document in DOCUMENTS:
        if document.name not in CURRENT_DOCS:
            continue
        text = document.read_text(encoding="utf-8")
        errors.extend(f"Retired command in {document.relative_to(ROOT)}: {value}" for value in RETIRED_COMMANDS if value in text)
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print("PASS documented EOAT Atlas commands and entry points exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
