"""The verifier. It trusts nothing the migrator says about itself.

It reads MySQL and PostgreSQL separately and works out for itself:
  * which source rows ought to have been quarantined (it replays the foreign keys over the source data),
  * what each value ought to look like after the move (its own canonical form, not the migrator's converters),
  * a count and an order-independent hash of every column, over the rows that ought to have survived,
  * the money total of every decimal column, plus the money in the quarantine, so it adds up to the source,
  * a seeded sample of rows compared field by field,
  * that every foreign key exists, is validated, and has no orphan, and that sequences sit above the data.
Any mismatch of one row, one cent or one character fails the run.
"""

from __future__ import annotations

import hashlib
import random
import struct
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from .config import PG_SCHEMA, MysqlConfig, PgConfig
from .db import mysql_connect, pg_connect
from .ddl import pg_name, qi
from .introspect import ForeignKey, SourceSchema, Table, read_schema
from .plan import effective_fks, topo_order
from .typemap import MyColumn, parse_mysql_temporal

NULL = "\x00NULL"
SEP = "\x1f"
MOD = 1 << 128
SAMPLE_SIZE = 150
INT_TYPES = {"tinyint", "smallint", "mediumint", "int", "bigint"}
TEXT_TYPES = {"varchar", "char", "text", "tinytext", "mediumtext", "longtext"}
BLOB_TYPES = {"blob", "tinyblob", "mediumblob", "longblob", "binary", "varbinary"}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    table: str = ""


@dataclass
class TableFacts:
    source: int = 0
    target: int = 0
    rejected: int = 0
    expected_rejected: int = 0
    columns_hashed: int = 0
    sampled: int = 0
    coerced_expected: int = 0


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)
    tables: dict[str, TableFacts] = field(default_factory=dict)
    money: dict[str, Decimal] = field(default_factory=dict)  # "table.column" -> target total
    quarantined_money: dict[str, Decimal] = field(default_factory=dict)
    source_money: dict[str, Decimal] = field(default_factory=dict)  # over ALL source rows

    def add(self, name: str, ok: bool, detail: str = "", table: str = "") -> None:
        self.checks.append(Check(name, ok, detail, table))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


# --- canonical forms (written for this file; nothing is imported from typemap's converters) ---------------


def _f32(x: float) -> str:
    return repr(struct.unpack("f", struct.pack("f", x))[0])


def _fmt_ts(dt: datetime) -> str:
    s = dt.strftime("%Y-%m-%d %H:%M:%S")
    return s + (f".{dt.microsecond:06d}".rstrip("0") if dt.microsecond else "")


def canon_source(v, c: MyColumn) -> str:
    """What this MySQL value must look like in PostgreSQL, as text."""
    dt = c.data_type
    if dt in ("timestamp", "datetime", "date"):
        if v is None:
            return NULL
        parsed = parse_mysql_temporal(v)
        if parsed is None:  # zero or impossible date: NULL when the column allows it, else 1970-01-01
            if c.nullable:
                return NULL
            return "1970-01-01" if dt == "date" else "1970-01-01 00:00:00"
        return parsed.isoformat() if dt == "date" else _fmt_ts(parsed)
    if v is None:
        return NULL
    if dt in INT_TYPES:
        return str(int(v))
    if dt in ("decimal", "numeric"):
        return format(Decimal(v).quantize(Decimal(1).scaleb(-(c.num_scale or 0))), "f")
    if dt == "float":
        return _f32(float(v))
    if dt == "double":
        return repr(float(v))
    if dt in TEXT_TYPES:
        return v if isinstance(v, str) else bytes(v).decode()
    if dt in BLOB_TYPES:
        return bytes(v).hex()
    raise ValueError(f"verifier has no canonical form for {c.column_type}")


def canon_target(v) -> str:
    """The same text, from what psycopg returns."""
    if v is None:
        return NULL
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return _fmt_ts(v.astimezone(UTC).replace(tzinfo=None) if v.tzinfo else v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return str(v)


def canon_target_col(v, c: MyColumn) -> str:
    if v is not None and c.data_type == "float":
        return _f32(float(v))
    return canon_target(v)


def h128(s: str) -> int:
    return int.from_bytes(hashlib.sha256(s.encode("utf-8", "surrogatepass")).digest()[:16], "big")


class ColAcc:
    """Order independent fingerprint of a column: row count and the sum of 128 bit hashes."""

    __slots__ = ("n", "h")

    def __init__(self) -> None:
        self.n = 0
        self.h = 0

    def add(self, s: str) -> None:
        self.n += 1
        self.h = (self.h + h128(s)) % MOD

    def __eq__(self, o: object) -> bool:
        return isinstance(o, ColAcc) and (self.n, self.h) == (o.n, o.h)

    def __repr__(self) -> str:
        return f"{self.n}:{self.h:032x}"


def _key_part(s: str) -> str:
    return "\\N" if s == NULL else s


# --- the run --------------------------------------------------------------------------------------------------


def _source_rows(conn, t: Table):
    cols = ", ".join(f"`{c.name}`" for c in t.columns)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {cols} FROM `{t.name}`")
        yield from cur.fetchall()


def _pk_cols(t: Table) -> tuple[str, ...] | None:
    return next((i.columns for i in t.indexes if i.primary), None)


def verify(
    mysql_cfg: MysqlConfig | None = None,
    pg_cfg: PgConfig | None = None,
    *,
    schema: str = PG_SCHEMA,
    seed: int = 7,
) -> VerifyReport:
    mysql_cfg = mysql_cfg or MysqlConfig.from_env()
    pg_cfg = pg_cfg or PgConfig.from_env()
    rep = VerifyReport()
    src = mysql_connect(mysql_cfg)
    pg = pg_connect(pg_cfg, autocommit=True)
    try:
        with src.cursor() as c:
            c.execute("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT")
        sch = read_schema(src, mysql_cfg.database)
        fks = effective_fks(sch)
        all_fks = [fk for lst in fks.values() for fk in lst]
        order = topo_order(list(sch.tables), all_fks)
        pgc = pg.cursor()

        _check_schema_shape(rep, sch, fks, pgc, schema)

        # parent key sets the replay needs: (table, columns) -> set of canonical tuples of surviving rows
        needed: dict[str, set[tuple[str, ...]]] = {}
        for fk in all_fks:
            needed.setdefault(fk.ref_table, set()).add(fk.ref_columns)
        parents: dict[tuple[str, tuple[str, ...]], set[tuple[str, ...]]] = {}

        pgc.execute(f"SELECT table_name, count(*) FROM {qi(schema)}._tillcarry_rejects GROUP BY 1")
        rejects_by_table = dict(pgc.fetchall())
        pgc.execute(f"SELECT table_name, rule, count(*) FROM {qi(schema)}._tillcarry_coerced GROUP BY 1, 2")
        coerced_logged: dict[tuple[str, str], int] = {(a, b): n for a, b, n in pgc.fetchall()}
        coerced_seen: dict[tuple[str, str], int] = {}

        rng = random.Random(seed)
        for name in order:
            t = sch.tables[name]
            facts = rep.tables.setdefault(name, TableFacts())
            _verify_table(rep, facts, src, pgc, sch, t, fks[name], parents, needed, schema, rng, coerced_seen)
            facts.rejected = rejects_by_table.get(name, 0)
            _check_counts(rep, name, facts)

        extra = set(rejects_by_table) - set(sch.tables)
        rep.add("rejects only name real tables", not extra, f"unknown: {sorted(extra)}" if extra else "")
        rep.add(
            "zero dates: every one found in the source is logged as coerced, nothing else is",
            coerced_logged == coerced_seen,
            f"logged {dict(sorted(coerced_logged.items()))} vs found {dict(sorted(coerced_seen.items()))}",
        )
        _check_money_reconciles(rep, sch, pgc, schema)
        _check_foreign_keys(rep, all_fks, pgc, schema)
        _check_sequences(rep, sch, pgc, schema)
        _check_reject_rows(rep, pgc, schema)
    finally:
        try:
            with src.cursor() as c:
                c.execute("ROLLBACK")
        finally:
            src.close()
            pg.close()
    return rep


def _check_schema_shape(rep: VerifyReport, sch: SourceSchema, fks, pgc, schema: str) -> None:
    pgc.execute(
        "SELECT table_name, column_name, is_nullable, ordinal_position FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name NOT LIKE '\\_tillcarry%%' ORDER BY table_name, ordinal_position",
        (schema,),
    )
    got: dict[str, list[tuple[str, bool]]] = {}
    for t, c, nullable, _ in pgc.fetchall():
        got.setdefault(t, []).append((c, nullable == "YES"))
    want = {n: [(c.name, c.nullable) for c in t.columns] for n, t in sch.tables.items()}
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    rep.add("same tables", not missing and not extra, f"missing {missing} extra {extra}" if missing or extra else f"{len(want)} tables")
    bad = [n for n in want if n in got and got[n] != want[n]]
    rep.add("same columns, order and nullability", not bad, f"differ: {bad}" if bad else "")

    pgc.execute(
        "SELECT t.relname, c.contype, array_agg(a.attname ORDER BY k.ord) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) "
        "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.attnum "
        "WHERE n.nspname=%s AND c.contype IN ('p','u') GROUP BY c.oid, t.relname, c.contype",
        (schema,),
    )
    pg_keys: set[tuple[str, str, frozenset[str]]] = {(t, k, frozenset(cols)) for t, k, cols in pgc.fetchall()}
    missing_keys = []
    for n, t in sch.tables.items():
        for i in t.indexes:
            if i.unique and (n, "p" if i.primary else "u", frozenset(i.columns)) not in pg_keys:
                missing_keys.append(f"{n}({','.join(i.columns)})")
    rep.add("every primary and unique key exists", not missing_keys, f"missing {missing_keys}" if missing_keys else "")

    pgc.execute(
        "SELECT t.relname, array_agg(a.attname ORDER BY k.ord) FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord) "
        "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.attnum "
        "WHERE n.nspname=%s GROUP BY i.indexrelid, t.relname",
        (schema,),
    )
    pg_idx = {(t, tuple(cols)) for t, cols in pgc.fetchall()}
    missing_idx = [
        f"{n}({','.join(i.columns)})"
        for n, t in sch.tables.items()
        for i in t.indexes
        if (n, i.columns) not in pg_idx
    ]
    rep.add("every index exists", not missing_idx, f"missing {missing_idx}" if missing_idx else "")


def _check_counts(rep: VerifyReport, name: str, f: TableFacts) -> None:
    rep.add(
        "row count: source = loaded + quarantined",
        f.source == f.target + f.rejected,
        f"{f.source} = {f.target} + {f.rejected}",
        name,
    )
    rep.add(
        "quarantine matches the replay of the foreign keys over the source",
        f.rejected == f.expected_rejected,
        f"quarantined {f.rejected}, replay expects {f.expected_rejected}",
        name,
    )


def _verify_table(rep, facts, src, pgc, sch, t, table_fks, parents, needed, schema, rng, coerced_seen) -> None:
    name = t.name
    cols = t.columns
    names = [c.name for c in cols]
    idx = {n: i for i, n in enumerate(names)}
    pk = _pk_cols(t)

    # 1. source: canonical rows, then which of them should survive
    raw_rows = list(_source_rows(src, t))
    rows = [[canon_source(v, c) for v, c in zip(r, cols, strict=True)] for r in raw_rows]
    facts.source = len(rows)
    for r_raw in raw_rows:
        for v, c in zip(r_raw, cols, strict=True):
            if c.data_type in ("timestamp", "datetime", "date") and v is not None and parse_mysql_temporal(v) is None:
                rule = "zero_date_to_null" if c.nullable else "zero_date_to_epoch"
                coerced_seen[(name, rule)] = coerced_seen.get((name, rule), 0) + 1

    alive = [True] * len(rows)
    for fk in table_fks:
        if fk.ref_table == name:
            continue
        pset = parents[(fk.ref_table, fk.ref_columns)]
        ci = [idx[c] for c in fk.columns]
        for n, r in enumerate(rows):
            if alive[n]:
                tup = tuple(r[i] for i in ci)
                if NULL not in tup and tup not in pset:
                    alive[n] = False
    for fk in [f for f in table_fks if f.ref_table == name]:  # self reference: repeat until stable
        ci = [idx[c] for c in fk.columns]
        rc = [idx[c] for c in fk.ref_columns]
        changed = True
        while changed:
            changed = False
            live = {tuple(r[i] for i in rc) for n, r in enumerate(rows) if alive[n]}
            for n, r in enumerate(rows):
                if alive[n]:
                    tup = tuple(r[i] for i in ci)
                    if NULL not in tup and tup not in live:
                        alive[n] = False
                        changed = True
    facts.expected_rejected = alive.count(False)
    for ref_cols in needed.get(name, ()):
        ci = [idx[c] for c in ref_cols]
        parents[(name, ref_cols)] = {tuple(r[i] for i in ci) for n, r in enumerate(rows) if alive[n]}

    # 2. the keys of the rows the replay says should be quarantined, against the rejects table
    key_cols = pk
    if key_cols is None:
        key_cols = next(
            (i.columns for i in t.indexes if i.unique and all(not t.column(c).nullable for c in i.columns)), None
        )
    if key_cols:
        ki = [idx[c] for c in key_cols]
        expect_keys = sorted(SEP.join(_key_part(r[i]) for i in ki) for n, r in enumerate(rows) if not alive[n])
        pgc.execute(
            f"SELECT row_key FROM {qi(schema)}._tillcarry_rejects WHERE table_name=%s ORDER BY 1", (name,)
        )
        got_keys = sorted(r[0] for r in pgc.fetchall())
        rep.add(
            "the exact rows quarantined are the rows the replay expects",
            expect_keys == got_keys,
            f"expected {len(expect_keys)} keys, found {len(got_keys)}" + ("" if expect_keys == got_keys else f"; first diff {_first_diff(expect_keys, got_keys)}"),
            name,
        )

    # 3. target rows
    sel = ", ".join(qi(n) for n in names)
    pgc.execute(f"SELECT {sel} FROM {qi(schema)}.{qi(name)}")
    trows = [[canon_target_col(v, c) for v, c in zip(r, cols, strict=True)] for r in pgc.fetchall()]
    facts.target = len(trows)

    # 4. order independent fingerprint of every column
    bad_cols = []
    for j, c in enumerate(cols):
        a, b = ColAcc(), ColAcc()
        for n, r in enumerate(rows):
            if alive[n]:
                a.add(r[j])
        for r in trows:
            b.add(r[j])
        if a != b:
            bad_cols.append(f"{c.name} (source {a!r} vs target {b!r})")
    facts.columns_hashed = len(cols)
    rep.add(
        f"checksum of all {len(cols)} columns over the surviving rows",
        not bad_cols,
        "; ".join(bad_cols[:3]) if bad_cols else "",
        name,
    )
    whole_a, whole_b = ColAcc(), ColAcc()
    for n, r in enumerate(rows):
        if alive[n]:
            whole_a.add(SEP.join(r))
    for r in trows:
        whole_b.add(SEP.join(r))
    rep.add("checksum of whole rows (catches values swapped between rows)", whole_a == whole_b, "" if whole_a == whole_b else f"{whole_a!r} vs {whole_b!r}", name)

    # 5. a seeded sample compared field by field, by key
    if key_cols:
        ki = [idx[c] for c in key_cols]
        src_by_key = {SEP.join(_key_part(r[i]) for i in ki): r for n, r in enumerate(rows) if alive[n]}
        dst_by_key = {SEP.join(_key_part(r[i]) for i in ki): r for r in trows}
        keys = sorted(src_by_key)
        sample = keys if len(keys) <= SAMPLE_SIZE else rng.sample(keys, SAMPLE_SIZE)
        diffs = []
        for k in sample:
            d = dst_by_key.get(k)
            if d is None:
                diffs.append(f"key {k!r} missing in target")
                continue
            for j, c in enumerate(cols):
                if src_by_key[k][j] != d[j]:
                    diffs.append(f"key {k!r} column {c.name}: {src_by_key[k][j]!r} vs {d[j]!r}")
        facts.sampled = len(sample)
        rep.add(f"{len(sample)} sampled rows equal field by field", not diffs, "; ".join(diffs[:3]), name)

    # 6. money, exact
    for j, c in enumerate(cols):
        if c.data_type != "decimal":
            continue
        src_total = sum((Decimal(r[j]) for n, r in enumerate(rows) if alive[n] and r[j] != NULL), Decimal(0))
        pgc.execute(f"SELECT coalesce(sum({qi(c.name)}), 0) FROM {qi(schema)}.{qi(name)}")
        dst_total = pgc.fetchone()[0]
        rep.money[f"{name}.{c.name}"] = dst_total
        rep.source_money[f"{name}.{c.name}"] = sum((Decimal(r[j]) for r in rows if r[j] != NULL), Decimal(0))
        rep.add(
            f"sum of {c.name} to the cent",
            src_total == dst_total,
            f"{src_total} vs {dst_total}" if src_total != dst_total else f"{dst_total}",
            name,
        )


def _first_diff(a: list[str], b: list[str]) -> str:
    sa, sb = set(a), set(b)
    only_a, only_b = sorted(sa - sb)[:2], sorted(sb - sa)[:2]
    return f"only expected {only_a}, only found {only_b}"


def _check_money_reconciles(rep: VerifyReport, sch: SourceSchema, pgc, schema: str) -> None:
    """Source total = loaded total + quarantined total, for every decimal column. No money disappears."""
    bad = []
    for key, loaded in rep.money.items():
        table, col = key.split(".", 1)
        pgc.execute(
            f"SELECT coalesce(sum((row_data->>%s)::numeric), 0) FROM {qi(schema)}._tillcarry_rejects WHERE table_name=%s",
            (col, table),
        )
        q = pgc.fetchone()[0]
        rep.quarantined_money[key] = q
        total = rep.source_money[key]
        if total != loaded + q:
            bad.append(f"{key}: source {total} vs loaded {loaded} + quarantined {q}")
    rep.add("money: source total = loaded + quarantined for every decimal column", not bad, "; ".join(bad[:3]))


def _check_foreign_keys(rep: VerifyReport, all_fks: list[ForeignKey], pgc, schema: str) -> None:
    pgc.execute(
        "SELECT t.relname, c.conname, c.convalidated FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=%s AND c.contype='f'",
        (schema,),
    )
    present = {(t, n): v for t, n, v in pgc.fetchall()}
    orphans: list[str] = []
    for fk in all_fks:
        cond = " AND ".join(f"c.{qi(x)} IS NOT NULL" for x in fk.columns)
        match = " AND ".join(f"p.{qi(rc)}=c.{qi(x)}" for x, rc in zip(fk.columns, fk.ref_columns, strict=True))
        pgc.execute(
            f"SELECT count(*) FROM {qi(schema)}.{qi(fk.table)} c WHERE {cond} AND NOT EXISTS "
            f"(SELECT 1 FROM {qi(schema)}.{qi(fk.ref_table)} p WHERE {match})"
        )
        n = pgc.fetchone()[0]
        if n:
            orphans.append(f"{fk.table}.{fk.name}: {n}")
    absent = [f"{fk.table}.{fk.name}" for fk in all_fks if (fk.table, pg_name(fk.table, fk.name)) not in present]
    unvalidated = [k for k, v in present.items() if not v]
    rep.add(f"all {len(all_fks)} foreign keys exist", not absent, f"missing {absent}" if absent else "")
    rep.add("every foreign key is validated", not unvalidated, str(unvalidated) if unvalidated else "")
    rep.add("no orphan row in the target (anti-join on every foreign key)", not orphans, "; ".join(orphans))


def _check_sequences(rep: VerifyReport, sch: SourceSchema, pgc, schema: str) -> None:
    bad = []
    n = 0
    for t in sch.tables.values():
        ident = next((c.name for c in t.columns if "auto_increment" in c.extra), None)
        if not ident:
            continue
        n += 1
        q = f"{qi(schema)}.{qi(t.name)}"
        pgc.execute("SELECT pg_get_serial_sequence(%s, %s)", (q, ident))
        seq = pgc.fetchone()[0]
        pgc.execute(f"SELECT last_value, is_called FROM {seq}")
        last, called = pgc.fetchone()
        nxt = last + 1 if called else last
        pgc.execute(f"SELECT coalesce(max({qi(ident)}), 0) FROM {q}")
        mx = pgc.fetchone()[0]
        want = max(t.auto_increment or 1, mx + 1)
        if nxt != want:
            bad.append(f"{t.name}.{ident}: next {nxt}, want {want}")
    rep.add(f"{n} identity sequences continue where MySQL AUTO_INCREMENT left off", not bad, "; ".join(bad[:3]))


def _check_reject_rows(rep: VerifyReport, pgc, schema: str) -> None:
    pgc.execute(
        f"SELECT count(*) FROM {qi(schema)}._tillcarry_rejects "
        "WHERE coalesce(reason,'') = '' OR row_data IS NULL OR row_data = '{}'::jsonb"
    )
    n = pgc.fetchone()[0]
    rep.add("every quarantined row carries a reason and its full data", n == 0, f"{n} incomplete" if n else "")
