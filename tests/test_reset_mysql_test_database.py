from __future__ import annotations

from types import SimpleNamespace

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
