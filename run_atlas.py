"""Canonical EOAT Atlas development bootstrap.

This launcher resolves its repository from this file, validates the canonical
development marker, selects mysql_api by default, verifies or starts the local
MySQL/API stack, and imports the current PySide6 application only afterward.
It never searches for an installed build and never falls back to Excel.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--backend", choices=("mysql_api", "legacy"))
    parser.add_argument("--environment", default=None)
    parser.add_argument("--no-auto-start-services", action="store_true")
    return parser


def _is_within(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _is_project_copy(path: str) -> bool:
    try:
        candidate = Path(path).resolve()
    except (OSError, ValueError):
        return False
    return candidate.is_dir() and (candidate / "EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT").exists()


def _isolate_import_path() -> None:
    retained = [entry for entry in sys.path if not (_is_project_copy(entry) and not _is_within(entry, REPOSITORY_ROOT))]
    root_text = str(REPOSITORY_ROOT)
    sys.path[:] = [root_text, *[entry for entry in retained if entry and Path(entry).resolve() != REPOSITORY_ROOT]]


def bootstrap(argv: list[str] | None = None):
    args, remaining = _parser().parse_known_args(argv)
    _isolate_import_path()
    from core.development_bootstrap.service_manager import BootstrapConfiguration, DevelopmentServiceManager

    configuration = BootstrapConfiguration.resolve(
        REPOSITORY_ROOT,
        backend=args.backend,
        environment=args.environment,
        no_auto_start_services=args.no_auto_start_services,
    )
    manager = DevelopmentServiceManager(configuration)
    report = manager.prepare()
    manager.print_banner(report)
    return report, remaining


def main(argv: list[str] | None = None) -> int:
    try:
        report, remaining = bootstrap(argv)
        sys.argv = [sys.argv[0], *remaining]
        from app.atlas import main as application_main
        from core.development_bootstrap.service_manager import assert_module_is_canonical

        assert_module_is_canonical(application_main, report.configuration.repository_root)
        return application_main.main()
    except Exception as exc:
        from core.development_bootstrap.exceptions import BootstrapError

        if isinstance(exc, BootstrapError):
            print("\nEOAT Atlas startup blocked\n" + "-" * 60, file=sys.stderr)
            print(exc.render(), file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
