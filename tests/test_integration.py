"""End to end against the two docker databases: seed, dry run, migrate, verify, run again, roll back, and the
deliberate-breakage controls. Skipped when the databases are not up, unless TILLCARRY_REQUIRE_DB=1 (CI sets it)."""

import json
import os

import pytest

from tillcarry import migrate as mig
from tillcarry.config import MysqlConfig, PgConfig
from tillcarry.db import mysql_connect, pg_connect
from tillcarry.seed import seed
from tillcarry.verify import verify

pytestmark = pytest.mark.integration

MY, PG = MysqlConfig.from_env(), PgConfig.from_env()
quiet = lambda *_: None  # noqa: E731


def _reachable() -> str | None:
    try:
        mysql_connect(MY).close()
        pg_connect(PG).close()
    except Exception as e:  # noqa: BLE001
        return f"databases not reachable ({type(e).__name__}); run `docker compose up -d --wait`"
    return None


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    why = _reachable()
    if why:
        if os.environ.get("TILLCARRY_REQUIRE_DB") == "1":
            pytest.fail(why)
        pytest.skip(why)
    manifest = tmp_path_factory.mktemp("seed") / "manifest.json"
    info = seed(MY, manifest=manifest)
    assert json.loads(manifest.read_text(encoding="utf8"))["total_rows"] == info["total_rows"]
    first = mig.run(MY, PG, log=quiet)
    return info, first


def pg_exec(sql, params=None, fetch=False):
    conn = pg_connect(PG, autocommit=True)
    try:
        cur = conn.execute(sql, params)
        return cur.fetchall() if fetch else None
    finally:
        conn.close()


def failed_names(rep):
    return {c.name for c in rep.failures}


def remigrate():
    mig.run(MY, PG, log=quiet)


def test_seed_is_a_few_thousand_rows_and_every_awkward_case_is_planted(world):
    info, _ = world
    assert 5_000 < info["total_rows"] < 30_000
    p = info["planted"]
    assert len(p["sales_with_missing_customer"]) == 3
    assert p["zero_dates_in_nullable_columns"]
    assert info["emoji_probe"]["result"] == "rejected"  # the utf8mb3 legacy schema cannot hold an emoji


def test_first_migration_balances_row_for_row(world):
    _, rep = world
    assert rep.swapped
    assert rep.total_source == rep.total_loaded + rep.total_rejected
    assert rep.total_rejected > 0 and rep.total_coerced > 0
    assert all(s.source_rows == s.loaded + s.rejected for s in rep.stats.values())


def test_verifier_passes_on_a_clean_migration(world):
    rep = verify(MY, PG)
    assert rep.ok, [f"{c.table}: {c.name}: {c.detail}" for c in rep.failures]
    assert len(rep.checks) > 200


def test_every_planted_orphan_is_in_quarantine_with_a_reason_and_none_is_dropped(world):
    info, _ = world
    p = info["planted"]
    rows = pg_exec("SELECT table_name, count(*), bool_and(reason <> '') FROM ospos._tillcarry_rejects GROUP BY 1", fetch=True)
    got = {t: n for t, n, _ in rows}
    assert all(ok for *_, ok in rows)
    assert got["ospos_sales"] == len(p["sales_with_missing_customer"])
    assert got["ospos_sales_payments"] >= p["payments_for_missing_sales"]
    assert got["ospos_sales_taxes"] >= p["sales_taxes_for_missing_sales"]
    assert got["ospos_inventory"] == p["inventory_rows_for_missing_items"]
    assert got["ospos_customers_points"] == p["customer_points_for_missing_sales"]
    assert got["ospos_attribute_links"] == p["attribute_links_for_missing_items"]
    assert got["ospos_attribute_definitions"] == len(p["attribute_definitions_chain_with_missing_root"])
    assert got["ospos_sales_items_taxes"] >= p["sale_item_taxes_without_a_sale_line"]
    assert got["ospos_items"] == len(p["items_with_missing_supplier"])


def test_zero_dates_are_logged_and_replaced_not_hidden(world):
    rows = dict(pg_exec("SELECT rule, count(*) FROM ospos._tillcarry_coerced GROUP BY 1", fetch=True))
    assert rows["zero_date_to_null"] == 3  # two expenses, one cash up
    assert rows["zero_date_to_epoch"] >= 8
    (n,) = pg_exec("SELECT count(*) FROM ospos.ospos_expenses WHERE date IS NULL", fetch=True)[0]
    assert n >= 3


def test_a_non_boolean_in_a_boolean_looking_column_keeps_the_column_a_smallint(world):
    (t,) = pg_exec(
        "SELECT data_type FROM information_schema.columns WHERE table_schema='ospos' AND table_name='ospos_items' AND column_name='allow_alt_description'",
        fetch=True,
    )[0]
    assert t == "smallint"
    (t,) = pg_exec(
        "SELECT data_type FROM information_schema.columns WHERE table_schema='ospos' AND table_name='ospos_items' AND column_name='deleted'",
        fetch=True,
    )[0]
    assert t == "boolean"


def test_emoji_that_the_legacy_database_refused_works_after_the_move(world):
    pg_exec("UPDATE ospos.ospos_stock_locations SET location_name = 'depot \U0001F600' WHERE location_id = 1")
    (v,) = pg_exec("SELECT location_name FROM ospos.ospos_stock_locations WHERE location_id = 1", fetch=True)[0]
    assert v == "depot \U0001F600"
    remigrate()


def test_dry_run_changes_nothing(world):
    before = pg_exec("SELECT count(*) FROM information_schema.tables WHERE table_schema LIKE 'ospos%'", fetch=True)
    schemas = pg_exec("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'ospos%' ORDER BY 1", fetch=True)
    rep = mig.run(MY, PG, dry_run=True, log=quiet)
    assert not rep.swapped and rep.total_rejected > 0
    assert before == pg_exec("SELECT count(*) FROM information_schema.tables WHERE table_schema LIKE 'ospos%'", fetch=True)
    assert schemas == pg_exec("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'ospos%' ORDER BY 1", fetch=True)
    assert verify(MY, PG).ok


def test_running_twice_gives_the_same_result_and_keeps_the_previous_schema(world):
    a = verify(MY, PG)
    second = mig.run(MY, PG, log=quiet)
    b = verify(MY, PG)
    assert a.ok and b.ok and second.previous_schema_kept
    assert {k: (f.source, f.target, f.rejected) for k, f in a.tables.items()} == {k: (f.source, f.target, f.rejected) for k, f in b.tables.items()}
    assert a.money == b.money
    assert pg_exec("SELECT count(*) FROM information_schema.schemata WHERE schema_name='ospos_prev'", fetch=True)[0][0] == 1


def test_rollback_restores_the_previous_schema(world):
    pg_exec("UPDATE ospos.ospos_people SET last_name = 'Marker' WHERE person_id = 1")
    remigrate()  # ospos_prev now holds the Marker edit
    assert pg_exec("SELECT last_name FROM ospos.ospos_people WHERE person_id = 1", fetch=True)[0][0] != "Marker"
    assert mig.rollback(PG, log=quiet)
    assert pg_exec("SELECT last_name FROM ospos.ospos_people WHERE person_id = 1", fetch=True)[0][0] == "Marker"
    remigrate()


def test_a_failing_run_leaves_the_target_untouched(world, monkeypatch):
    before = pg_exec("SELECT count(*) FROM ospos.ospos_sales", fetch=True)
    monkeypatch.setattr(mig, "_sweep_orphans", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        mig.run(MY, PG, log=quiet)
    assert before == pg_exec("SELECT count(*) FROM ospos.ospos_sales", fetch=True)
    monkeypatch.undo()
    assert verify(MY, PG).ok


# --- deliberate breakage: the verifier must fail, every time ---------------------------------------------------


def broken(world, sql, expect):
    """Damage PostgreSQL after a good migration, confirm the verifier notices, then migrate again to heal."""
    remigrate()
    assert verify(MY, PG).ok
    pg_exec(sql)
    rep = verify(MY, PG)
    names = failed_names(rep)
    remigrate()
    assert not rep.ok, f"verifier did not notice: {sql}"
    assert any(expect in n for n in names), (expect, names)
    assert verify(MY, PG).ok


def test_control_one_row_deleted(world):
    broken(world, "DELETE FROM ospos.ospos_items_taxes WHERE ctid = (SELECT min(ctid) FROM ospos.ospos_items_taxes)", "row count")


def test_control_one_cent_changed(world):
    broken(world, "UPDATE ospos.ospos_sales_payments SET payment_amount = payment_amount + 0.01 WHERE payment_id = (SELECT min(payment_id) FROM ospos.ospos_sales_payments)", "to the cent")


def test_control_one_character_changed(world):
    broken(world, "UPDATE ospos.ospos_people SET last_name = overlay(last_name placing 'x' from 1 for 1) WHERE person_id = 2", "checksum of all")


def test_control_two_values_swapped_between_rows(world):
    """Per column checksums cannot see this (the same values are still in the column); the whole row checksum can."""
    rows = pg_exec("SELECT person_id, last_name FROM ospos.ospos_people ORDER BY person_id LIMIT 60", fetch=True)
    (a, an), (b, bn) = next((x, y) for x in rows for y in rows if x[1] != y[1])
    sql = (
        "UPDATE ospos.ospos_people SET last_name = CASE person_id "
        f"WHEN {a} THEN (SELECT last_name FROM ospos.ospos_people WHERE person_id = {b}) "
        f"WHEN {b} THEN (SELECT last_name FROM ospos.ospos_people WHERE person_id = {a}) END "
        f"WHERE person_id IN ({a}, {b})"
    )
    broken(world, sql, "checksum of whole rows")


def test_control_a_row_added_that_was_never_in_the_source(world):
    broken(world, "INSERT INTO ospos.ospos_stock_locations (location_name, deleted) VALUES ('ghost', false)", "row count")


def test_control_a_quarantined_row_silently_forgotten(world):
    broken(world, "DELETE FROM ospos._tillcarry_rejects WHERE id = (SELECT min(id) FROM ospos._tillcarry_rejects)", "quarantine")


def test_control_a_foreign_key_dropped(world):
    broken(world, "ALTER TABLE ospos.ospos_sales DROP CONSTRAINT ospos_sales_ibfk_2", "foreign keys exist")


def test_control_a_sequence_left_behind(world):
    broken(world, "SELECT setval(pg_get_serial_sequence('ospos.ospos_sales', 'sale_id'), 1, false)", "identity sequences")


def test_control_the_source_changes_after_the_move(world):
    remigrate()
    conn = mysql_connect(MY)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE ospos_sales_payments SET payment_amount = payment_amount + 0.01 WHERE payment_id = 1")
        rep = verify(MY, PG)
        assert not rep.ok and any("to the cent" in n for n in failed_names(rep))
    finally:
        with conn.cursor() as cur:
            cur.execute("UPDATE ospos_sales_payments SET payment_amount = payment_amount - 0.01 WHERE payment_id = 1")
        conn.close()
    assert verify(MY, PG).ok
