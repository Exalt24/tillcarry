"""Command line: seed, migrate, verify, rollback."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import migrate as mig
from .config import PG_SCHEMA, MysqlConfig, PgConfig
from .seed import DEFAULT_SEED, seed
from .verify import verify


def _print_migration(rep: mig.RunReport) -> None:
    width = max(len(n) for n in rep.stats)
    print(f"\n{'table'.ljust(width)}  {'source':>7} {'loaded':>7} {'quarantined':>12} {'zero dates fixed':>17}")
    for name in rep.plan.order:
        s = rep.stats[name]
        print(f"{name.ljust(width)}  {s.source_rows:>7} {s.loaded:>7} {s.rejected:>12} {s.coerced:>17}")
    print(f"{'TOTAL'.ljust(width)}  {rep.total_source:>7} {rep.total_loaded:>7} {rep.total_rejected:>12} {rep.total_coerced:>17}")
    print("\ndecisions that were not a straight copy:")
    kinds = {"-> boolean": 0, "-> smallint": 0, "-> citext": 0}
    for d in rep.plan.decisions:
        for k in kinds:
            if k in d:
                kinds[k] += 1
                break
        else:
            print(f"  - {d}")
    print(f"  - {kinds['-> boolean']} columns tinyint(1) -> boolean (allowlisted, data is only 0/1/NULL)")
    print(f"  - {kinds['-> smallint']} columns tinyint(1) -> smallint (a status or flag, not a proven boolean)")
    print(f"  - {kinds['-> citext']} text columns in a UNIQUE key -> citext (utf8_general_ci was case-insensitive)")
    for w in rep.plan.warnings:
        print(f"  ! {w}")
    print(("\nDRY RUN: nothing was written to PostgreSQL." if rep.dry_run else
           f"\nSwapped in as schema '{PG_SCHEMA}'." + (f" Previous schema kept as '{PG_SCHEMA}_prev'." if rep.previous_schema_kept else "")))


def _print_verify(rep) -> None:
    by_table: dict[str, list] = {}
    for c in rep.checks:
        by_table.setdefault(c.table or "(database)", []).append(c)
    for table, checks in by_table.items():
        bad = [c for c in checks if not c.ok]
        print(f"{'FAIL' if bad else 'ok  '}  {table}: {len(checks) - len(bad)}/{len(checks)} checks")
        for c in bad:
            print(f"        FAILED {c.name}: {c.detail}")
    print()
    total = len(rep.checks)
    fails = len(rep.failures)
    cols = sum(f.columns_hashed for f in rep.tables.values())
    rows_src = sum(f.source for f in rep.tables.values())
    rows_dst = sum(f.target for f in rep.tables.values())
    rows_rej = sum(f.rejected for f in rep.tables.values())
    print(f"rows: source {rows_src} = loaded {rows_dst} + quarantined {rows_rej}")
    print(f"columns checksummed: {cols}   rows sampled field by field: {sum(f.sampled for f in rep.tables.values())}")
    pay = rep.money.get("ospos_sales_payments.payment_amount")
    if pay is not None:
        print(f"payments total in PostgreSQL: {pay}  (quarantined payments: {rep.quarantined_money.get('ospos_sales_payments.payment_amount')})")
    print(f"{total - fails}/{total} checks passed" + ("" if not fails else f", {fails} FAILED"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tillcarry", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("seed", help="load the OSPOS schema into MySQL and fill it with invented data")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--manifest", type=Path, default=Path("out/seed-manifest.json"))
    p = sub.add_parser("migrate", help="copy MySQL to PostgreSQL")
    p.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    sub.add_parser("verify", help="prove nothing was lost")
    sub.add_parser("rollback", help="swap the previous PostgreSQL schema back in")
    a = ap.parse_args(argv)

    if a.cmd == "seed":
        info = seed(MysqlConfig.from_env(), seed_value=a.seed, scale=a.scale, manifest=a.manifest)
        print(f"seeded {info['total_rows']} rows in {len(info['rows'])} tables (seed {a.seed}); manifest: {a.manifest}")
        print(f"emoji into the utf8mb3 schema: {info['emoji_probe']}")
        return 0
    if a.cmd == "migrate":
        rep = mig.run(MysqlConfig.from_env(), PgConfig.from_env(), dry_run=a.dry_run)
        _print_migration(rep)
        return 0
    if a.cmd == "verify":
        rep = verify(MysqlConfig.from_env(), PgConfig.from_env())
        _print_verify(rep)
        return 0 if rep.ok else 1
    if a.cmd == "rollback":
        return 0 if mig.rollback(PgConfig.from_env()) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
