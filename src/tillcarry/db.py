"""Connection helpers. Dates come back from MySQL as raw text so a zero date survives until we decide what to do with it."""

from __future__ import annotations

import psycopg
import pymysql
import pymysql.converters as conv
import pymysql.cursors
from pymysql.constants import FIELD_TYPE

from .config import MysqlConfig, PgConfig


def _raw(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def mysql_connect(cfg: MysqlConfig, *, database: str | None = None) -> pymysql.Connection:
    converters = dict(conv.conversions)
    for t in (FIELD_TYPE.DATE, FIELD_TYPE.DATETIME, FIELD_TYPE.TIMESTAMP, FIELD_TYPE.NEWDATE):
        converters[t] = _raw
    c = pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.database if database is None else (database or None),
        charset="utf8mb3",
        conv=converters,
        autocommit=True,
    )
    with c.cursor() as cur:
        cur.execute("SET time_zone = '+00:00'")
        cur.execute("SET SESSION information_schema_stats_expiry = 0")
    return c


def pg_connect(cfg: PgConfig, *, autocommit: bool = False) -> psycopg.Connection:
    c = psycopg.connect(cfg.dsn(), autocommit=autocommit)
    with c.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
    return c
