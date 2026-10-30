# Type mapping, MySQL to PostgreSQL

What `src/tillcarry/typemap.py` does and why, one row per MySQL type family actually present in the
Open Source Point of Sale 3.3.9 schema. Every rule here is exercised by `tests/test_typemap.py`.

| MySQL | PostgreSQL | Why |
|---|---|---|
| `tinyint(1)`, column on the allowlist, data is only 0/1/NULL | `boolean` | A real flag (`deleted`, `is_serialized`, ...). The allowlist (`BOOLEAN_ALLOWLIST` in `typemap.py`) is table-specific or `("*", "deleted")` for the one column name that is a boolean everywhere it appears. |
| `tinyint(1)`, not on the allowlist, or the data holds something other than 0/1/NULL | `smallint` | A status or type code (`sale_status`, `item_type`, `stock_type`) or a bit-flag field (`definition_flags`) that only looks like a boolean because of its declared width. The plan checks the real data for every allowlisted column before committing to `boolean`; one planted row in the seed (`allow_alt_description = 2`) exists specifically to prove this check works, and does: that column stays `smallint`. |
| `tinyint`/`smallint`/`mediumint`, signed | matching signed integer | No precision lost. |
| `int`, `bigint`, unsigned | the next size up (`bigint`, `numeric(20,0)`) | PostgreSQL has no unsigned integers; the next size up guarantees the full unsigned range fits. |
| `decimal(p,s)` | `numeric(p,s)` | Exact, same precision and scale: money and quantities must not round. |
| `float`, `double` | `real`, `double precision` | Same bit width, same rounding behaviour. |
| `varchar(n)`/`char(n)`, NOT in a UNIQUE key | `varchar(n)`/`char(n)` | Straight copy. |
| `varchar`/`char` in a UNIQUE key (or joined by a foreign key to a column that is) | `citext` | MySQL's `utf8_general_ci` collation makes every such key case-insensitive; PostgreSQL's default `text` is case-sensitive. Keeping `varchar` here would silently let `"ADMIN"` and `"admin"` coexist as two different values where the source never could. `citext` is the extension PostgreSQL ships for exactly this. The case-insensitive set is computed once (`_case_insensitive_columns` in `plan.py`) and then propagated across every foreign key so a join partner always matches its parent's comparison behaviour. |
| `text` and the `*text` family | `text` | Straight copy. |
| `blob` and the `*blob`/`binary`/`varbinary` family | `bytea` | Straight copy, byte for byte. |
| `timestamp` | `timestamptz` | MySQL stores `TIMESTAMP` internally in UTC and converts for display; `timestamptz` is PostgreSQL's equivalent. |
| `datetime` | `timestamp` (no time zone) | MySQL's `DATETIME` carries no zone information at all; adding one on the way to PostgreSQL would be inventing data. |
| `date` | `date` | Straight copy. |
| anything else | the migration refuses to run | `map_type()` raises rather than guessing; a schema with a type not in this table needs a reviewed rule added here first. |

## Zero and impossible dates

MySQL, outside strict mode (the mode this schema's own `docker_mysql.cnf` uses, and the mode a decade of
real shop data was very likely written under), accepts `0000-00-00` and other calendar-impossible dates
like `2019-02-31`. PostgreSQL accepts neither. The rule (`parse_mysql_temporal`, `convert_value`):

- A nullable column: the impossible date becomes `NULL`.
- A `NOT NULL` column: the impossible date becomes the Unix epoch (`1970-01-01`, in whichever of `date`,
  naive `timestamp`, or UTC `timestamptz` the column's type calls for), chosen because it is an obviously
  fake date a report can filter on, rather than silently reusing today's date or some other value that
  could be mistaken for real data.

Every such conversion is written to `_tillcarry_coerced` with the rule name, the original source text,
and what it became, specifically so "the migration quietly changed a date" is never true: it is always a
visible, reviewable row.

## Defaults

`map_default()` carries a column's `DEFAULT` across using the mapped type: `CURRENT_TIMESTAMP` becomes
`now()`, a `0`/`1` default on a boolean-mapped column becomes `false`/`true`, a decimal default is
re-quantized to the mapped scale, and a text default is quoted with its own quotes doubled. A `bytea`
column never gets a text default carried over (there is nothing meaningful to carry).
