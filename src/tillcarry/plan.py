"""Turn a SourceSchema into a migration plan: PostgreSQL types, constraints, the load order, and a list of every
decision that was not a straight copy. Pure given a data check callback, so tests need no database."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .introspect import ForeignKey, Index, SourceSchema, Table
from .typemap import MyColumn, PgType, is_boolean_candidate, map_default, map_type

# A foreign key whose parent columns are not a PRIMARY or UNIQUE key cannot exist in PostgreSQL. These are the
# documented repairs. Anything not listed here is skipped with a warning, never guessed.
FK_REPLACEMENTS: dict[tuple[str, str], ForeignKey] = {
    ("ospos_sales_items_taxes", "ospos_sales_items_taxes_ibfk_1"): ForeignKey(
        name="ospos_sales_items_taxes_sale_line_fk",
        table="ospos_sales_items_taxes",
        columns=("sale_id", "item_id", "line"),
        ref_table="ospos_sales_items",
        ref_columns=("sale_id", "item_id", "line"),
        origin="replacement",
    ),
}

# Relations the application relies on but the MySQL schema never declared. Adding them is what makes orphan
# rows visible; they are quarantined, not deleted.
EXTRA_FKS: tuple[ForeignKey, ...] = (
    ForeignKey(
        name="ospos_sales_taxes_sale_fk",
        table="ospos_sales_taxes",
        columns=("sale_id",),
        ref_table="ospos_sales",
        ref_columns=("sale_id",),
        origin="added",
    ),
)


@dataclass
class ColumnPlan:
    col: MyColumn
    pg: PgType
    default_sql: str | None

    @property
    def name(self) -> str:
        return self.col.name


@dataclass
class TablePlan:
    name: str
    columns: list[ColumnPlan]
    pk: tuple[str, ...] | None
    uniques: list[Index]
    indexes: list[Index]
    fks: list[ForeignKey]
    identity: str | None
    auto_increment: int | None
    key_cols: tuple[str, ...] | None  # how a row is named in the rejects and coerced logs

    def col(self, name: str) -> ColumnPlan:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)


@dataclass
class Plan:
    tables: dict[str, TablePlan]
    order: list[str]
    warnings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    def all_fks(self) -> list[ForeignKey]:
        return [fk for t in self.order for fk in self.tables[t].fks]


def covers_unique(table: Table, columns: tuple[str, ...]) -> bool:
    """True when `columns` (as a set) is exactly the PRIMARY KEY or a UNIQUE key of `table`."""
    want = set(columns)
    return any(i.unique and set(i.columns) == want for i in table.indexes)


def topo_order(tables: list[str], fks: list[ForeignKey]) -> list[str]:
    """Parents before children. A self reference is ignored for ordering. Raises on a real cycle."""
    deps: dict[str, set[str]] = {t: set() for t in tables}
    for fk in fks:
        if fk.ref_table != fk.table and fk.ref_table in deps and fk.table in deps:
            deps[fk.table].add(fk.ref_table)
    out: list[str] = []
    done: set[str] = set()
    remaining = sorted(tables)
    while remaining:
        ready = [t for t in remaining if deps[t] <= done]
        if not ready:
            raise ValueError(f"foreign key cycle among {remaining}")
        for t in ready:
            out.append(t)
            done.add(t)
        remaining = [t for t in remaining if t not in done]
    return out


def _case_insensitive_columns(schema: SourceSchema, fks: list[ForeignKey]) -> set[tuple[str, str]]:
    ci: set[tuple[str, str]] = set()
    for t in schema.tables.values():
        for idx in t.indexes:
            if idx.unique:
                for c in idx.columns:
                    if t.column(c).data_type in ("varchar", "char"):
                        ci.add((t.name, c))
    changed = True
    while changed:  # a foreign key joins two columns, so both must be the same PostgreSQL type
        changed = False
        for fk in fks:
            for c, rc in zip(fk.columns, fk.ref_columns, strict=True):
                a, b = (fk.table, c), (fk.ref_table, rc)
                if (a in ci) != (b in ci):
                    ci.add(a)
                    ci.add(b)
                    changed = True
    return ci


def effective_fks(
    schema: SourceSchema, warnings: list[str] | None = None, decisions: list[str] | None = None
) -> dict[str, list[ForeignKey]]:
    """The foreign keys PostgreSQL will get: source keys that can exist, documented replacements for the ones
    that cannot, and the documented additions. Shared with the verifier so both agree on what a parent is."""
    warnings = [] if warnings is None else warnings
    decisions = [] if decisions is None else decisions
    fks_by_table: dict[str, list[ForeignKey]] = {t: [] for t in schema.tables}
    for t in schema.tables.values():
        for fk in t.fks:
            parent = schema.tables.get(fk.ref_table)
            if parent is not None and covers_unique(parent, fk.ref_columns):
                fks_by_table[t.name].append(fk)
                continue
            repl = FK_REPLACEMENTS.get((t.name, fk.name))
            if repl is not None:
                fks_by_table[t.name].append(repl)
                decisions.append(
                    f"FK {fk.name} points at {fk.ref_table}({', '.join(fk.ref_columns)}) which is not unique; "
                    f"replaced by {repl.name} on ({', '.join(repl.columns)})"
                )
            else:
                warnings.append(f"FK {fk.name} skipped: {fk.ref_table}({', '.join(fk.ref_columns)}) is not unique")
    for fk in EXTRA_FKS:
        if fk.table in schema.tables and fk.ref_table in schema.tables:
            fks_by_table[fk.table].append(fk)
            decisions.append(f"FK {fk.name} added: {fk.table}({', '.join(fk.columns)}) -> {fk.ref_table}, absent in MySQL")
    return fks_by_table


def build_plan(schema: SourceSchema, non_boolean_values: Callable[[str, str], int]) -> Plan:
    """`non_boolean_values(table, column)` returns how many rows hold a value other than 0, 1 or NULL."""
    warnings: list[str] = []
    decisions: list[str] = []

    fks_by_table = effective_fks(schema, warnings, decisions)

    all_fks = [fk for lst in fks_by_table.values() for fk in lst]
    ci = _case_insensitive_columns(schema, all_fks)
    order = topo_order(list(schema.tables), all_fks)

    tables: dict[str, TablePlan] = {}
    for name in order:
        t = schema.tables[name]
        cols: list[ColumnPlan] = []
        for c in t.columns:
            boolean = False
            if is_boolean_candidate(name, c):
                bad = non_boolean_values(name, c.name)
                if bad == 0:
                    boolean = True
                    decisions.append(f"{name}.{c.name}: tinyint(1) -> boolean (allowlisted, data is 0/1/NULL)")
                else:
                    warnings.append(
                        f"{name}.{c.name}: allowlisted as boolean but {bad} rows hold other values; kept as smallint"
                    )
            elif c.column_type.replace(" ", "") == "tinyint(1)":
                decisions.append(f"{name}.{c.name}: tinyint(1) -> smallint (not a proven boolean)")
            ci_text = (name, c.name) in ci
            if ci_text:
                decisions.append(f"{name}.{c.name}: text in a UNIQUE key -> citext (utf8_general_ci was case-insensitive)")
            pg = map_type(name, c, boolean=boolean, case_insensitive=ci_text)
            cols.append(ColumnPlan(c, pg, map_default(c, pg)))

        pk = next((i.columns for i in t.indexes if i.primary), None)
        uniques = [i for i in t.indexes if i.unique and not i.primary]
        indexes = [i for i in t.indexes if not i.unique and not i.primary]
        identity = next((c.name for c in t.columns if c.auto_increment), None)
        key_cols = pk
        if key_cols is None:
            for u in uniques:
                if all(not t.column(c).nullable for c in u.columns):
                    key_cols = u.columns
                    break
        if pk is None:
            warnings.append(f"{name}: no primary key in MySQL" + (f"; rows are named by unique key {key_cols}" if key_cols else ""))
        tables[name] = TablePlan(
            name, cols, pk, uniques, indexes, fks_by_table[name], identity, t.auto_increment, key_cols
        )
    return Plan(tables, order, warnings, decisions)
