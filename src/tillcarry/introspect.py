"""Read a MySQL schema from information_schema into plain dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field

from .typemap import MyColumn


@dataclass(frozen=True)
class Index:
    name: str
    unique: bool
    columns: tuple[str, ...]
    primary: bool = False


@dataclass(frozen=True)
class ForeignKey:
    name: str
    table: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]
    on_delete: str = "NO ACTION"
    origin: str = "source"  # source | replacement | added


@dataclass
class Table:
    name: str
    columns: list[MyColumn] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    fks: list[ForeignKey] = field(default_factory=list)
    auto_increment: int | None = None

    def column(self, name: str) -> MyColumn:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)


@dataclass
class SourceSchema:
    name: str
    tables: dict[str, Table]
    server_version: str = ""


def read_schema(conn, schema: str) -> SourceSchema:
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    version = cur.fetchone()[0]

    cur.execute(
        "SELECT TABLE_NAME, AUTO_INCREMENT FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
        (schema,),
    )
    tables = {n: Table(n, auto_increment=ai) for n, ai in cur.fetchall()}

    cur.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, "
        "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION",
        (schema,),
    )
    for t, c, dt, ct, nullable, default, extra, clen, prec, scale in cur.fetchall():
        if t not in tables:
            continue
        is_num = dt in ("decimal", "numeric")
        tables[t].columns.append(
            MyColumn(
                name=c,
                data_type=dt.lower(),
                column_type=ct.lower(),
                nullable=(nullable == "YES"),
                default=default,
                extra=(extra or "").lower().replace("default_generated", "DEFAULT_GENERATED"),
                char_max_len=clen,
                num_precision=int(prec) if is_num and prec is not None else None,
                num_scale=int(scale) if is_num and scale is not None else None,
            )
        )

    cur.execute(
        "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, SUB_PART "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s "
        "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
        (schema,),
    )
    grouped: dict[tuple[str, str], list] = {}
    for t, idx, non_unique, _seq, col, sub in cur.fetchall():
        if sub is not None:
            raise ValueError(f"{t}.{idx} uses a prefix index on {col}; not supported")
        grouped.setdefault((t, idx), [int(non_unique), []])[1].append(col)
    for (t, idx), (non_unique, cols) in grouped.items():
        if t in tables:
            tables[t].indexes.append(Index(idx, non_unique == 0, tuple(cols), primary=(idx == "PRIMARY")))

    cur.execute(
        "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, "
        "k.REFERENCED_COLUMN_NAME, r.DELETE_RULE "
        "FROM information_schema.KEY_COLUMN_USAGE k "
        "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
        "  ON r.CONSTRAINT_SCHEMA=k.TABLE_SCHEMA AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME AND r.TABLE_NAME=k.TABLE_NAME "
        "WHERE k.TABLE_SCHEMA=%s AND k.REFERENCED_TABLE_NAME IS NOT NULL "
        "ORDER BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION",
        (schema,),
    )
    fk_rows: dict[tuple[str, str], list] = {}
    for t, cname, _pos, col, rt, rc, rule in cur.fetchall():
        fk_rows.setdefault((t, cname), [rt, rule, [], []])
        fk_rows[(t, cname)][2].append(col)
        fk_rows[(t, cname)][3].append(rc)
    for (t, cname), (rt, rule, cols, rcols) in fk_rows.items():
        if t in tables:
            tables[t].fks.append(ForeignKey(cname, t, tuple(cols), rt, tuple(rcols), rule))
    cur.close()
    return SourceSchema(schema, tables, version)
