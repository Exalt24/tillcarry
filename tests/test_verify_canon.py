"""The verifier's own arithmetic: its canonical forms must agree across the two databases for equal data, and
disagree for a one character, one cent or one row difference."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tillcarry.typemap import MyColumn
from tillcarry.verify import NULL, ColAcc, canon_source, canon_target, canon_target_col


def col(data_type, column_type=None, nullable=False, scale=None):
    return MyColumn("c", data_type, column_type or data_type, nullable, None, "", num_scale=scale)


def test_money_agrees_and_one_cent_differs():
    c = col("decimal", "decimal(15,2)", scale=2)
    assert canon_source(Decimal("12.5"), c) == canon_target(Decimal("12.50")) == "12.50"
    assert canon_source(Decimal("12.50"), c) != canon_target(Decimal("12.51"))


def test_three_and_four_decimal_places():
    assert canon_source(Decimal("1.5"), col("decimal", "decimal(15,3)", scale=3)) == "1.500"
    assert canon_source(Decimal("0.12"), col("decimal", "decimal(15,4)", scale=4)) == "0.1200"


def test_boolean_and_small_int_agree():
    assert canon_source(1, col("tinyint", "tinyint(1)")) == canon_target(True) == "1"
    assert canon_source(0, col("tinyint", "tinyint(1)")) == canon_target(False) == "0"
    assert canon_source(2, col("tinyint", "tinyint(1)")) == canon_target(2) == "2"


def test_float_goes_through_four_bytes_on_both_sides():
    c = col("float")
    assert canon_source(10.1, c) == canon_target_col(10.100000381469727, c)


def test_timestamp_agrees_across_a_zone_and_zero_dates_follow_the_documented_rule():
    ts = col("timestamp")
    pg_value = datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
    assert canon_source("2025-03-04 05:06:07", ts) == canon_target(pg_value)
    assert canon_source("0000-00-00 00:00:00", col("timestamp", nullable=True)) == NULL
    assert canon_source("0000-00-00 00:00:00", ts) == "1970-01-01 00:00:00"
    assert canon_source("2019-00-00 00:00:00", ts) == "1970-01-01 00:00:00"
    assert canon_source("0000-00-00", col("date")) == "1970-01-01" == canon_target(date(1970, 1, 1))


def test_blob_and_null_and_text():
    assert canon_source(b"\x00\xff", col("mediumblob")) == canon_target(b"\x00\xff") == "00ff"
    assert canon_source(None, col("varchar", "varchar(5)")) == canon_target(None) == NULL
    assert canon_source("Zoë 山田", col("varchar", "varchar(20)")) == canon_target("Zoë 山田")
    assert canon_source("NULL", col("varchar", "varchar(5)")) != NULL  # the word NULL is not a NULL


def test_one_character_changes_the_text():
    c = col("varchar", "varchar(20)")
    assert canon_source("Santos", c) != canon_target("Santas")


def test_fingerprint_ignores_order_but_not_content_or_count():
    def acc(values):
        a = ColAcc()
        for v in values:
            a.add(v)
        return a

    assert acc(["a", "b", "c"]) == acc(["c", "a", "b"])
    assert acc(["a", "b", "c"]) != acc(["a", "b", "d"])
    assert acc(["a", "b"]) != acc(["a", "b", "b"])
    assert acc(["a", "a", "b"]) != acc(["a", "b", "b"])  # same count, same set of distinct values
    assert acc([]) == acc([])


def test_unknown_type_is_refused():
    with pytest.raises(ValueError):
        canon_source("x", col("geometry"))
