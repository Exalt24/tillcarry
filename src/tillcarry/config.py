"""Connection settings. Defaults match docker-compose.yml; every value can be overridden by environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

MYSQL_SCHEMA = "ospos"
PG_SCHEMA = "ospos"


@dataclass(frozen=True)
class MysqlConfig:
    host: str = "127.0.0.1"
    port: int = 13307
    user: str = "root"
    password: str = "lab-only"
    database: str = MYSQL_SCHEMA

    @classmethod
    def from_env(cls) -> MysqlConfig:
        return cls(
            host=os.environ.get("TILLCARRY_MYSQL_HOST", cls.host),
            port=int(os.environ.get("TILLCARRY_MYSQL_PORT", cls.port)),
            user=os.environ.get("TILLCARRY_MYSQL_USER", cls.user),
            password=os.environ.get("TILLCARRY_MYSQL_PASSWORD", cls.password),
            database=os.environ.get("TILLCARRY_MYSQL_DB", cls.database),
        )


@dataclass(frozen=True)
class PgConfig:
    host: str = "127.0.0.1"
    port: int = 15432
    user: str = "postgres"
    password: str = "lab-only"
    dbname: str = "tillcarry"

    @classmethod
    def from_env(cls) -> PgConfig:
        return cls(
            host=os.environ.get("TILLCARRY_PG_HOST", cls.host),
            port=int(os.environ.get("TILLCARRY_PG_PORT", cls.port)),
            user=os.environ.get("TILLCARRY_PG_USER", cls.user),
            password=os.environ.get("TILLCARRY_PG_PASSWORD", cls.password),
            dbname=os.environ.get("TILLCARRY_PG_DB", cls.dbname),
        )

    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} user={self.user} "
            f"password={self.password} dbname={self.dbname}"
        )
