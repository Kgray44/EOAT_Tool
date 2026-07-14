from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class DatabaseSettings:
    host: str = "127.0.0.1"
    port: int = 3306
    database: str = "eoat_atlas_dev"
    username: str = "eoat_atlas_app"
    password: str = ""
    driver: str = "pymysql"

    @classmethod
    def from_environment(cls, *, migration: bool = False) -> DatabaseSettings:
        prefix = "EOAT_DB_MIGRATION_" if migration else "EOAT_DB_"
        return cls(
            host=os.getenv("EOAT_DB_HOST", "127.0.0.1"),
            port=int(os.getenv("EOAT_DB_PORT", "3306")),
            database=os.getenv("EOAT_DB_NAME", "eoat_atlas_dev"),
            username=os.getenv(f"{prefix}USER", "eoat_atlas_migrator" if migration else "eoat_atlas_app"),
            password=os.getenv(f"{prefix}PASSWORD", ""),
            driver=os.getenv("EOAT_DB_DRIVER", "pymysql"),
        )

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"mysql+{self.driver}://{quote_plus(self.username)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}?charset=utf8mb4"
        )


def migration_database_url() -> str:
    explicit = os.getenv("EOAT_DATABASE_URL")
    return explicit or DatabaseSettings.from_environment(migration=True).sqlalchemy_url
