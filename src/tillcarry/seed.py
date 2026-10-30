"""Build the MySQL source: load the OSPOS 3.3.9 schema, then fill it with invented data and plant the awkward
cases a ten year old shop database really holds. Every value comes from a seeded random generator, so two runs
give byte for byte the same database and the checksums in the README can be reproduced.

Nothing here is real: names, shops, products, phone numbers and the password hashes are made up. Phone numbers
use the 555-01xx range and addresses are invented streets.
"""

from __future__ import annotations

import json
import random
import unicodedata
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymysql

from .config import MysqlConfig
from .db import mysql_connect

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = ROOT / "schema" / "ospos-3.3.9.mysql.sql"
REFDATA_FILE = ROOT / "schema" / "ospos-3.3.9.reference-data.sql"
DEFAULT_SEED = 20261030

FIRST = ["Maria", "Jose", "Juan", "Ana", "Luz", "Carlo", "Bea", "Miguel", "Zoë", "Renée", "Sofía", "Andrés", "Noël",
         "Joaquín", "Dalisay", "Hiroshi", "Yuki", "Mei", "Wei", "Priya", "Arjun", "Fatima", "Omar", "Liam", "Emma",
         "Grace", "Paolo", "Kristine", "Ramon", "Teresita", "Lourdes", "Ignacio", "Amihan", "Tomas", "Elena"]
LAST = ["Santos", "Reyes", "Cruz", "Bautista", "Garcia", "Mendoza", "Peña", "Muñoz", "Dela Cruz", "Villanueva",
        "Ramos", "Aquino", "Castillo", "O'Brien", "Nguyen", "Tanaka", "Suzuki", "Lim", "Tan", "Patel", "Haddad",
        "Müller", "Åberg", "Lindqvist", "Fernández", "Domínguez", "Soriano", "Navarro", "Lopez", "Abad", "Salazar"]
CJK = [("山田", "花子"), ("王", "小明"), ("김", "민준"), ("佐藤", "健")]
STREETS = ["Sampaguita St", "Rizal Ave", "Mabini St", "Acacia Lane", "Bonifacio Drive", "Orchid Road", "Luna St"]
CITIES = [("Cebu City", "Cebu", "6000"), ("Davao City", "Davao del Sur", "8000"), ("Quezon City", "Metro Manila", "1100"),
          ("Iloilo City", "Iloilo", "5000"), ("Baguio", "Benguet", "2600")]
ADJ = ["Mountain", "Golden", "Fresh", "Classic", "Crispy", "Sweet", "Spicy", "Premium", "Family", "Island"]
NOUN = {
    "Beverages": ["Spring Water", "Iced Tea", "Calamansi Juice", "Café Latte", "Cola", "Soy Milk"],
    "Snacks": ["Banana Chips", "Rice Crackers", "Peanuts", "Dried Mango", "Cheese Puffs", "Pork Rinds"],
    "Hardware": ["Hammer", "Screwdriver Set", "Duct Tape", "Padlock", "Paint Brush", "Wire Cutter"],
    "Stationery": ["Notebook", "Ballpen Pack", "Stapler", "Highlighter", "Sticky Notes", "Folder"],
    "Personal Care": ["Shampoo", "Soap Bar", "Toothpaste", "Lotion", "Face Towel", "Deodorant"],
}
SIZE = ["", " 250ml", " 500ml", " 1L", " 12pk", " 100g", " 250g", " Large"]
PERMISSION_SKIP = {"items_stock", "sales_stock", "receivings_stock"}

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")


def ascii_slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum()) or "x"


def split_statements(sql: str) -> list[str]:
    out, buf = [], []
    for line in sql.splitlines():
        if line.startswith("--") or not line.strip():
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            out.append("\n".join(buf).rstrip().rstrip(";"))
            buf = []
    return out


class Seeder:
    def __init__(self, conn, seed: int, scale: float) -> None:
        self.c = conn
        self.rng = random.Random(seed)
        self.scale = scale
        self.planted: dict[str, object] = {}
        self.base = datetime(2024, 1, 1)

    # ----- helpers ---------------------------------------------------------------------------------------
    def n(self, base: int) -> int:
        return max(3, int(base * self.scale))

    def ins(self, table: str, cols: list[str], rows: list[tuple]) -> None:
        if not rows:
            return
        col_sql = ", ".join(f"`{c}`" for c in cols)
        ph = ", ".join(["%s"] * len(cols))
        with self.c.cursor() as cur:
            cur.executemany(f"INSERT INTO `{table}` ({col_sql}) VALUES ({ph})", rows)

    def ts(self, days_from: int = 0, days_to: int = 700) -> str:
        d = self.base + timedelta(days=self.rng.randint(days_from, days_to), seconds=self.rng.randint(8 * 3600, 20 * 3600))
        return d.strftime("%Y-%m-%d %H:%M:%S")

    def money(self, lo: float, hi: float) -> Decimal:
        return Decimal(str(round(self.rng.uniform(lo, hi), 2))).quantize(Q2)

    def person_row(self, pid: int, first: str, last: str) -> tuple:
        city, state, zip_ = self.rng.choice(CITIES)
        comments = self.rng.choice(["", "", "", "Prefers morning pickup", "Wholesale buyer", "Asked for a receipt copy"])
        email = f"{ascii_slug(first)}.{ascii_slug(last)}{pid}@example.test"
        return (first, last, self.rng.choice([0, 1, None]), f"555-01{pid % 100:02d}", email,
                f"{self.rng.randint(1, 999)} {self.rng.choice(STREETS)}", "", city, state, zip_, "PH", comments, pid)

    # ----- the build -------------------------------------------------------------------------------------
    def build(self) -> None:
        r = self.rng
        with self.c.cursor() as cur:
            cur.execute("SET SESSION sql_mode = ''")  # a decade-old database was not strict; this lets zero dates in
            cur.execute("SET SESSION foreign_key_checks = 0")

        n_emp, n_sup, n_cust = 8, self.n(20), self.n(320)
        emp_ids = list(range(1, 1 + n_emp))
        sup_ids = list(range(n_emp + 1, n_emp + 1 + n_sup))
        cust_ids = list(range(n_emp + n_sup + 2, n_emp + n_sup + 2 + n_cust))  # one id skipped: a gap
        spare_ids = [cust_ids[-1] + 1 + k for k in range(5)]  # people nobody references

        people = []
        for pid in emp_ids + sup_ids + cust_ids + spare_ids:
            if pid in cust_ids and r.random() < 0.04:
                first, last = r.choice(CJK)
            else:
                first, last = r.choice(FIRST), r.choice(LAST)
            people.append(self.person_row(pid, first, last))
        people[0] = people[0][:11] + ("Owner, invented", emp_ids[0])
        self.ins("ospos_people", ["first_name", "last_name", "gender", "phone_number", "email", "address_1", "address_2",
                                  "city", "state", "zip", "country", "comments", "person_id"], people)
        with self.c.cursor() as cur:  # the spare people were hired and left again; the id counter stays above them
            cur.execute("DELETE FROM ospos_people WHERE person_id >= %s", (spare_ids[0],))

        users = ["owner.reyes", "mgr.santos", "cashier.lim", "cashier.garcia", "stock.abad", "cashier.nguyen", "night.tan", "temp.aquino"]
        alphabet = "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        self.ins("ospos_employees", ["username", "password", "person_id", "deleted", "hash_version", "language", "language_code"],
                 [(u, "$2y$10$" + "".join(r.choice(alphabet) for _ in range(53)), pid, 1 if u.startswith("temp") else 0, 2,
                   "english" if i % 2 else None, "en-US" if i % 2 else None) for i, (u, pid) in enumerate(zip(users, emp_ids, strict=True))])
        with self.c.cursor() as cur:
            cur.execute("SELECT permission_id FROM ospos_permissions ORDER BY 1")
            perms = [p for (p,) in cur.fetchall() if p not in PERMISSION_SKIP]
        grants = []
        for i, pid in enumerate(emp_ids):
            for p in perms:
                if i == 0 or r.random() < 0.45 or p in ("sales", "home"):
                    grants.append((p, pid, "home"))
        self.ins("ospos_grants", ["permission_id", "person_id", "menu_group"], grants)

        self.ins("ospos_suppliers", ["person_id", "company_name", "agency_name", "account_number", "tax_id", "deleted", "category"],
                 [(pid, f"{r.choice(LAST)} {r.choice(['Trading', 'Wholesale', 'Imports', 'Distribution'])}", r.choice(["", "Visayas desk", "Metro desk"]),
                   f"SUP-{pid:04d}" if r.random() < 0.8 else None, f"TIN-{r.randint(100, 999)}-{r.randint(100, 999)}", 0, r.choice([0, 1]))
                  for pid in sup_ids])

        self.ins("ospos_stock_locations", ["location_id", "location_name", "deleted"], [(2, "backroom", 0)])
        cats = [(1, "Standard", 1, 0), (2, "Reduced", 2, 0), (3, "Zero rated", 3, 0)]
        self.ins("ospos_tax_categories", ["tax_category_id", "tax_category", "tax_group_sequence", "deleted"], cats)
        self.ins("ospos_tax_codes", ["tax_code_id", "tax_code", "tax_code_name", "city", "state", "deleted"],
                 [(1, "PH-VAT", "Value added tax", "", "", 0), (2, "PH-EXEMPT", "Exempt", "", "", 0)])
        self.ins("ospos_tax_jurisdictions", ["jurisdiction_id", "jurisdiction_name", "tax_group", "tax_type", "reporting_authority",
                                              "tax_group_sequence", "cascade_sequence", "deleted"],
                 [(1, "National", "VAT", 1, "Invented revenue office", 1, 0, 0)])
        self.ins("ospos_tax_rates", ["tax_rate_id", "rate_tax_code_id", "rate_tax_category_id", "rate_jurisdiction_id", "tax_rate", "tax_rounding_code"],
                 [(1, 1, 1, 1, Decimal("12.0000"), 0), (2, 1, 2, 1, Decimal("5.0000"), 0), (3, 2, 3, 1, Decimal("0.0000"), 0)])

        # customers: some zero dates in the NOT NULL signup date
        cust_rows = []
        zero_cust = set(r.sample(cust_ids, 3))
        for k, pid in enumerate(cust_ids):
            date = self.ts(0, 600)
            if pid in zero_cust:
                date = "0000-00-00 00:00:00" if k % 2 == 0 else "2019-00-00 00:00:00"
            company = r.choice([None, None, None, f"{r.choice(LAST)} Store", "Café Lourdes Ltd™", "Ñandú Provisions"])
            cust_rows.append((pid, company, f"C-{pid:05d}" if r.random() < 0.7 else None, r.choice([0, 1, 1, 1]), "", None,
                              r.choice([Decimal("0.00"), Decimal("0.00"), Decimal("5.00"), Decimal("10.00")]), 0,
                              r.choice([None, 1, 2, 3, 4, 5]), r.choice([None, 0, 10, 250]), 1 if r.random() < 0.03 else 0,
                              date, r.choice(emp_ids), r.choice([0, 1])))
        self.ins("ospos_customers", ["person_id", "company_name", "account_number", "taxable", "tax_id", "sales_tax_code_id", "discount",
                                     "discount_type", "package_id", "points", "deleted", "date", "employee_id", "consent"], cust_rows)
        self.planted["zero_date_customers"] = sorted(zero_cust)

        # items
        n_items = self.n(250)
        item_rows, item_prices = [], {}
        for iid in range(1, n_items + 1):
            cat = r.choice(list(NOUN))
            name = f"{r.choice(ADJ)} {r.choice(NOUN[cat])}{r.choice(SIZE)}"
            cost = self.money(0.5, 80)
            unit = (cost * Decimal(str(round(r.uniform(1.15, 1.8), 2)))).quantize(Q2)
            if iid == 7:
                cost, unit = Decimal("0.01"), Decimal("0.01")
            item_prices[iid] = unit
            supplier = r.choice(sup_ids + [None, None])
            item_rows.append((name, cat, supplier, f"49{iid:010d}", r.choice(["", "Imported", "Local brand", "Seasonal"]), cost, unit,
                              Decimal("5.000"), Decimal("1.000"), iid, None, 0, 0, 0, 0, 1 if r.random() < 0.04 else 0,
                              r.choice([1, 1, 2, 3]), Decimal("1.000"), "Each", 0, ""))
        item_rows[0] = item_rows[0][:4] + ("Plain, with ' quote and \\ backslash\nand a newline\tand a tab",) + item_rows[0][5:]
        item_rows[1] = item_rows[1][:4] + ("é" * 255,) + item_rows[1][5:]  # fills the varchar(255)
        item_rows[2] = item_rows[2][:4] + ("NULL",) + item_rows[2][5:]
        item_rows[3] = item_rows[3][:4] + ("\\N",) + item_rows[3][5:]
        item_rows[4] = ("無糖 Green Tea 500ml ™ €2", "Beverages", item_rows[4][2]) + item_rows[4][3:]
        item_rows[5] = item_rows[5][:11] + (2,) + item_rows[5][12:]  # allow_alt_description = 2, a "boolean" that is not
        orphan_item = n_items  # supplier 9999 does not exist
        item_rows[orphan_item - 1] = item_rows[orphan_item - 1][:2] + (9999,) + item_rows[orphan_item - 1][3:]
        item_rows[8] = item_rows[8][:12] + (1,) + item_rows[8][13:]  # one serialized item
        self.ins("ospos_items", ["name", "category", "supplier_id", "item_number", "description", "cost_price", "unit_price", "reorder_level",
                                 "receiving_quantity", "item_id", "pic_filename", "allow_alt_description", "is_serialized", "stock_type",
                                 "item_type", "deleted", "tax_category_id", "qty_per_pack", "pack_name", "low_sell_item_id", "hsn_code"], item_rows)
        self.planted["items_with_missing_supplier"] = [orphan_item]
        self.planted["item_with_value_2_in_boolean_column"] = [6]

        self.ins("ospos_items_taxes", ["item_id", "name", "percent"],
                 [(i, "VAT", Decimal("12.000")) for i in r.sample(range(1, n_items + 1), self.n(100))])
        self.ins("ospos_item_kits", ["item_kit_id", "item_kit_number", "name", "item_id", "kit_discount", "kit_discount_type",
                                     "price_option", "print_option", "description"],
                 [(k, f"KIT{k}", f"Starter bundle {k}", 0, Decimal("0.00"), 0, 0, 0, "Bundle of everyday items") for k in range(1, 7)])
        kit_items = {(k, i): Decimal(str(r.choice([1, 2, 3]))) + Decimal("0.000") for k in range(1, 7) for i in r.sample(range(1, n_items), 4)}
        self.ins("ospos_item_kit_items", ["item_kit_id", "item_id", "quantity", "kit_sequence"], [(k, i, q, 0) for (k, i), q in kit_items.items()])
        qty_rows = [(i, 1, Decimal(str(r.randint(0, 400))) + Decimal("0.000")) for i in range(1, n_items + 1)]
        qty_rows += [(i, 2, Decimal(str(r.randint(0, 60))) + Decimal("0.125")) for i in range(1, n_items + 1, 5)]
        self.ins("ospos_item_quantities", ["item_id", "location_id", "quantity"], qty_rows)

        inv, bad_inv = [], []
        for k in range(self.n(600)):
            inv.append((k + 1, r.randint(1, n_items - 1), r.choice(emp_ids), self.ts(), r.choice(["Initial stock", "Recount", "Damaged", "Delivery"]),
                        1, Decimal(str(r.randint(-20, 100))) + Decimal("0.000")))
        inv[10] = inv[10][:3] + ("0000-00-00 00:00:00",) + inv[10][4:]
        for k in range(3):
            bad_inv.append((len(inv) + k + 1, 90000 + k, emp_ids[0], self.ts(), "item removed from catalogue", 1, Decimal("1.000")))
        self.ins("ospos_inventory", ["trans_id", "trans_items", "trans_user", "trans_date", "trans_comment", "trans_location", "trans_inventory"], inv + bad_inv)
        self.planted["inventory_rows_for_missing_items"] = len(bad_inv)

        # attributes, including a chain inside one table whose root parent is missing
        self.ins("ospos_attribute_definitions", ["definition_id", "definition_name", "definition_type", "definition_unit", "definition_flags", "definition_fk", "deleted"],
                 [(1, "Colour", "DROPDOWN", None, 5, None, 0), (2, "Weight", "DECIMAL", "kg", 3, None, 0), (3, "Best before", "DATE", None, 1, None, 0),
                  (4, "Note", "TEXT", None, 0, None, 0), (5, "Legacy group", "GROUP", None, 0, 4000, 0), (6, "Legacy child", "TEXT", None, 0, 5, 0)])
        self.planted["attribute_definitions_chain_with_missing_root"] = [5, 6]
        vals = [(k + 1, v, None, None) for k, v in enumerate(["Red", "Blue", "Green", "Black", "Yellow"])]
        vals += [(6 + k, None, None, Decimal(str(round(0.25 * (k + 1), 3)))) for k in range(5)]
        vals += [(11 + k, None, (self.base + timedelta(days=30 * k)).strftime("%Y-%m-%d"), None) for k in range(5)]
        self.ins("ospos_attribute_values", ["attribute_id", "attribute_value", "attribute_date", "attribute_decimal"], vals)
        links = [(r.randint(1, 5), 1, i, None, None) for i in r.sample(range(1, n_items - 1), 40)]
        links += [(r.randint(6, 10), 2, i, None, None) for i in r.sample(range(1, n_items - 1), 25)]
        links += [(1, 1, 80000, None, None), (2, 1, 80001, None, None)]  # items that do not exist
        seen, uniq = set(), []
        for lk in links:
            if lk[2:] + (lk[1],) not in seen:
                seen.add(lk[2:] + (lk[1],))
                uniq.append(lk)
        self.ins("ospos_attribute_links", ["attribute_id", "definition_id", "item_id", "sale_id", "receiving_id"], uniq)
        self.planted["attribute_links_for_missing_items"] = 2

        # gift cards with the largest legal money value
        gc = [(self.ts(), k + 1, f"GC{1000 + k}", self.money(5, 500), 0, r.choice(cust_ids + [None])) for k in range(self.n(40))]
        gc[0] = (gc[0][0], 1, "GC1000", Decimal("9999999999999.99"), 0, None)
        self.ins("ospos_giftcards", ["record_time", "giftcard_id", "giftcard_number", "value", "deleted", "person_id"], gc)

        # expenses and cash ups
        ex_cats = ["Rent", "Electricity", "Packaging", "Transport", "Repairs", "Staff meals"]
        self.ins("ospos_expense_categories", ["expense_category_id", "category_name", "category_description", "deleted"],
                 [(k + 1, c, f"{c} costs", 0) for k, c in enumerate(ex_cats)])
        ex = [(k + 1, self.ts(), self.money(20, 4000), r.choice(["Cash", "Check", "Due"]), r.randint(1, 6), r.choice(["", "Monthly", "Invoice 22-118"]),
               r.choice(emp_ids), 0, None, None, r.choice(sup_ids + [None])) for k in range(self.n(60))]
        ex[3] = ex[3][:1] + ("0000-00-00 00:00:00",) + ex[3][2:]
        ex[9] = ex[9][:1] + ("0000-00-00 00:00:00",) + ex[9][2:]
        ex[12] = ex[12][:1] + (None,) + ex[12][2:]
        ex[14] = ex[14][:2] + (Decimal("-19.99"),) + ex[14][3:]  # a refund
        self.ins("ospos_expenses", ["expense_id", "date", "amount", "payment_type", "expense_category_id", "description", "employee_id",
                                    "deleted", "supplier_tax_code", "tax_amount", "supplier_id"], ex)
        cash = []
        for k in range(self.n(30)):
            cash.append((k + 1, self.ts(), None if k % 7 == 3 else self.ts(), Decimal("200.00"), Decimal("0.00"), 0, self.money(500, 3000),
                         self.money(100, 900), Decimal("0.00"), self.money(700, 4000), "Shift close", r.choice(emp_ids), r.choice(emp_ids), 0, Decimal("0.00")))
        cash[5] = cash[5][:2] + ("0000-00-00 00:00:00",) + cash[5][3:]
        self.ins("ospos_cash_up", ["cashup_id", "open_date", "close_date", "open_amount_cash", "transfer_amount_cash", "note", "closed_amount_cash",
                                   "closed_amount_card", "closed_amount_check", "closed_amount_total", "description", "open_employee_id",
                                   "close_employee_id", "deleted", "closed_amount_due"], cash)
        self.planted["zero_dates_in_nullable_columns"] = {"ospos_expenses.date": 2, "ospos_cash_up.close_date": 1}

        # receivings
        n_rec = self.n(60)
        recs, rec_items = [], []
        for rid in range(1, n_rec + 1):
            recs.append((self.ts(), r.choice(sup_ids), r.choice(emp_ids), r.choice([None, "Delivered by van"]), rid, r.choice(["Cash", "Check", None]), f"PO-{rid:04d}"))
            for line, it in enumerate(r.sample(range(1, n_items - 1), r.randint(2, 5)), start=1):
                rec_items.append((rid, it, None, None, line, Decimal(str(r.randint(5, 60))) + Decimal("0.000"), self.money(0.5, 60), item_prices[it],
                                  Decimal("0.00"), 0, 1, Decimal("1.000")))
        self.ins("ospos_receivings", ["receiving_time", "supplier_id", "employee_id", "comment", "receiving_id", "payment_type", "reference"], recs)
        self.ins("ospos_receivings_items", ["receiving_id", "item_id", "description", "serialnumber", "line", "quantity_purchased", "item_cost_price",
                                            "item_unit_price", "discount", "discount_type", "item_location", "receiving_quantity"], rec_items)

        self._sales(n_items, emp_ids, cust_ids, item_prices, orphan_item)
        self._sessions()
        self._gaps_and_probe()

    def _sales(self, n_items, emp_ids, cust_ids, item_prices, orphan_item) -> None:
        r = self.rng
        n_sales = self.n(900)
        sales, s_items, s_taxes_i, pays, s_taxes, rewards, points = [], [], [], [], [], [], []
        missing_cust = {n_sales - 2, n_sales - 1, n_sales}  # sales whose customer record is gone
        zero_time = set(r.sample(range(1, n_sales - 3), 3))
        for sid in range(1, n_sales + 1):
            cust = None if r.random() < 0.3 else r.choice(cust_ids)
            if sid in missing_cust:
                cust = 888000 + sid
            stamp = "0000-00-00 00:00:00" if sid in zero_time else self.ts()
            invoice = f"INV-{sid:06d}" if r.random() < 0.25 else None
            sales.append((stamp, cust, r.choice(emp_ids), r.choice([None, None, "Gift wrap", "Pick up Friday"]), invoice, None, sid,
                          r.choice([0, 0, 0, 0, 1, 2]), None, None, r.choice([0, 0, 0, 1])))
            lines = r.sample(range(1, n_items), r.randint(1, 5))
            if sid in (11, 12):
                lines[0] = orphan_item
            subtotal = Decimal(0)
            for line, it in enumerate(lines, start=1):
                qty = Decimal(str(r.choice([1, 1, 1, 2, 3, 5]))) + (Decimal("0.500") if r.random() < 0.05 else Decimal("0.000"))
                disc = r.choice([Decimal("0.00")] * 4 + [Decimal("5.00"), Decimal("10.00")])
                price = item_prices.get(it, Decimal("10.00"))
                net = (qty * price * (Decimal(100) - disc) / Decimal(100)).quantize(Q2, ROUND_HALF_UP)
                subtotal += net
                s_items.append((sid, it, None, None, line, qty, (price * Decimal("0.7")).quantize(Q2), price, disc, 0, 1, 0))
                s_taxes_i.append((sid, it, line, "VAT", Decimal("12.0000"), 0, 0, 0, (net * Decimal("0.12")).quantize(Q4), 1, 1, 1))
            tax = (subtotal * Decimal("0.12")).quantize(Q2, ROUND_HALF_UP)
            total = subtotal + tax
            s_taxes.append((sid, 1, 1, 1, subtotal.quantize(Q4), tax.quantize(Q4), 0, "VAT", Decimal("12.0000"), 1, 0))
            if r.random() < 0.2 and total > Decimal("10"):
                half = (total / 2).quantize(Q2)
                pays.append((sid, "Cash", half, Decimal("0.00"), 0, r.choice(emp_ids), stamp, ""))
                pays.append((sid, "Credit Card", total - half, Decimal("0.00"), 0, r.choice(emp_ids), stamp, f"AUTH{sid:06d}"))
            else:
                pays.append((sid, r.choice(["Cash", "Cash", "Credit Card", "Debit Card", "Gift Card"]), total, Decimal("0.00"), 0, r.choice(emp_ids), stamp, ""))
            if cust is not None and r.random() < 0.15:
                rewards.append((sid, round(r.uniform(0.5, 25), 1), r.choice([0.0, 0.1, 2.5])))
        # orphans of every flavour
        for k in range(3):
            pays.append((70000 + k, "Cash", Decimal("12.34"), Decimal("0.00"), 0, emp_ids[0], self.ts(), "no such sale"))
        for k in range(5):
            s_taxes.append((60000 + k, 1, 1, 1, Decimal("100.0000"), Decimal("12.0000"), 0, "VAT", Decimal("12.0000"), 1, 0))
        for k in range(4):  # the sale exists, the sale line does not: passes the legacy key, fails the repaired one
            s_taxes_i.append((1, 5 + k, 90 + k, "VAT", Decimal("12.0000"), 0, 0, 0, Decimal("1.2300"), 1, 1, 1))
        for k in range(2):
            s_items.append((2, 70000 + k, None, None, 40 + k, Decimal("1.000"), Decimal("1.00"), Decimal("2.00"), Decimal("0.00"), 0, 1, 0))
        for sid in (3, 4):
            points.append((sid, 1, 90000 + sid, 5))
        self.ins("ospos_sales", ["sale_time", "customer_id", "employee_id", "comment", "invoice_number", "quote_number", "sale_id", "sale_status",
                                 "dinner_table_id", "work_order_number", "sale_type"], sales)
        self.ins("ospos_sales_items", ["sale_id", "item_id", "description", "serialnumber", "line", "quantity_purchased", "item_cost_price",
                                       "item_unit_price", "discount", "discount_type", "item_location", "print_option"], s_items)
        self.ins("ospos_sales_items_taxes", ["sale_id", "item_id", "line", "name", "percent", "tax_type", "rounding_code", "cascade_sequence",
                                             "item_tax_amount", "sales_tax_code_id", "jurisdiction_id", "tax_category_id"], s_taxes_i)
        pay_rows = [(k + 1,) + p for k, p in enumerate(pays)]
        self.ins("ospos_sales_payments", ["payment_id", "sale_id", "payment_type", "payment_amount", "cash_refund", "cash_adjustment", "employee_id",
                                          "payment_time", "reference_code"], pay_rows)
        self.ins("ospos_sales_taxes", ["sale_id", "jurisdiction_id", "tax_category_id", "tax_type", "tax_group", "sale_tax_basis", "sale_tax_amount",
                                       "print_sequence", "name", "tax_rate", "sales_tax_code_id", "rounding_code"],
                 [(s[0], s[1], s[2], 1, "VAT", s[4], s[5], s[6], s[7], s[8], s[9], s[10]) for s in s_taxes])
        self.ins("ospos_sales_reward_points", ["sale_id", "earned", "used"], rewards)
        self.ins("ospos_customers_points", ["person_id", "package_id", "sale_id", "points_earned"], [(cust_ids[0], 2, 5, 12), (cust_ids[1], 3, 6, 4)] + [(cust_ids[2], 1, p[2], p[3]) for p in points])
        self.planted["sales_with_missing_customer"] = sorted(missing_cust)
        self.planted["sales_with_zero_time"] = sorted(zero_time)
        self.planted["sales_items_for_missing_items"] = 2
        self.planted["payments_for_missing_sales"] = 3
        self.planted["sales_taxes_for_missing_sales"] = 5
        self.planted["sale_item_taxes_without_a_sale_line"] = 4
        self.planted["customer_points_for_missing_sales"] = 2

    def _sessions(self) -> None:
        r = self.rng
        rows = []
        for k in range(6):
            blob = bytes([r.randint(0, 255) for _ in range(40)]) + b"\x00\xff\x00session"
            rows.append((f"sess{k:036d}", f"10.0.0.{k + 1}", 1_700_000_000 + k * 977, blob))
        rows.append(("sess-big-unsigned-0000000000000000000", "::1", 4_294_967_295, b""))
        self.ins("ospos_sessions", ["id", "ip_address", "timestamp", "data"], rows)

    def _gaps_and_probe(self) -> None:
        """Delete the newest few sales so the id counter sits above the data, then try an emoji the legacy column cannot hold."""
        with self.c.cursor() as cur:
            cur.execute("SELECT MAX(sale_id) FROM ospos_sales")
            top = cur.fetchone()[0]
            gone = list(range(top - 14, top - 7))  # inside the range, so a real gap, and above the planted-orphan sales
            for tbl in ("ospos_sales_payments", "ospos_sales_items_taxes", "ospos_sales_items", "ospos_sales_taxes", "ospos_sales_reward_points"):
                cur.execute(f"DELETE FROM {tbl} WHERE sale_id BETWEEN %s AND %s", (gone[0], gone[-1]))
            cur.execute("DELETE FROM ospos_sales WHERE sale_id BETWEEN %s AND %s", (gone[0], gone[-1]))
            self.planted["sale_ids_deleted_leaving_a_gap"] = [gone[0], gone[-1]]
        # the id counter above the data: insert and delete a throwaway sale with a high id
        with self.c.cursor() as cur:
            cur.execute("INSERT INTO ospos_sales (sale_id, sale_time, employee_id) VALUES (5000, '2025-01-01 00:00:00', 1)")
            cur.execute("DELETE FROM ospos_sales WHERE sale_id = 5000")
        self.planted["auto_increment_counter_left_above_max_id"] = "ospos_sales: id 5000 inserted then deleted"

    def counts_now(self) -> dict[str, int]:
        out = {}
        with self.c.cursor() as cur:
            cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY 1")
            for (t,) in cur.fetchall():
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                out[t] = cur.fetchone()[0]
        return out


def emoji_probe(cfg: MysqlConfig) -> dict[str, str]:
    """The schema is utf8mb3: MySQL cannot hold a four byte character in it. Show that, in strict mode."""
    conn = pymysql.connect(host=cfg.host, port=cfg.port, user=cfg.user, password=cfg.password, database=cfg.database, charset="utf8mb4", autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION sql_mode = 'STRICT_ALL_TABLES'")
            try:
                cur.execute("INSERT INTO ospos_stock_locations (location_id, location_name, deleted) VALUES (99, %s, 0)", ("depot \U0001F600",))
                cur.execute("DELETE FROM ospos_stock_locations WHERE location_id = 99")
                return {"result": "accepted (unexpected)"}
            except pymysql.err.MySQLError as e:
                return {"result": "rejected", "error": f"{e.args[0]}: {e.args[1][:80]}"}
    finally:
        conn.close()


def reset_source(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SET SESSION foreign_key_checks = 0")
        cur.execute("SET SESSION sql_mode = ''")
        # MySQL 8.4 refuses a foreign key that points at a non-unique column; this legacy schema has one.
        cur.execute("SET SESSION restrict_fk_on_non_standard_key = 0")
        cur.execute("SELECT DATABASE()")
        db = cur.fetchone()[0]
        cur.execute(f"DROP DATABASE `{db}`")
        cur.execute(f"CREATE DATABASE `{db}` CHARACTER SET utf8mb3 COLLATE utf8mb3_general_ci")
        cur.execute(f"USE `{db}`")
        for stmt in split_statements(SCHEMA_FILE.read_text(encoding="utf8")):
            cur.execute(stmt)
        for stmt in split_statements(REFDATA_FILE.read_text(encoding="utf8")):
            cur.execute(stmt)


def seed(cfg: MysqlConfig | None = None, *, seed_value: int = DEFAULT_SEED, scale: float = 1.0, manifest: Path | None = None) -> dict:
    cfg = cfg or MysqlConfig.from_env()
    conn = mysql_connect(cfg)
    try:
        reset_source(conn)
        s = Seeder(conn, seed_value, scale)
        s.build()
        info = {"seed": seed_value, "scale": scale, "rows": s.counts_now(), "planted": s.planted}
    finally:
        conn.close()
    info["emoji_probe"] = emoji_probe(cfg)
    info["total_rows"] = sum(info["rows"].values())
    if manifest:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf8")
    return info
