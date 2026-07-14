from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api_manager import APIManager
from .exceptions import BootstrapError
from .mysql_manager import MySQLManager
from .service_manager import CANONICAL_MARKER


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="EOAT Atlas local development service control")
    result.add_argument("service", choices=("mysql", "api"))
    result.add_argument("action", choices=("start", "stop", "status"))
    result.add_argument("--read-only", action="store_true", help="Start the API with writes disabled")
    return result


def _print_mysql(status, state: str) -> None:
    print("EOAT Atlas Local MySQL")
    print(f"Status: {state}")
    print(f"MySQL version: {status.version or 'Unavailable'}")
    print("Host: 127.0.0.1")
    print("Port: 3306")
    print(f"Database: {status.database}")
    print(f"Schema revision: {status.schema_revision or 'Unavailable'}")
    print(f"Tables: {status.table_count}")
    print(f"PID: {status.pid or 'None'}")
    print(f"Log: {status.log_path}")


def _print_api(status, state: str) -> None:
    print("EOAT Atlas Local API")
    print(f"Status: {state}")
    print(f"API version: {status.api_version or 'Unavailable'}")
    print(f"Schema revision: {status.schema_revision or 'Unavailable'}")
    print(f"Database: {'Connected' if status.database_reachable else 'Unavailable'}")
    print(f"Canonical process: {'Yes' if status.canonical else 'No'}")
    print(f"Writes enabled: {'Yes' if status.writes_enabled else 'No'}")
    print(f"PID: {status.pid or 'None'}")
    print(f"Log: {status.log_path}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = repository_root()
    if not (root / CANONICAL_MARKER).is_file():
        print("This repository is not the canonical EOAT Atlas development root.", file=sys.stderr)
        return 2
    try:
        if args.service == "mysql":
            manager = MySQLManager()
            before = manager.status()
            if args.action == "start":
                status = manager.verify(manager.start())
                _print_mysql(status, "Already running" if before.running else "Started")
            elif args.action == "stop":
                manager.stop()
                _print_mysql(manager.status(), "Stopped")
            else:
                status = manager.status()
                _print_mysql(status, "Running" if status.running else "Stopped")
                return 0 if status.connected else 1
        else:
            manager = APIManager(root)
            before = manager.status()
            if args.action == "start":
                status = manager.verify(manager.start(writes_enabled=not args.read_only), writes_enabled=not args.read_only)
                _print_api(status, "Already running" if before.running else "Started")
            elif args.action == "stop":
                manager.stop()
                _print_api(manager.status(), "Stopped")
            else:
                status = manager.status()
                _print_api(status, "Running" if status.running else "Stopped")
                return 0 if status.healthy and status.canonical else 1
    except BootstrapError as exc:
        print(exc.render(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
