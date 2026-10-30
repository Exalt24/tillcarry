import pytest

from tillcarry.ddl import pg_name
from tillcarry.introspect import ForeignKey, Index, SourceSchema, Table
from tillcarry.plan import build_plan, covers_unique, effective_fks, topo_order
from tillcarry.typemap import MyColumn


def c(name, data_type="int", column_type=None, nullable=False, **kw):
    return MyColumn(name, data_type, column_type or data_type, nullable, None, kw.pop("extra", ""), **kw)


def schema_two_tables(parent_unique=True):
    parent = Table(
        "ospos_parent",
        [c("id", extra="auto_increment"), c("code", "varchar", "varchar(10)", char_max_len=10), c("deleted", "tinyint", "tinyint(1)")],
        [Index("PRIMARY", True, ("id",), True), Index("code", parent_unique, ("code",))],
    )
    child = Table(
        "ospos_child",
        [c("child_id"), c("parent_code", "varchar", "varchar(10)", char_max_len=10)],
        [Index("PRIMARY", True, ("child_id",), True)],
        [ForeignKey("child_fk", "ospos_child", ("parent_code",), "ospos_parent", ("code",), "CASCADE")],
    )
    return SourceSchema("ospos", {"ospos_parent": parent, "ospos_child": child})


def test_topo_order_puts_parents_first_and_ignores_self_reference():
    fks = [
        ForeignKey("a", "c", ("x",), "b", ("x",)),
        ForeignKey("b", "b", ("x",), "a", ("x",)),
        ForeignKey("self", "a", ("p",), "a", ("x",)),
    ]
    assert topo_order(["c", "b", "a"], fks) == ["a", "b", "c"]


def test_topo_order_refuses_a_real_cycle():
    fks = [ForeignKey("a", "a", ("x",), "b", ("x",)), ForeignKey("b", "b", ("x",), "a", ("x",))]
    with pytest.raises(ValueError):
        topo_order(["a", "b"], fks)


def test_covers_unique_compares_column_sets():
    t = Table("t", indexes=[Index("PRIMARY", True, ("a", "b"), True), Index("k", False, ("c",))])
    assert covers_unique(t, ("b", "a"))
    assert not covers_unique(t, ("a",))
    assert not covers_unique(t, ("c",))


def test_a_foreign_key_to_a_non_unique_column_is_skipped_with_a_warning_when_there_is_no_documented_repair():
    s = schema_two_tables(parent_unique=False)
    warnings, decisions = [], []
    fks = effective_fks(s, warnings, decisions)
    assert fks["ospos_child"] == []
    assert warnings and "not unique" in warnings[0]


def test_documented_repair_replaces_the_broken_foreign_key():
    sales_items = Table("ospos_sales_items", [c("sale_id"), c("item_id"), c("line")], [Index("PRIMARY", True, ("sale_id", "item_id", "line"), True)])
    taxes = Table(
        "ospos_sales_items_taxes",
        [c("sale_id"), c("item_id"), c("line")],
        [],
        [ForeignKey("ospos_sales_items_taxes_ibfk_1", "ospos_sales_items_taxes", ("sale_id",), "ospos_sales_items", ("sale_id",))],
    )
    fks = effective_fks(SourceSchema("o", {"ospos_sales_items": sales_items, "ospos_sales_items_taxes": taxes}))
    assert [f.columns for f in fks["ospos_sales_items_taxes"]] == [("sale_id", "item_id", "line")]
    assert fks["ospos_sales_items_taxes"][0].origin == "replacement"


def test_text_columns_joined_by_a_foreign_key_share_a_type():
    plan = build_plan(schema_two_tables(), lambda t, col: 0)
    assert plan.tables["ospos_parent"].col("code").pg.sql == "citext"
    assert plan.tables["ospos_child"].col("parent_code").pg.sql == "citext"  # propagated through the FK


def test_boolean_needs_clean_data_else_the_plan_keeps_smallint_and_warns():
    clean = build_plan(schema_two_tables(), lambda t, col: 0)
    assert clean.tables["ospos_parent"].col("deleted").pg.sql == "boolean"
    dirty = build_plan(schema_two_tables(), lambda t, col: 3)
    assert dirty.tables["ospos_parent"].col("deleted").pg.sql == "smallint"
    assert any("3 rows hold other values" in w for w in dirty.warnings)


def test_plan_orders_parents_before_children_and_names_the_identity_column():
    plan = build_plan(schema_two_tables(), lambda t, col: 0)
    assert plan.order == ["ospos_parent", "ospos_child"]
    assert plan.tables["ospos_parent"].identity == "id"
    assert plan.tables["ospos_parent"].key_cols == ("id",)


def test_long_constraint_names_are_shortened_deterministically_under_63_bytes():
    name = pg_name("ospos_sales_items_taxes", "ospos_sales_items_taxes_ibfk_1_with_a_very_long_suffix_x")
    assert len(name) <= 63
    assert name == pg_name("ospos_sales_items_taxes", "ospos_sales_items_taxes_ibfk_1_with_a_very_long_suffix_x")
    assert pg_name("ospos_items", "ospos_items_ibfk_1") == "ospos_items_ibfk_1"
