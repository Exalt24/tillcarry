from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tillcarry.typemap import (
    EPOCH_DATE,
    EPOCH_NAIVE,
    EPOCH_UTC,
    MyColumn,
    convert_value,
    is_boolean_candidate,
    map_default,
    map_type,
    parse_mysql_temporal,
)


def col(name="c", data_type="int", column_type=None, nullable=False, default=None, extra="", **kw):
    return MyColumn(name, data_type, column_type or data_type, nullable, default, extra, **kw)


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        (col(data_type="int", column_type="int"), "integer"),
        (col(data_type="int", column_type="int unsigned"), "bigint"),
        (col(data_type="bigint", column_type="bigint"), "bigint"),
        (col(data_type="bigint", column_type="bigint unsigned"), "numeric(20,0)"),
        (col(data_type="smallint", column_type="smallint"), "smallint"),
        (col(data_type="decimal", column_type="decimal(15,2)", num_precision=15, num_scale=2), "numeric(15,2)"),
        (col(data_type="decimal", column_type="decimal(15,3)", num_precision=15, num_scale=3), "numeric(15,3)"),
        (col(data_type="float", column_type="float"), "real"),
        (col(data_type="varchar", column_type="varchar(40)", char_max_len=40), "varchar(40)"),
        (col(data_type="text", column_type="text"), "text"),
        (col(data_type="mediumblob", column_type="mediumblob"), "bytea"),
        (col(data_type="timestamp", column_type="timestamp"), "timestamptz"),
        (col(data_type="datetime", column_type="datetime"), "timestamp"),
        (col(data_type="date", column_type="date"), "date"),
    ],
)
def test_straight_mappings(column, expected):
    assert map_type("ospos_x", column).sql == expected


def test_tinyint_is_a_small_number_not_a_boolean_by_default():
    c = col("sale_status", "tinyint", "tinyint(1)")
    assert map_type("ospos_sales", c).sql == "smallint"
    assert not is_boolean_candidate("ospos_sales", c)


def test_allowlisted_tinyint_becomes_boolean_only_when_the_plan_says_the_data_is_clean():
    c = col("deleted", "tinyint", "tinyint(1)")
    assert is_boolean_candidate("ospos_items", c)
    assert map_type("ospos_items", c, boolean=True).sql == "boolean"
    assert map_type("ospos_items", c, boolean=False).sql == "smallint"


def test_table_specific_allowlist_entry_does_not_leak_to_other_tables():
    c = col("status", "tinyint", "tinyint(1)")
    assert is_boolean_candidate("ospos_dinner_tables", c)
    assert not is_boolean_candidate("ospos_sales", c)


def test_bit_flag_column_is_never_a_boolean_candidate():
    assert not is_boolean_candidate("ospos_attribute_definitions", col("definition_flags", "tinyint", "tinyint(1)"))


def test_tinyint_wider_than_one_is_not_a_candidate():
    assert not is_boolean_candidate("ospos_x", col("deleted", "tinyint", "tinyint(4)"))


def test_text_in_a_unique_key_becomes_citext():
    c = col("username", "varchar", "varchar(255)", char_max_len=255)
    assert map_type("ospos_employees", c, case_insensitive=True).sql == "citext"
    assert map_type("ospos_employees", c).sql == "varchar(255)"


def test_unknown_type_is_refused_not_guessed():
    with pytest.raises(ValueError):
        map_type("ospos_x", col("g", "geometry", "geometry"))


def test_defaults():
    ts = col("t", "timestamp", "timestamp", default="CURRENT_TIMESTAMP", extra="DEFAULT_GENERATED")
    assert map_default(ts, map_type("t", ts)) == "now()"
    b = col("deleted", "tinyint", "tinyint(1)", default="0")
    assert map_default(b, map_type("t", b, boolean=True)) == "false"
    assert map_default(b, map_type("t", b)) == "0"
    d = col("d", "decimal", "decimal(15,2)", default="0.00", num_precision=15, num_scale=2)
    assert map_default(d, map_type("t", d)) == "0.00"
    s = col("s", "varchar", "varchar(8)", default="it's", char_max_len=8)
    assert map_default(s, map_type("t", s)) == "'it''s'"
    e = col("e", "varchar", "varchar(8)", default="", char_max_len=8)
    assert map_default(e, map_type("t", e)) == "''"
    assert map_default(col("n", "int", nullable=True, default=None), map_type("t", col("n"))) is None


# --- values -------------------------------------------------------------------------------------------------


def test_zero_date_in_a_nullable_column_becomes_null_and_is_reported():
    c = col("close_date", "timestamp", nullable=True)
    value, co = convert_value("0000-00-00 00:00:00", c, map_type("t", c))
    assert value is None
    assert co.rule == "zero_date_to_null"
    assert co.source_value == "0000-00-00 00:00:00"


@pytest.mark.parametrize(
    ("dtype", "epoch"), [("timestamp", EPOCH_UTC), ("datetime", EPOCH_NAIVE), ("date", EPOCH_DATE)]
)
def test_zero_date_in_a_not_null_column_becomes_the_epoch_and_is_reported(dtype, epoch):
    c = col("d", dtype, nullable=False)
    raw = "0000-00-00" if dtype == "date" else "0000-00-00 00:00:00"
    value, co = convert_value(raw, c, map_type("t", c))
    assert value == epoch
    assert co.rule == "zero_date_to_epoch"


@pytest.mark.parametrize("raw", ["2019-00-00 00:00:00", "2019-02-31 10:00:00", "0000-01-01 00:00:00"])
def test_impossible_dates_are_treated_like_zero_dates(raw):
    assert parse_mysql_temporal(raw) is None


def test_real_timestamp_is_utc_aware_and_datetime_is_naive():
    ts = col("t", "timestamp")
    v, co = convert_value("2025-03-04 05:06:07", ts, map_type("t", ts))
    assert co is None and v == datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
    dt = col("t", "datetime")
    v, _ = convert_value("2025-03-04 05:06:07", dt, map_type("t", dt))
    assert v == datetime(2025, 3, 4, 5, 6, 7) and v.tzinfo is None
    d = col("t", "date")
    v, _ = convert_value("2025-03-04", d, map_type("t", d))
    assert v == date(2025, 3, 4)


def test_text_that_is_not_a_date_is_an_error_not_a_zero_date():
    c = col("t", "timestamp")
    with pytest.raises(ValueError):
        convert_value("garbage", c, map_type("t", c))


def test_decimal_keeps_every_digit():
    c = col("amount", "decimal", "decimal(15,2)", num_precision=15, num_scale=2)
    v, _ = convert_value(Decimal("9999999999999.99"), c, map_type("t", c))
    assert v == Decimal("9999999999999.99")


def test_null_is_null_for_every_kind():
    for c in (col("a", "int"), col("b", "varchar", "varchar(5)", char_max_len=5), col("c", "timestamp"), col("d", "mediumblob")):
        assert convert_value(None, c, map_type("t", c)) == (None, None)


def test_boolean_conversion():
    c = col("deleted", "tinyint", "tinyint(1)")
    pg = map_type("ospos_x", c, boolean=True)
    assert convert_value(1, c, pg)[0] is True
    assert convert_value(0, c, pg)[0] is False


def test_text_with_a_nul_byte_is_refused_loudly():
    c = col("s", "varchar", "varchar(9)", char_max_len=9)
    with pytest.raises(ValueError):
        convert_value("a\x00b", c, map_type("t", c))


def test_binary_survives_as_bytes():
    c = col("data", "mediumblob")
    v, _ = convert_value(b"\x00\xff\x00", c, map_type("t", c))
    assert v == b"\x00\xff\x00"
