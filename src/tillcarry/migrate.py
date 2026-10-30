"""The migration itself.

One PostgreSQL transaction does everything: build a fresh schema (<name>_next), copy the data, quarantine
orphans, add constraints, reset sequences, then swap it in by renaming. If anything fails the transaction rolls
back and the target is exactly as it was. The previous schema is kept as <name>_prev so `tillcarry rollback`
is two renames. MySQL is only ever read, inside one read-only consistent snapshot.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pymysql.cursors

from . import __version__, ddl
from .config import PG_SCHEMA, MysqlConfig, PgConfig
from .db import mysql_connect, pg_connect
from .introspect import read_schema
from .plan import Plan, TablePlan, build_plan
from .typemap import convert_value

REJECTS = "_tillcarry_rejects"
COERCED = "_tillcarry_coerced"
RUNLOG = "_tillcarry_run"
KEY_SEP = "\x1f"
NULL_KEY = "\\N"


@dataclass
class TableStats:
    source_rows: int = 0
    loaded: int = 0
    rejected: int = 0
    coerced: int = 0


@dataclass
class RunReport:
    dry_run: bool
    plan: Plan
    stats: dict[str, TableStats] = field(default_factory=dict)
    swapped: bool = False
    previous_schema_kept: bool = False

    @property
    def total_source(self) -> int:
        return sum(s.source_rows for s in self.stats.values())

    @property
    def total_loaded(self) -> int:
        return sum(s.loaded for s in self.stats.values())

    @property
    def total_rejected(self) -> int:
        return sum(s.rejected for s in self.stats.values())

    @property
    def total_coerced(self) -> int:
        return sum(s.coerced for s in self.stats.values())


def key_text(values: list) -> str:
    """Name a row by its key columns, the same way the SQL key expression does."""
    out = []
    for v in values:
        if v is None:
            out.append(NULL_KEY)
        elif isinstance(v, bool):
            out.append("t" if v else "f")
        else:
            out.append(format(v, "f") if hasattr(v, "as_tuple") else str(v))
    return KEY_SEP.join(out)


def key_sql(t: TablePlan, alias: str) -> str:
    if not t.key_cols:
        return "NULL"
    parts = ", ".join(f"coalesce({alias}.{ddl.qi(c)}::text, '{NULL_KEY}')" for c in t.key_cols)
    return f"concat_ws(chr(31), {parts})"


def _create_meta(cur, s: str) -> None:
    cur.execute(
        f"""CREATE TABLE {ddl.qi(s)}.{REJECTS} (
              id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              table_name text NOT NULL, row_key text, reason text NOT NULL,
              constraint_name text, row_data jsonb NOT NULL,
              rejected_at timestamptz NOT NULL DEFAULT now())"""
    )
    cur.execute(
        f"""CREATE TABLE {ddl.qi(s)}.{COERCED} (
              id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              table_name text NOT NULL, row_key text, column_name text NOT NULL,
              rule text NOT NULL, source_value text NOT NULL, target_value text)"""
    )
    cur.execute(
        f"""CREATE TABLE {ddl.qi(s)}.{RUNLOG} (
              id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
              tool_version text NOT NULL, source_version text NOT NULL, source_schema text NOT NULL,
              started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
              source_counts jsonb NOT NULL, decisions jsonb NOT NULL, warnings jsonb NOT NULL)"""
    )


def _load_table(src, cur, s: str, t: TablePlan, stats: TableStats, log) -> None:
    cols = [c.name for c in t.columns]
    sel = "SELECT " + ", ".join(f"`{c}`" for c in cols) + f" FROM `{t.name}`"
    key_idx = [cols.index(c) for c in (t.key_cols or ())]
    coerced_rows: list[tuple] = []
    copy_sql = f"COPY {ddl.qi(s)}.{ddl.qi(t.name)} ({', '.join(ddl.qi(c) for c in cols)}) FROM STDIN"
    with src.cursor(pymysql.cursors.SSCursor) as sc:
        sc.execute(sel)
        with cur.copy(copy_sql) as cp:
            for raw in sc:
                out = []
                row_coercions = []
                for i, cp_ in enumerate(t.columns):
                    v, co = convert_value(raw[i], cp_.col, cp_.pg)
                    out.append(v)
                    if co is not None:
                        row_coercions.append((cp_.name, co))
                cp.write_row(out)
                if row_coercions:
                    key = key_text([out[i] for i in key_idx]) if key_idx else None
                    for cname, co in row_coercions:
                        coerced_rows.append((t.name, key, cname, co.rule, co.source_value, co.target_value))
    if coerced_rows:
        cur.executemany(
            f"INSERT INTO {ddl.qi(s)}.{COERCED} (table_name,row_key,column_name,rule,source_value,target_value) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            coerced_rows,
        )
    stats.coerced = len(coerced_rows)


def _sweep_orphans(cur, s: str, plan: Plan, stats: dict[str, TableStats], log) -> None:
    """Quarantine rows whose parent is missing. Tables are visited parents first, so a rejected parent makes its
    children orphans in turn (the cascade). A table that points at itself is swept until nothing more moves."""
    for name in plan.order:
        t = plan.tables[name]
        if not t.fks:
            continue
        while True:
            moved = 0
            for fk in t.fks:
                notnull = " AND ".join(f"c.{ddl.qi(c)} IS NOT NULL" for c in fk.columns)
                match = " AND ".join(
                    f"p.{ddl.qi(rc)} = c.{ddl.qi(c)}" for c, rc in zip(fk.columns, fk.ref_columns, strict=True)
                )
                reason = f"orphan: no parent in {fk.ref_table}({', '.join(fk.ref_columns)})"
                cur.execute(
                    f"""WITH bad AS (
                          DELETE FROM {ddl.qi(s)}.{ddl.qi(name)} c
                          WHERE {notnull}
                            AND NOT EXISTS (SELECT 1 FROM {ddl.qi(s)}.{ddl.qi(fk.ref_table)} p WHERE {match})
                          RETURNING c.*)
                        INSERT INTO {ddl.qi(s)}.{REJECTS} (table_name, row_key, reason, constraint_name, row_data)
                        SELECT %s, {key_sql(t, 'bad')}, %s, %s, to_jsonb(bad) FROM bad""",
                    (name, reason, fk.name),
                )
                n = cur.rowcount
                if n:
                    stats[name].rejected += n
                    moved += n
                    log(f"  quarantined {n} rows from {name} ({fk.name})")
            if not moved or not any(f.ref_table == name for f in t.fks):
                break


def _reset_identity(cur, s: str, t: TablePlan) -> None:
    if not t.identity:
        return
    q = f"{ddl.qi(s)}.{ddl.qi(t.name)}"
    cur.execute(f"SELECT max({ddl.qi(t.identity)}) FROM {q}")
    mx = cur.fetchone()[0] or 0
    nxt = max(t.auto_increment or 1, mx + 1)
    cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (q, t.identity))
    seq = cur.fetchone()[0]
    if nxt <= 1:
        cur.execute("SELECT setval(%s, 1, false)", (seq,))
    else:
        cur.execute("SELECT setval(%s, %s, true)", (seq, nxt - 1))


def run(
    mysql_cfg: MysqlConfig | None = None,
    pg_cfg: PgConfig | None = None,
    *,
    dry_run: bool = False,
    schema: str = PG_SCHEMA,
    log: Callable[[str], None] = print,
) -> RunReport:
    mysql_cfg = mysql_cfg or MysqlConfig.from_env()
    pg_cfg = pg_cfg or PgConfig.from_env()
    started = datetime.now(UTC)
    src = mysql_connect(mysql_cfg)
    pg = pg_connect(pg_cfg, autocommit=True)
    try:
        with pg.cursor() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS citext")
        pg.autocommit = False

        schema_info = read_schema(src, mysql_cfg.database)

        def non_boolean(table: str, column: str) -> int:
            with src.cursor() as c:
                c.execute(f"SELECT COUNT(*) FROM `{table}` WHERE `{column}` IS NOT NULL AND `{column}` NOT IN (0, 1)")
                return c.fetchone()[0]

        plan = build_plan(schema_info, non_boolean)
        for w in plan.warnings:
            log(f"warning: {w}")
        report = RunReport(dry_run, plan, {n: TableStats() for n in plan.order})

        nxt, prev = f"{schema}_next", f"{schema}_prev"
        cur = pg.cursor()
        cur.execute(f"DROP SCHEMA IF EXISTS {ddl.qi(nxt)} CASCADE")
        cur.execute(f"CREATE SCHEMA {ddl.qi(nxt)}")
        _create_meta(cur, nxt)
        for name in plan.order:
            cur.execute(ddl.create_table(nxt, plan.tables[name]))

        with src.cursor() as c:
            c.execute("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT")
        try:
            for name in plan.order:
                t = plan.tables[name]
                with src.cursor() as c:
                    c.execute(f"SELECT COUNT(*) FROM `{name}`")
                    report.stats[name].source_rows = c.fetchone()[0]
                _load_table(src, cur, nxt, t, report.stats[name], log)
                log(f"  copied {name}: {report.stats[name].source_rows} rows")
        finally:
            with src.cursor() as c:
                c.execute("ROLLBACK")

        for name in plan.order:
            t = plan.tables[name]
            stmt = ddl.add_primary_key(nxt, t)
            if stmt:
                cur.execute(stmt)
            for u in t.uniques:
                cur.execute(ddl.add_unique(nxt, t, u))
        _sweep_orphans(cur, nxt, plan, report.stats, log)
        for name in plan.order:
            t = plan.tables[name]
            for i in t.indexes:
                cur.execute(ddl.create_index(nxt, t, i))
        for fk in plan.all_fks():
            cur.execute(ddl.add_foreign_key(nxt, fk))
        for name in plan.order:
            _reset_identity(cur, nxt, plan.tables[name])
            cur.execute(f"SELECT count(*) FROM {ddl.qi(nxt)}.{ddl.qi(name)}")
            report.stats[name].loaded = cur.fetchone()[0]
            st = report.stats[name]
            if st.source_rows != st.loaded + st.rejected:
                raise RuntimeError(f"{name}: {st.source_rows} read, {st.loaded} loaded, {st.rejected} quarantined")

        cur.execute(
            f"INSERT INTO {ddl.qi(nxt)}.{RUNLOG} VALUES (1, %s, %s, %s, %s, now(), %s, %s, %s)",
            (
                __version__,
                schema_info.server_version,
                mysql_cfg.database,
                started,
                json.dumps({n: s.source_rows for n, s in report.stats.items()}),
                json.dumps(plan.decisions),
                json.dumps(plan.warnings),
            ),
        )

        if dry_run:
            pg.rollback()
            log("dry run: everything above was executed and rolled back; the target is unchanged")
        else:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = %s)", (schema,)
            )
            had_current = cur.fetchone()[0]
            cur.execute(f"DROP SCHEMA IF EXISTS {ddl.qi(prev)} CASCADE")
            if had_current:
                cur.execute(f"ALTER SCHEMA {ddl.qi(schema)} RENAME TO {ddl.qi(prev)}")
            cur.execute(f"ALTER SCHEMA {ddl.qi(nxt)} RENAME TO {ddl.qi(schema)}")
            pg.commit()
            report.swapped = True
            report.previous_schema_kept = had_current
        return report
    except BaseException:
        pg.rollback()
        raise
    finally:
        pg.close()
        src.close()


def rollback(pg_cfg: PgConfig | None = None, *, schema: str = PG_SCHEMA, log: Callable[[str], None] = print) -> bool:
    """Put the previous schema back. Returns False when there is nothing to roll back to."""
    pg_cfg = pg_cfg or PgConfig.from_env()
    prev, bad = f"{schema}_prev", f"{schema}_rolledback"
    pg = pg_connect(pg_cfg)
    try:
        cur = pg.cursor()
        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)", ([schema, prev],))
        have = {r[0] for r in cur.fetchall()}
        if prev not in have:
            log(f"no {prev} schema; nothing to roll back to")
            return False
        cur.execute(f"DROP SCHEMA IF EXISTS {ddl.qi(bad)} CASCADE")
        if schema in have:
            cur.execute(f"ALTER SCHEMA {ddl.qi(schema)} RENAME TO {ddl.qi(bad)}")
        cur.execute(f"ALTER SCHEMA {ddl.qi(prev)} RENAME TO {ddl.qi(schema)}")
        pg.commit()
        log(f"rolled back: {prev} is {schema} again; the schema you rolled away from is {bad}")
        return True
    finally:
        pg.close()
