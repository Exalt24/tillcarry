"""Type mapping rules, MySQL to PostgreSQL. Pure functions, no database access, covered by tests/test_typemap.py.

The rules and the reasons behind them are written out in docs/type-mapping.md. Short version:

* tinyint(1) is NOT a boolean by default. Open Source Point of Sale uses tinyint(1) for status codes
  (sale_status, item_type) and bit flags (definition_flags). Only an explicit allowlist, and only when the
  column holds nothing but 0, 1 and NULL, becomes boolean.
* A varchar that sits in a UNIQUE key becomes citext, because MySQL's utf8_general_ci made that key
  case-insensitive and PostgreSQL's default collation does not.
* A zero date (0000-00-00) cannot exist in PostgreSQL. Nullable column: NULL. NOT NULL column: 1970-01-01,
  and either way the change is written to _tillcarry_coerced so it is never silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

EPOCH_DATE = date(1970, 1, 1)
EPOCH_NAIVE = datetime(1970, 1, 1)
EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)

# (table without prefix, column). "*" matches any table.
BOOLEAN_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("*", "deleted"),
        ("customers", "taxable"),
        ("items", "allow_alt_description"),
        ("items", "is_serialized"),
        ("dinner_tables", "status"),
    }
)

TABLE_PREFIX = "ospos_"


@dataclass(frozen=True)
class MyColumn:
    """One MySQL column as information_schema reports it."""

    name: str
    data_type: str  # int, tinyint, varchar, decimal, timestamp ...
    column_type: str  # int unsigned, tinyint(1), decimal(15,2) ...
    nullable: bool
    default: str | None
    extra: str  # auto_increment, DEFAULT_GENERATED ...
    char_max_len: int | None = None
    num_precision: int | None = None
    num_scale: int | None = None

    @property
    def unsigned(self) -> bool:
        return "unsigned" in self.column_type

    @property
    def auto_increment(self) -> bool:
        return "auto_increment" in self.extra


@dataclass(frozen=True)
class PgType:
    sql: str  # the type as written in CREATE TABLE
    kind: str  # int, bool, numeric, float, text, bytes, timestamptz, timestamp, date
    note: str = ""  # why this type, for the report


def short_table(table: str) -> str:
    return table[len(TABLE_PREFIX):] if table.startswith(TABLE_PREFIX) else table


def is_boolean_candidate(table: str, col: MyColumn) -> bool:
    """Schema level test: tinyint(1) and on the allowlist. The data test happens at plan time."""
    if col.data_type != "tinyint" or col.column_type.replace(" ", "") not in ("tinyint(1)",):
        return False
    t = short_table(table)
    return (t, col.name) in BOOLEAN_ALLOWLIST or ("*", col.name) in BOOLEAN_ALLOWLIST


def map_type(table: str, col: MyColumn, *, boolean: bool = False, case_insensitive: bool = False) -> PgType:
    """Map one column. `boolean` is the plan's decision (candidate AND data clean). `case_insensitive` is true
    for text columns that sit in a UNIQUE key."""
    dt = col.data_type
    if dt == "tinyint":
        if boolean:
            return PgType("boolean", "bool", "tinyint(1) on the allowlist, data is only 0/1/NULL")
        return PgType("smallint", "int", "tinyint is a small number, not a boolean")
    if dt == "smallint":
        return PgType("integer" if col.unsigned else "smallint", "int")
    if dt == "mediumint":
        return PgType("integer", "int")
    if dt == "int":
        return PgType("bigint" if col.unsigned else "integer", "int", "unsigned int needs bigint" if col.unsigned else "")
    if dt == "bigint":
        if col.unsigned:
            return PgType("numeric(20,0)", "numeric", "unsigned bigint can exceed bigint")
        return PgType("bigint", "int")
    if dt in ("decimal", "numeric"):
        p, s = col.num_precision or 65, col.num_scale or 0
        return PgType(f"numeric({p},{s})", "numeric", "exact decimal, same precision and scale")
    if dt == "float":
        return PgType("real", "float", "4 byte float, same bits")
    if dt == "double":
        return PgType("double precision", "float")
    if dt in ("varchar", "char"):
        n = col.char_max_len or 255
        if case_insensitive:
            return PgType("citext", "text", "UNIQUE key was case-insensitive under utf8_general_ci")
        return PgType(f"{'varchar' if dt == 'varchar' else 'char'}({n})", "text")
    if dt in ("text", "tinytext", "mediumtext", "longtext"):
        return PgType("text", "text")
    if dt in ("blob", "tinyblob", "mediumblob", "longblob", "binary", "varbinary"):
        return PgType("bytea", "bytes")
    if dt == "timestamp":
        return PgType("timestamptz", "timestamptz", "MySQL TIMESTAMP is stored in UTC")
    if dt == "datetime":
        return PgType("timestamp", "timestamp", "no zone in the source, none added")
    if dt == "date":
        return PgType("date", "date")
    raise ValueError(f"no mapping rule for MySQL type {col.column_type!r} ({dt})")


def map_default(col: MyColumn, pg: PgType) -> str | None:
    """The DEFAULT clause body for PostgreSQL, or None when there is none."""
    d = col.default
    if d is None:
        return None
    if "DEFAULT_GENERATED" in col.extra and d.upper().startswith("CURRENT_TIMESTAMP"):
        return "now()"
    if pg.kind == "bool":
        return "true" if d not in ("0", "") else "false"
    if pg.kind in ("int", "numeric", "float"):
        return str(Decimal(d)) if pg.kind == "numeric" else d
    if pg.kind == "bytes":
        return None
    return "'" + d.replace("'", "''") + "'"


# --- value conversion -------------------------------------------------------------------------------------

_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?)?$")


def parse_mysql_temporal(raw: str) -> datetime | date | None:
    """Parse MySQL's text form. Returns None for a zero or otherwise impossible date (0000-00-00, 2019-00-00,
    2019-02-31). Raises ValueError for text that is not a date at all."""
    m = _DT_RE.match(raw)
    if not m:
        raise ValueError(f"not a MySQL date or datetime: {raw!r}")
    y, mo, d, hh, mi, ss, frac = m.groups()
    year, month, day = int(y), int(mo), int(d)
    try:
        if hh is None:
            return date(year, month, day)
        micro = int((frac or "0").ljust(6, "0"))
        return datetime(year, month, day, int(hh), int(mi), int(ss), micro)
    except ValueError:
        return None


@dataclass(frozen=True)
class Coercion:
    """A value we had to change. Written to _tillcarry_coerced."""

    rule: str
    source_value: str
    target_value: str | None


def convert_value(raw, col: MyColumn, pg: PgType):
    """Convert one value from what PyMySQL returns to what psycopg should receive.
    Returns (value, Coercion | None)."""
    if raw is None:
        return None, None
    k = pg.kind
    if k == "bool":
        return bool(int(raw)), None
    if k == "int":
        return int(raw), None
    if k == "numeric":
        return (raw if isinstance(raw, Decimal) else Decimal(str(raw))), None
    if k == "float":
        return float(raw), None
    if k == "text":
        s = raw.decode() if isinstance(raw, bytes) else str(raw)
        if "\x00" in s:
            raise ValueError("NUL character in text; PostgreSQL cannot store it")
        return s, None
    if k == "bytes":
        return bytes(raw), None
    if k in ("timestamptz", "timestamp", "date"):
        parsed = parse_mysql_temporal(raw)
        if parsed is None:
            if col.nullable:
                return None, Coercion("zero_date_to_null", raw, None)
            epoch = {"timestamptz": EPOCH_UTC, "timestamp": EPOCH_NAIVE, "date": EPOCH_DATE}[k]
            return epoch, Coercion("zero_date_to_epoch", raw, epoch.isoformat())
        if k == "timestamptz":
            return parsed.replace(tzinfo=UTC), None
        return parsed, None
    raise ValueError(f"unknown kind {k}")
