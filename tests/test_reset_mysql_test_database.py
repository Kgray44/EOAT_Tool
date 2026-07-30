from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.database import reset_mysql_test_database


class _Cursor:
    def __init__(self, statements: list[tuple[str, tuple[object, ...] | None]]) -> None:
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, statement: str, params=None) -> None:
        self.statements.append((statement, params))


class _Connection:
    def __init__(self, statements: list[tuple[str, tuple[object, ...] | None]]) -> None:
        self.statements = statements

    def cursor(self) -> _Cursor:
        return _Cursor(self.statements)

    def close(self) -> None:
        return None


def test_reset_reuses_root_and_grants_network_reachable_test_app_user(monkeypatch) -> None:
    statements: list[tuple[str, tuple[object, ...] | None]] = []
    environment = {
        "EOAT_DB_NAME": "eoat_atlas_test",
        "EOAT_DB_USER": "eoat_atlas_app",
        "EOAT_DB_PASSWORD": "synthetic-app-password",
        "EOAT_DB_MIGRATION_USER": "root",
        "EOAT_DB_MIGRATION_PASSWORD": "synthetic-root-password",
        "EOAT_DB_ROOT_PASSWORD": "synthetic-root-password",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", ["reset_mysql_test_database.py"])
    monkeypatch.setattr(
        reset_mysql_test_database.pymysql,
        "connect",
        lambda **_kwargs: _Connection(statements),
    )
    monkeypatch.setattr(
        reset_mysql_test_database.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    assert reset_mysql_test_database.main() == 0

    sql = "\n".join(statement for statement, _params in statements)
    assert "CREATE USER IF NOT EXISTS %s@'%%'" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON" in sql
    assert "EXECUTE" not in sql
    assert "GRANT ALL PRIVILEGES" not in sql
    assert all(params != ("root",) for _statement, params in statements)


@pytest.mark.parametrize(
    ("database", "host"),
    [
        ("eoat_atlas_dev", "127.0.0.1"),
        ("eoat_atlas_prod", "127.0.0.1"),
        ("", "127.0.0.1"),
        ("eoat_atlas_test*", "127.0.0.1"),
        ("eoat_atlas_test", "eoat-atlas"),
        ("eoat_atlas_test", "eoat-atlas.gwplastics.com"),
    ],
)
def test_reset_rejects_non_disposable_database_or_host(monkeypatch, database: str, host: str) -> None:
    monkeypatch.setenv("EOAT_DB_NAME", database)
    monkeypatch.setenv("EOAT_DB_HOST", host)
    monkeypatch.setattr("sys.argv", ["reset_mysql_test_database.py"])

    with pytest.raises(SystemExit, match="2"):
        reset_mysql_test_database.main()


def test_reset_rejects_overlong_test_account_before_connecting(monkeypatch) -> None:
    monkeypatch.setenv("EOAT_DB_NAME", "eoat_atlas_test")
    monkeypatch.setenv("EOAT_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("EOAT_DB_ROOT_PASSWORD", "synthetic-root-password")
    monkeypatch.setenv("EOAT_DB_USER", "x" * 33)
    monkeypatch.setenv("EOAT_DB_PASSWORD", "synthetic-app-password")
    monkeypatch.setenv("EOAT_DB_MIGRATION_USER", "migration")
    monkeypatch.setenv("EOAT_DB_MIGRATION_PASSWORD", "synthetic-migration-password")
    monkeypatch.setattr("sys.argv", ["reset_mysql_test_database.py"])

    with pytest.raises(SystemExit, match="2"):
        reset_mysql_test_database.main()
