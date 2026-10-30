# Technical assessment: Open Source Point of Sale 3.3.9

Register this says plainly: this is a demonstration assessment I built on a public open source
project with invented data, not a client engagement. Nobody's real shop, customer list or sale history
is anywhere in this document or this repository. The method, the checks and the numbers are real; the
subject is a stand-in for the kind of PHP/CodeIgniter codebase a business owner might ask "salvage or
rebuild?" about.

## Executive summary (for a non-technical owner)

Open Source Point of Sale (OSPOS) is a free, ten plus year old shop till system: ring up sales, track
stock across locations, manage customers, suppliers, gift cards and basic reports. The version reviewed
here, 3.3.9, runs on tools that are themselves old: the underlying PHP framework has had no update since
March 2022, and the PHP version it is written for (7.2 through 7.4) stopped receiving security fixes in
November 2022. The code starts and runs on a current PHP 8.3 install (I tested it), but it is noisy with
warnings there and one part (a class naming collision, see below) breaks outright, which is the kind of
thing that turns into a real outage on a live store at the worst time.

The database is in better shape than the code. Its 39 tables are mostly sound: real primary keys, real
money columns, and most relationships protected by foreign keys. A handful of relationships are not
protected (notably between a sale's line items and its taxes), which is the kind of gap that lets
orphaned records accumulate quietly for years, and I found and had to specifically design around exactly
that gap when building the migration in this repository.

**What I would tell an owner:** the database and the core sale/inventory logic are worth keeping; the
framework underneath is worth replacing. That is a phased plan, not a weekend job, and not a full
rebuild either. See Section 9 for the actual phases, Section 7 for what to keep as is, refactor, or
replace, and Section 10 for the honest limits of what one person reviewing from the outside in a few
hours can actually tell you.

---

## 1. Scope and method

**Subject.** [opensourcepos/opensourcepos](https://github.com/opensourcepos/opensourcepos), MIT
licensed, cloned at tag `3.3.9`, commit `c00ff28d10f25c2638a65cbfbbcd08b75a83c59f` (committed
2023-11-06). I chose this tag because it is the last release before the project renamed itself from
`jekkos/opensourcepos` legacy history, is still CodeIgniter 3 (later `3.4.x` releases on the `master`
branch moved to CodeIgniter 4, which is a different review), and ships a complete, runnable SQL schema
(`database/tables.sql`, `database/constraints.sql`) rather than migrations-only. The repository was
cloned to a scratch folder outside this repo and is not vendored here: only short quoted snippets, file
paths and line numbers are kept, per its MIT licence (reproduced in `NOTICE`, below).

**What was actually read.** Every file under `application/controllers`, `application/models`,
`application/libraries`, `application/config`, `database/`, `composer.json` and `composer.lock`;
representative files under `application/views` and `application/helpers`; the Dockerfile and
`docker-compose*.yml`; `application/tests/*` (all 3 PHP test files) and `test/*.js` (5 Selenium/JS
sanity scripts, read but not run, no browser driver in this environment).

**Tools actually run**, all offline or against disposable local containers, nothing against the real
internet except cloning the public repo and reading public advisory data already bundled in Composer's
own advisory database:

| Tool | What it did | Evidence |
|---|---|---|
| `docker build` (the project's own `Dockerfile`, target `ospos`) | built and ran OSPOS 3.3.9 on PHP 7.4 against a local MySQL 8 container | this section |
| `docker build` (same Dockerfile, PHP 8.3 base image) | ran the same app on PHP 8.3 to test runtime compatibility | `docs/evidence/php83-login-cli.txt` |
| `composer audit --locked` | known CVEs in the locked dependency versions | `docs/evidence/composer-audit.json` |
| `phpcs` + `PHPCompatibility` (3.10 / 9.3) | flags code incompatible with a target PHP version | `docs/evidence/phpcompat-7.4.json`, `-8.1.json`, `-8.3.json` |
| the project's own PHPUnit suite, with Xdebug coverage | runs the 9 tests that exist and measures real line/method coverage | `docs/evidence/phpunit-coverage.txt` |
| `scripts/assessment/metrics.py` (written for this assessment) | file and line counts by area, biggest files, longest functions | `docs/evidence/metrics.json` |
| `scripts/assessment/security_checks.py` (written for this assessment) | grep based, file:line security leads for a human to read and judge | `docs/evidence/security-grep.txt` |
| manual read + one control request against a disposable local instance | investigated the one lead that looked like SQL injection | `docs/evidence/sort-injection-probe.txt` |

The two Python scripts are in this repository (`scripts/assessment/`) so every number below can be
reproduced against a fresh checkout of the same tag: `python scripts/assessment/metrics.py <checkout>`
and `python scripts/assessment/security_checks.py <checkout>`.

**What I did not do**: a licensed static analysis tool (PHPStan, Psalm) against the full codebase with
a bootstrapped autoloader (CodeIgniter 3's loader makes this nontrivial without a real install; a
future pass should add it); a dynamic security scan (OWASP ZAP or similar) against a running instance;
interviewing anyone who actually ran this software in production, since there is no real business
behind this review. Section 10 lists every other limit.

---

## 2. Architecture map

OSPOS is a single CodeIgniter 3 application, MVC, no API layer, no background workers, one PHP process
serving one MySQL database:

```
Browser --> Apache/PHP --> CodeIgniter 3 router --> Controller --> Model --> MySQLi --> MySQL
                                              \--> Library (business logic)
                                              \--> View (HTML, or a JSON echo for AJAX)
```

**Controllers** (`application/controllers/`, 25 files, 9,092 lines): one per module (`Items`, `Sales`,
`Customers`, `Suppliers`, `Receivings`, `Employees`, `Reports`, `Config`, ...), each extending a shared
`Secure_Controller` that handles login and per-module permission checks. Most controllers follow the
same shape: `index()` renders the management page, `search()` answers an AJAX grid request, `save()`
and `remove()` handle the create/update/delete form posts, `get_row()` or similar returns one record as
JSON for the edit modal.

**Models** (`application/models/`, 61 files, 10,802 lines) hold the actual queries, built with
CodeIgniter's query builder. `Sale.php` (1,448 lines) and `Item.php` (986 lines) are the two largest and
carry the core domain logic: a sale's totals, tax lines and payments; an item's price, stock level
across locations, and its "kit" (bundle) composition.

**Libraries** (`application/libraries/`, 11 files, 3,226 lines) hold cross cutting business rules that
do not map to one database table: `Sale_lib.php` (1,367 lines) is the checkout engine (adding a line
item, applying a discount, computing tax, completing a sale); `Tax_lib.php` (468 lines) resolves which
tax rates apply by jurisdiction and category; `Barcode_lib.php` generates printable barcodes;
`Receiving_lib.php` mirrors `Sale_lib` for incoming stock.

**Views** (`application/views/`, 116 files, 16,932 lines) are server rendered HTML with embedded PHP and
a good deal of inline JavaScript (notably `sales/register.php`, the checkout screen, at 1,002 lines with
551 branch like tokens by the crude count in `metrics.json`: this is the single most complex file in the
project by that measure).

**Database access** is exclusively through CodeIgniter's Active Record query builder (`$this->db->...`)
for ordinary CRUD; a handful of raw `->query()` calls build temporary tables for reports (see Section
5). There is no ORM beyond CodeIgniter's own, no repository layer, and no service layer separating
controllers from models: a controller calls a model directly, which is typical of CodeIgniter 3 apps of
this era.

**A request, end to end** (completing a sale): browser POSTs the cart to `Sales::complete()`
(`application/controllers/Sales.php`, a 257 line method, the single longest function in the codebase per
`metrics.json`) &rarr; it asks `Sale_lib` to validate and total the cart &rarr; `Sale_lib` calls `Tax_lib`
per line item &rarr; the controller calls `Sale::save()` (`application/models/Sale.php`) which writes
`ospos_sales`, `ospos_sales_items`, `ospos_sales_items_taxes`, `ospos_sales_taxes` and
`ospos_sales_payments` inside one transaction &rarr; the view echoes JSON back to the register screen's
JavaScript.

**Dependencies** (`composer.json`): `codeigniter/framework ^3.1.11` (resolved to `3.1.11` in the lock
file), `dompdf/dompdf ^2.0.2` (receipt and report PDFs), `tamtamchik/namecase`, `vlucas/phpdotenv ^2.4`
(resolved `2.6.8`), `paragonie/random_compat`. Dev-only: PHPUnit 7.5.6 and `kenjis/ci-phpunit-test`.

---

## 3. Database review

The schema (`database/tables.sql`, `database/constraints.sql`) was loaded into a disposable MySQL 8
container and inspected through `information_schema`, not just read as text, so what follows is measured
against the database the application actually ran, including the one migration (`20210714140000`) that
ran automatically on first login and changed two columns (see below).

**39 tables, 51 declared foreign keys, every table InnoDB, every table `utf8`/`utf8mb3`.** All money
columns are `DECIMAL`, never `FLOAT` or `DOUBLE` (good: no rounding surprises), typically
`decimal(15,2)` for prices and payments and `decimal(15,3)` for quantities, letting a shop sell by the
gram or the tenth of a unit.

**Primary keys**: every table has one except two: `ospos_migrations` (a single `version` column, which
is how the framework's migration tool tracks itself, not a design flaw) and `ospos_sessions` (CodeIgniter's
own session table, keyed `id` but declared without `PRIMARY KEY`, just a plain `KEY`, in the stock
schema). `ospos_attribute_links` also has no primary key, only a pair of `UNIQUE` indexes, which means a
duplicate (attribute, item) pair with different `sale_id`/`receiving_id` NULLs can slip through; I found
this by trying to build a primary key for it during migration planning and finding none existed to
reuse.

**Foreign keys that will not carry over to PostgreSQL as declared.** PostgreSQL requires a foreign key's
target columns to be a primary or unique key; MySQL enforces this too in principle, but one relationship
in this schema violates it anyway:

- `ospos_sales_items_taxes_ibfk_1` points `ospos_sales_items_taxes.sale_id` at
  `ospos_sales_items.sale_id`, but `sale_id` alone is not unique on `ospos_sales_items` (its real key is
  `sale_id, item_id, line`). Confirmed in MySQL by direct query over
  `information_schema.key_column_usage` joined to `referential_constraints`: this constraint exists and
  is enforced by MySQL today, but only because MySQL (unlike PostgreSQL) permits a foreign key to
  reference a column that is merely the *prefix* of a composite index, not a full unique key by itself.
  This is MySQL specific leniency, not a real one to one relationship; the actual relationship a sale's
  per item tax line needs is to one specific `(sale_id, item_id, line)` row of `ospos_sales_items`, which
  the existing key does cover. `tillcarry`'s migration plan documents this exact repair
  (`FK_REPLACEMENTS` in `src/tillcarry/plan.py`) and the seeded data includes rows that only pass the
  loose MySQL version of this key and fail the tighter one, specifically to prove the repair matters (see
  Section 6 of this document, and `tests/test_integration.py::test_every_planted_orphan_is_in_quarantine...`).
- `ospos_sales_taxes` has **no foreign key to `ospos_sales` at all** in the stock schema, despite holding
  a `sale_id` on every row and the application always writing it alongside a sale. This is a real,
  shipped gap, not a migration artifact: a deleted sale (the application never deletes sales through its
  own UI, but a database administrator doing cleanup could) leaves orphaned tax rows behind forever,
  silently. `tillcarry` adds this relationship (`EXTRA_FKS` in `plan.py`) specifically so the migration
  can catch and quarantine any row that would have been invisible under the original schema.

**Collation makes four `UNIQUE` text keys case insensitive**, something MySQL's `utf8_general_ci`
does for free and PostgreSQL's default `text` does not: `ospos_employees.username`,
`ospos_modules.module_id`/`name_lang_key`/`desc_lang_key`, `ospos_giftcards.giftcard_number`,
`ospos_app_config.key`, and others (17 columns found by the migration planner's own analysis, which
walks every `UNIQUE` index and every column joined to one of those columns through a foreign key, since
a join partner must share the same comparison behaviour). Moving these to plain PostgreSQL `text` would
silently let `"ADMIN"` and `"admin"` coexist as two different usernames, which is a real behavioural
change, not a cosmetic one. `tillcarry` maps all of them to PostgreSQL's `citext` type instead.

**`tinyint(1)` is used for two different things**, and the schema alone cannot tell you which: a real
boolean flag (`deleted`, `is_serialized`, almost every table) and a small status or type code with more
than two values (`ospos_sales.sale_status`, `ospos_items.item_type`, `ospos_items.stock_type`). Treating
every `tinyint(1)` as a PostgreSQL `boolean` (a common, careless migration shortcut) would be silently
wrong for the status columns. `tillcarry` decides this per column from an explicit, reviewed allowlist
checked against the actual data (see Section 6).

**No views, no triggers, no stored routines** exist in this schema (`information_schema.views`,
`.triggers` and `.routines` all returned zero rows against the live container): all business logic lives
in PHP, which is good news for a migration (nothing hidden in the database to reverse engineer) and
confirms the application layer, not the schema, is where the real porting effort goes.

**One migration runs on login, automatically, with no operator in the loop.** `Login::login_check()`
(`application/controllers/Login.php`) calls `$this->migration->is_latest()` and, if false, calls
`$this->migration->latest()` with `set_time_limit(3600)`, inside the web request. On a fresh 3.3.9
checkout this ran migration `20210714140000` (`move_expenses_categories`) the first time I logged in,
changing `ospos_expenses.expense_category_id` and adding `ospos_expense_categories`, confirmed by
diffing `information_schema.columns` before and after. Running a schema migration as a side effect of
the first user who happens to log in, inside an HTTP request, with a one hour timeout and no
confirmation step, is a real operational risk on a production instance with real data: a slow migration
can time out the request after partially applying, and nothing in the flow asks an operator "are you
sure", unlike `tillcarry`'s own migration, which uses an isolated schema and a single rename to go live
only after every row balances.

---

## 4. Dependency and runtime audit

**PHP.** `composer.json` declares `"php": "^7.2"`; the shipped `Dockerfile` uses the `php:7.4-apache`
base image. PHP 7.2 reached end of life 2020-11-30; PHP 7.4 reached end of life 2022-11-28 (both per
php.net's own supported-versions page). Neither branch receives security patches today. I built and ran
the application on PHP 8.3 (current, supported) using the project's own Dockerfile with only the base
image tag changed:

- It **starts and serves pages** (login screen rendered, login succeeded, `/home` and `/items` returned
  HTTP 200).
- It is **noisy**: 40+ "Creation of dynamic property is deprecated" warnings on a single login flow
  alone (PHP 8.2 deprecated untyped dynamic class properties; CodeIgniter 3's core classes rely on them
  throughout), plus one "implicitly required parameter after optional" deprecation in the language
  loader. None of these are fatal by themselves.
- It has **one real, reproducible fatal error**: `RuntimeException: Class Attribute already exists and
  doesn't extend CI_Model`, thrown from CodeIgniter's own loader (`system/core/Loader.php:353`) when the
  application's `Attribute` *model* class collides with PHP 8's built in `Attribute` class (added in PHP
  8.0 for native attributes/annotations). This is not a deprecation warning, it is a fatal, and it
  reproduces on every request that loads the `Attribute` model (confirmed via CLI request simulation,
  `docs/evidence/php83-login-cli.txt`). **This single class rename (`Attribute` to something else, plus
  every reference to it) is the one concrete blocking issue standing between this codebase and running
  on a currently supported PHP version**, everything else in the PHP 8.3 run was warnings.

**CodeIgniter.** The locked version is `3.1.11`; the framework's own repository
(`bcit-ci/CodeIgniter`, now effectively the CodeIgniter 3 line) last tagged a 3.x release, `3.1.13`, on
2022-03-03 (confirmed against the repository's own commit history for that tag). There has been no CI3
release in the time since. The project has one listed maintainer, and the CodeIgniter Foundation's
active development is CodeIgniter 4, a separate, incompatible framework; porting this application to CI4
is effectively a rewrite of every controller and model's base class usage, not an upgrade.

**Composer package audit** (`composer audit --locked`, against Composer's own bundled advisory
database, `docs/evidence/composer-audit.json`), 12 advisories across 3 packages:

| Package | Locked version | Advisories | Worst severity |
|---|---|---|---|
| `dompdf/dompdf` | 2.0.3 | 7 (CVE-2026-59943, -59942, -59941, -56722, -55555, -55554; CVE-2023-50262) | medium |
| `phenx/php-svg-lib` (dompdf's own dependency) | 0.5.0 | 3 (one with no CVE, marked critical by the advisory; CVE-2024-25117; CVE-2023-50251) | critical |
| `phpunit/phpunit` | 7.5.6 (dev only) | 1 (CVE-2026-24765, unsafe deserialization in coverage handling) | high |

The dompdf/php-svg-lib chain backs PDF generation (receipts, reports): the critical advisory and two of
the mediums concern SVG image handling inside a PDF, which matters only if the application ever renders
an SVG supplied by a user or a third party into a PDF; OSPOS's own PDF templates do not appear to do
this from a read of `application/helpers/dompdf_helper.php` and the report views, but I did not trace
every code path that calls dompdf, so treat this as a lead, not a closed question. The PHPUnit advisory
only matters if the dev dependencies ever run against untrusted input, which in a CI pipeline they
normally do not. `phpunit/php-token-stream` and `sebastian/resource-operations` are flagged as
**abandoned** (no advisory, just unmaintained) by the same audit.

**JavaScript dependencies**: `package.json` lists build tooling only (Grunt, Bower) for asset compilation,
no runtime JS dependencies were audited as part of this review; a full assessment should run `npm audit`
against the lock file as a follow up.

---

## 5. Security findings

Every finding below is from `scripts/assessment/security_checks.py` (a grep based lead finder, this
repo) read against the actual file and line, not a third party scanner's unverified output. The full
output is `docs/evidence/security-grep.txt`; this section explains which leads turned out to matter
after a human read them.

**Authentication: bcrypt with a legacy MD5 upgrade path, not a finding.**
`application/models/Employee.php::login()` (lines 326-353) checks `hash_version`: version 1 compares
`md5($password)` directly and upgrades to `password_hash()` (bcrypt via `PASSWORD_DEFAULT`) on
successful login; version 2 uses `password_verify()`. This is the standard, correct way to retire a
weak hash without forcing every user to reset their password, and the seed data in this repository ships
only version 2 hashes. Listed here so the pattern is on record, not because it is wrong.

**CSRF and output filtering are enabled, with one excluded route and global XSS filtering off, as a
deliberate design choice, not an oversight.** `application/config/config.php`: `csrf_protection = TRUE`,
`csrf_token_name`/`csrf_cookie_name` set, `csrf_exclude_uris = array('login')` (the login form itself is
exempt, which is normal: there is no session yet to attach a token to), `global_xss_filtering = FALSE`.
The codebase instead calls `$this->xss_clean()` explicitly at specific output points (20 call sites
found); `global_xss_filtering = FALSE` is CodeIgniter 3's documented recommended setting precisely
because blanket input filtering has a long history of mangling legitimate data (a customer named
`O'Brien`, an item description containing `<`), so this is a defensible choice, not a gap, provided every
real injection point is covered by an explicit escape, which the next two findings test.

**Investigated and downgraded: `order_by($sort, $order)` with an unvalidated `sort` parameter, 15 call
sites, not demonstrated to be exploitable.** Every list screen (`Items`, `Sales`, `Customers`,
`Employees`, `Suppliers`, `Expenses`, `Giftcards`, `Cashups`, `Attributes`, `Item_kits`, `Tax_categories`,
`Tax_codes`, `Tax_jurisdictions`, `Taxes`) reads `$sort = $this->input->get('sort')` straight from the
query string and passes it to `$this->db->order_by($sort, $order)` with no allowlist of real column
names. On first read this looks like classic unescaped identifier injection. I read CodeIgniter 3's own
`order_by()` implementation (`system/database/DB_query_builder.php`) and confirmed it escapes the column
name through `_protect_identifiers()` whenever the call does not explicitly pass `escape = FALSE`; none
of the 15 call sites in this application do. I then tested this directly against a disposable local
instance (own throwaway data, own Docker network, authenticated as that instance's own default admin,
no real target anywhere): three requests to `/items/search`, one with a normal column name and two with
a crafted `sort` value containing a `SELECT SLEEP(...)` payload. All three returned HTTP 200 in about
0.03 seconds with no timing difference, consistent with the escaping working as the framework's source
says it should (`docs/evidence/sort-injection-probe.txt`). **Conclusion: not a demonstrated SQL
injection under CodeIgniter 3's own protections, but still worth fixing** as a hardening measure (an
explicit allowlist of sortable columns per model), because the safety here depends entirely on one shared
library function in a framework that stopped receiving updates in 2022 continuing to behave exactly as
read, forever, across 15 call sites that could each individually be changed by a future contributor who
does not know why the escaping matters.

**Raw SQL string concatenation: all for internal temporary table scaffolding, not user input.** 17 hits
for string-built `->query()` calls (`security-grep.txt`, check `sql-concat-in-query`); every one read
builds a `CREATE TEMPORARY TABLE` or similar DDL statement by concatenating `$this->db->dbprefix(...)`
(the table prefix, an application constant, never user supplied) with literal SQL. None concatenates a
request parameter into a query string. Two related hits are more interesting:
`Attribute.php:76` does `$this->db->where("attribute_$data_type", $attribute_value)`, where
`$data_type` selects which of four hardcoded internal column names (`attribute_value`,
`attribute_date`, `attribute_decimal`, plus a text variant) to filter on, read from
`Attribute::$types`, an internal constant list, not request input: safe, but written in a style that
would become dangerous the moment someone "simplifies" it to take the column name from the request. The
same pattern repeats in `Sale.php:460`. **Recommendation**: replace the string interpolation with a
`switch` or a lookup table even though the current inputs are safe, specifically because this style
invites the exact mistake found in the `order_by` finding above.

**File upload: extension allowlist only, no MIME or content check found.** `Items::handle_image_upload()`
and the equivalent in `Config.php` call CodeIgniter's `upload` library with
`allowed_types => $this->config->item('image_allowed_types')` (configurable, defaults include `svg`)
or a hardcoded `'gif|jpg|png'`. CodeIgniter's upload library checks the file extension and, depending on
version, a weak MIME sniff; it is well documented that extension based checks can be bypassed by a
polyglot file. SVG uploads specifically are a known stored-XSS vector (an SVG can contain a `<script>`
tag) if the uploaded file is ever served back inline rather than downloaded; I did not trace every path
that serves an uploaded item image to confirm whether this application is vulnerable to that specific
chain, so this is a lead for the next reviewer, not a closed finding.

**Secrets stored in a database settings table, encrypted at rest by the one feature that uses them, not
by the storage layer itself.** `ospos_app_config` holds `smtp_pass`, `msg_pwd`, `gcaptcha_secret_key`,
and the Mailchimp API key as plain rows (298 hits in the `sensitive-in-appconfig` check, almost all of
them the column simply being read or written like any other setting). Two call sites
(`Config.php:413, 442`) do encrypt the SMTP and messaging passwords with CodeIgniter's `encryption`
library before saving; the reCAPTCHA secret and Mailchimp key are not. The encryption key itself
(`$config['encryption_key']`) comes from an environment variable with an empty string default: if an
operator never sets `ENCRYPTION_KEY`, the "encrypted" password is encrypted with an empty key, which is
not meaningfully encrypted at all. `tillcarry`'s own seeded reference data deliberately excludes these
columns' real-world equivalents (the secret rows are stripped entirely from
`schema/ospos-3.3.9.reference-data.sql`) rather than migrating empty placeholders that could be mistaken
for real values.

**Session configuration is reasonable for its era**: database backed sessions (`sess_driver = 'database'`),
`sess_match_ip = TRUE` (rejects a hijacked cookie replayed from a different IP, at the cost of breaking
legitimate users behind a roaming mobile network or a load balancer that does not preserve client IP),
`cookie_httponly = TRUE`, `cookie_secure` tied to whether HTTPS is detected. No `SameSite` setting is
configured explicitly in `application/config/config.php`, but the actual response header observed when
running the app showed `SameSite=Strict` on the CSRF cookie and `HttpOnly` with no `SameSite` attribute
on the session cookie, meaning CodeIgniter 3's underlying session handler applies its own default; a
production deployment should confirm this explicitly rather than relying on a framework default from
2022.

---

## 6. Code quality and test coverage

**Size and shape** (from `scripts/assessment/metrics.py` against the full checkout,
`docs/evidence/metrics.json`): 25 controllers (9,092 lines), 61 models (10,802 lines), 11 libraries
(3,226 lines), 116 views (16,932 lines), 1,021 functions total across controllers/models/libraries, of
which **26 exceed 100 lines**. The ten longest: `Sales::complete` (257 lines),
`Sale::search` (185), `Sale_lib::add_item` (178), `Items::view` (177), `Items::save` (173),
`Sale::save` (172), and four more in the 100-170 range (full list in `metrics.json`). The biggest single
files by line count are `Reports.php` (1,666 lines), `Sales.php` (1,574), `Sale.php` (1,448),
`Sale_lib.php` (1,367) and `Items.php` (1,227): the sale and reporting logic is, unsurprisingly, where
the complexity concentrates, and it is concentrated in a small number of very long functions rather than
spread across many short ones, which is the single biggest readability and testability cost in this
codebase. A rewrite of the checkout flow that keeps the same business rules but breaks `complete()` and
`add_item()` into named steps would pay for itself quickly.

**Test coverage, measured, not estimated.** The project ships exactly 3 PHPUnit test files covering 3
narrow areas (`Locale_helper`, `Token_lib`'s barcode token generation, and a `Rounding_mode` enum), 9
tests, 26 assertions, all passing (`docs/evidence/phpunit-coverage.txt`). Running the same suite with
Xdebug coverage enabled against the project's own `phpunit.xml` whitelist (controllers, models, views,
libraries, helpers, hooks) measured:

| Metric | Covered | Total | Percent |
|---|---|---|---|
| Classes | 3 | 103 | 2.91% |
| Methods | 12 | 1,038 | 1.16% |
| Lines | 84 | 24,781 | 0.34% |

In plain terms: **none of the checkout flow, the inventory logic, the tax calculation, or any
controller is under automated test.** The 3 `test/*.js` files are Selenium browser scripts (manual
end-to-end smoke tests, not run as part of this assessment since no browser driver was set up in this
environment) that exercise giftcard numbering, a basic sale and receiving flow, and quantity handling;
reading them confirms they describe the intended behaviour but they are not wired into CI in the
repository I reviewed (no `.github/workflows` file calling them). **This near-zero coverage is the
single biggest risk to any refactor or migration of this codebase**: there is no automated safety net
to catch a regression in the tax engine or the checkout total, which is exactly why `tillcarry`'s own
migration tooling (the other half of this repository) treats "prove nothing changed" as a first class,
tested deliverable rather than an afterthought.

**`PHPCompatibility` static scan** against PHP 7.4, 8.1 and 8.3 targets (`phpcs`, own run,
`docs/evidence/phpcompat-*.json`) found the same 3 warnings at every target version, all
`ReservedFunctionNames.MethodDoubleUnderscore` (three methods named with PHP's reserved `__` magic
method prefix pattern in a way the standard flags defensively; read and confirmed harmless, they are
legitimate uses of `__construct`/`__get`-style magic in context). **This static scan did not catch the
one real PHP 8 fatal (the `Attribute` class collision) found in Section 4**, because a class name
collision with a PHP core class added in a later version is a runtime fact, not a static syntax
incompatibility; this is exactly why the assessment includes both a static scan and an actual run on the
target runtime; relying on either alone would have missed a real finding.

---

## 7. Reuse, refactor, migrate or replace matrix

| Area | Decision | Why |
|---|---|---|
| Database schema (39 tables) | **Reuse, with two repairs** | Sound types, real keys, no stored logic to reverse engineer; repair the two foreign key gaps found in Section 3 and the `tinyint(1)`/boolean ambiguity, which this repo's migration tool does automatically and documents (Section 6 continuation below, `src/tillcarry/plan.py`). |
| Customer, supplier, item, receiving data and history | **Reuse (migrate as data)** | This is the asset a shop actually needs kept: years of sales, customers and stock history. See Section 8. |
| Checkout / tax engine logic (`Sale_lib`, `Tax_lib`) | **Refactor, keep the rules** | The tax jurisdiction/category/rounding model (Section 3) is genuinely more capable than most small POS systems; the rules are worth keeping, the 1,367 and 468 line single files holding them are not. Extract into small, independently testable functions with unit tests written against the *existing* behaviour first, then refactor. |
| Controllers and the MVC wiring | **Replace (framework), reuse (intent)** | CodeIgniter 3 is unmaintained (Section 4); the *shape* of each controller (one module, CRUD plus a search endpoint) ports cleanly to almost any modern framework's controller/resource pattern, but the code itself does not survive a framework change line for line. |
| Views / front end (`application/views`, inline JS) | **Replace** | Server rendered HTML with inline jQuery is the part most tied to the specific framework and least reusable; a modern front end (even a server rendered one in a current framework) is a rewrite here regardless of backend choice. |
| Barcode, PDF receipt generation (`Barcode_lib`, dompdf) | **Migrate the library choice** | dompdf itself is still maintained upstream (newer than the locked 2.0.3, see Section 4); bump it rather than replace the concept. Barcode generation logic is small (236 lines) and portable as is. |
| Authentication (bcrypt via `password_hash`/`password_verify`) | **Reuse the algorithm, replace the plumbing** | The hashing choice is correct and portable to any framework; the session/cookie wiring around it is CodeIgniter specific and gets replaced with the new framework's own. |
| The 3 existing PHPUnit tests | **Reuse as a starting fixture, not a safety net** | They prove the barcode token and locale helpers work; they prove nothing about the checkout, inventory or reporting, which is where a migration's real risk lives (Section 6). |
| `ospos_sessions`, migration-on-login behaviour | **Replace** | Database backed sessions and a migration runner triggered by an HTTP request are patterns a modern framework or a proper deploy pipeline handles better and more safely (Section 3). |

---

## 8. Preservation of customer data and history

The data that actually matters to a business owner living through a modernization is exactly the part
the schema review in Section 3 found to be sound: `ospos_people`, `ospos_customers`, `ospos_suppliers`,
`ospos_employees`, every `ospos_sales*` table, `ospos_receivings*`, `ospos_inventory`, and
`ospos_giftcards`. None of it needs to be reconstructed or reinterpreted; it needs to be *moved*
correctly, which is a different and more tractable problem than "rebuild the business logic that
produced it."

This repository's migration tool (`tillcarry`, Section B of this repository, `src/tillcarry/`) is built
specifically to prove that kind of move: every source row is accounted for as either loaded or
quarantined with a stated, machine checked reason (never silently dropped); every zero or impossible
date (a known legacy data reality, not a hypothetical, see Section 3's 20-year-old schema and the awkward
rows seeded in `src/tillcarry/seed.py`) is converted by a documented rule and logged, never guessed
silently; every money column's total is checked to the cent between source and target, every column's
contents are checksummed, and a sample of rows is compared field by field. A real engagement with a real
shop's export would run this same tool against that export (after adapting its MySQL connection to the
real server), not against invented data, and the existing verifier would still have to pass before
anyone was told the migration was done.

---

## 9. Phased modernization vs. a full rebuild

**Phased modernization** (recommended for a shop depending on this software today):

1. **Phase 0, stabilize (1-2 weeks).** Fix the one PHP 8 fatal (rename the `Attribute` model class and
   every reference to it, Section 4); pin and run on a supported PHP version (8.1 or 8.3); run
   `composer audit` and bump dompdf/php-svg-lib past their advisories (Section 4); set `ENCRYPTION_KEY`
   explicitly in every environment. This alone removes the "runs on an unsupported, unpatched PHP" risk
   without touching behaviour.
2. **Phase 1, database migration with proof (1-3 weeks, this repository's method).** Export the real
   schema and data, run a `tillcarry`-style migration to PostgreSQL (or, if staying on MySQL, simply
   repair the two foreign key gaps and audit the `tinyint` columns in place), verify row for row, keep
   both databases running in parallel during a cutover window.
3. **Phase 2, extract and test the business logic (4-8 weeks).** Write characterization tests against
   the *current* checkout, tax and inventory behaviour before changing anything (Section 6 shows there
   are currently none), then refactor `Sale_lib`, `Tax_lib` and the longest controller methods into
   smaller, independently tested units, still inside CodeIgniter 3. This is the highest value, lowest
   risk phase: it makes every later phase safer without yet touching the framework.
4. **Phase 3, framework and front end replacement (8-16 weeks, the biggest phase).** Port the now-tested
   business logic into a current framework; rebuild the views. Effort depends heavily on target choice
   and is the widest estimate range here on purpose: a like for like PHP framework port is the low end, a
   full stack rewrite (new language, SPA front end) is the high end.
5. **Phase 4, decommission the old stack.** Once Phase 3's output has run in parallel and matched the old
   system's output for a full business cycle (at minimum a slow and a busy week, a full reporting month
   if the owner can wait that long), retire CodeIgniter 3 entirely.

**Full rebuild** (justifiable only if the business plans to meaningfully change how it operates, e.g.
adding features the current data model cannot express, multi-tenant SaaS, or a genuinely different UX):
discard the application layer, keep the data via the same Phase 1 migration method (the data is sound
regardless of which path is chosen, Sections 3 and 8), design a new domain model informed by, but not
bound by, the reuse/refactor/replace matrix in Section 7. Faster to reach a *different* product; slower
and riskier to reach *feature parity* with what the business already has, because every undocumented
business rule currently living inside `Sale_lib`'s 1,367 lines (with zero test coverage, Section 6) has
to be rediscovered from behaviour rather than ported.

**Decision criteria**: if the business is satisfied with what the software does today and mainly wants
it to stop being a security and maintainability liability, phase. If the business has outgrown what a
single-location-aware, PHP-MVC, server-rendered till system can express, and has budget for a 3-6 month
project with real risk of scope growth, consider a rebuild, but do the data migration (Phase 1) either
way and do not let "we're rebuilding anyway" become an excuse to skip verifying the data move.

**Effort ranges are ranges because:** they assume one capable full stack engineer, assume the real
production database is of a similar size and shape to what this review examined (no multi-million row
history, no heavily customized fork), and assume no new integrations are added mid-project. A business
with a much larger sales history, a customized install, or planned new features should treat every
number above as the optimistic end.

---

## 10. Limits of this assessment, stated plainly

- **This is one person's review from the outside, in a bounded amount of time, with no access to a real
  production deployment, no interviews with real users, and no visibility into any custom modifications
  a real installer might have made.** A real engagement would start by asking what, if anything, has
  been changed from stock.
- **No licensed static analyzer (PHPStan/Psalm) was run against the full codebase.** `phpcs` with
  `PHPCompatibility` checks syntax-level version compatibility, not type safety, dead code, or logic
  bugs; a follow up pass should add one, which requires bootstrapping CodeIgniter 3's autoloader for a
  standalone tool to understand the class graph.
- **No dynamic application security scan (OWASP ZAP, Burp) was run.** The security section is a grep
  based lead finder plus manual reading plus one narrow, consented control test against a disposable
  local instance with invented data; it is not a penetration test and does not claim completeness. The
  file upload and SVG rendering leads in Section 5 are explicitly marked unconfirmed for this reason.
- **The 5 Selenium `test/*.js` scripts were read, not executed**, since no browser automation driver was
  set up for this review; they describe intended behaviour for giftcards, a basic sale/receiving flow,
  and quantity handling, and should be run in any real follow up.
- **JavaScript/npm dependencies were not audited**, only PHP/Composer ones.
- **Effort estimates in Section 9 are ranges built from the size and structure measured in Section 6**,
  not from pricing a real client's actual scope; a real quote needs the real codebase (if forked or
  customized) and the real data volume.
- **The database review (Section 3) covers the schema that ships with the tag reviewed, after the one
  migration that runs on first login; it does not reflect whatever additional migrations a years old
  real production database might have accumulated.** A real engagement reads the target database's
  actual `ospos_migrations` row and schema, not the stock tag's.

---

## Sources, licence and attribution

Subject project: [opensourcepos/opensourcepos](https://github.com/opensourcepos/opensourcepos), MIT
licence, tag `3.3.9`, commit `c00ff28d10f25c2638a65cbfbbcd08b75a83c59f`. CodeIgniter framework release
history: [bcit-ci/CodeIgniter](https://github.com/bcit-ci/CodeIgniter) (tag `3.1.13`, last 3.x commit
2022-03-03). PHP support timeline: [php.net/supported-versions](https://www.php.net/supported-versions.php).
Dependency advisories: Composer's own bundled advisory database via `composer audit --locked`
(`docs/evidence/composer-audit.json`), which itself aggregates GitHub Security Advisories and FriendsOfPHP's
security advisories database.

This document quotes short code fragments and file paths from the subject project under the terms of its
MIT licence (attribution preserved above); no substantial portion of its source is reproduced here or
vendored into this repository.
