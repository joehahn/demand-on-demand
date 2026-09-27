"""
load_data.py: one-time pull of Iowa Liquor Sales (2016 onward) into a local Postgres warehouse.

Stages (run all by default, or name one):
    python load_data.py download   # yearly zips -> $DOD_DATA_DIR
    python load_data.py raw        # zips -> raw.liquor_sales (all text, dirt preserved)
    python load_data.py curate     # raw -> sales.* star schema (typed, still dirty values)
    python load_data.py ref        # ref.calendar, ref.county_demographics
    python load_data.py meta       # meta.column_notes data dictionary + COMMENT ON

Connects as dod_owner (DOD_OWNER_DSN in .env). Never prints credentials.
"""
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import holidays
import pandas as pd
import psycopg
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
DATA_DIR = Path(os.path.expanduser(os.environ.get("DOD_DATA_DIR", "~/data/demand-on-demand")))

# Iowa Data Hub dataset id for each year (from catalog.data.gov, verified 2026-09-26)
YEAR_IDS = {2016: 1253, 2017: 1254, 2018: 1255, 2019: 1256, 2020: 1257, 2021: 1258,
            2022: 1259, 2023: 1260, 2024: 1261, 2025: 1262, 2026: 1263}
URL = "https://idh-be.iowa.gov/api/v1/datasets/{id}/rows.csv"


def zip_path(year):
    return DATA_DIR / f"iowa_liquor_sales_{year}.zip"


def download():
    """Download each year's zip unless a valid copy is already on disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for year, ds_id in YEAR_IDS.items():
        path = zip_path(year)
        # the current year is still growing, so always refresh it
        if path.exists() and year != max(YEAR_IDS) and zipfile.is_zipfile(path):
            print(f"{year}: have {path.name} ({path.stat().st_size / 1e6:.0f} MB)")
            continue
        t0 = time.time()
        tmp = path.with_suffix(".part")
        with requests.get(URL.format(id=ds_id), stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        if not zipfile.is_zipfile(tmp):
            sys.exit(f"{year}: download is not a zip, aborting")
        tmp.rename(path)
        print(f"{year}: {path.stat().st_size / 1e6:.0f} MB in {time.time() - t0:.0f}s")


# ---------------------------------------------------------------- database helpers

def connect():
    """Connect as the table owner. Big session memory makes the index builds and GROUP BYs fast."""
    conn = psycopg.connect(os.environ["DOD_OWNER_DSN"], autocommit=True)
    conn.execute("SET maintenance_work_mem = '2GB'")
    conn.execute("SET work_mem = '256MB'")
    return conn


def run_sql(conn, label, sql):
    """Run one SQL statement and report how long it took."""
    t0 = time.time()
    cur = conn.execute(sql)
    rows = f", {cur.rowcount:,} rows" if cur.rowcount and cur.rowcount > 0 else ""
    print(f"  {label}: {time.time() - t0:.0f}s{rows}")


# ---------------------------------------------------------------- raw landing table

RAW_COLS = ["invoice_id", "ordered_on", "store_no", "store_name", "store_address", "store_city",
            "store_zip_code", "county_fips_code", "county_name", "category_code", "category_name",
            "vendor_number", "vendor_name", "item_no", "im_desc", "pack", "bottle_volume_ml",
            "state_bottle_cost", "state_bottle_retail", "sales_bottles", "sales_dollars",
            "sales_liters", "sales_gallons"]


def raw():
    """Land every CSV part, as text, exactly as published. Rebuilds raw.liquor_sales from scratch."""
    with connect() as conn:
        cols = ",\n  ".join(f"{c} text" for c in RAW_COLS)
        conn.execute("DROP TABLE IF EXISTS raw.liquor_sales CASCADE")
        conn.execute(f"CREATE UNLOGGED TABLE raw.liquor_sales (\n  {cols},\n"
                     "  source_file text, loaded_at timestamptz DEFAULT now())")
        for year in YEAR_IDS:
            with zipfile.ZipFile(zip_path(year)) as z:
                for part in z.namelist():
                    t0 = time.time()
                    # stamp the source file on each row via a column default, then COPY straight from the zip
                    conn.execute(f"ALTER TABLE raw.liquor_sales ALTER source_file SET DEFAULT '{part}'")
                    copy_sql = (f"COPY raw.liquor_sales ({', '.join(RAW_COLS)}) "
                                "FROM STDIN WITH (FORMAT csv, HEADER true)")
                    with conn.cursor() as cur, cur.copy(copy_sql) as copy, z.open(part) as f:
                        while chunk := f.read(1 << 22):
                            copy.write(chunk)
                    print(f"  {part}: {time.time() - t0:.0f}s")
        conn.execute("ALTER TABLE raw.liquor_sales ALTER source_file DROP DEFAULT")
        n = conn.execute("SELECT count(*) FROM raw.liquor_sales").fetchone()[0]
        print(f"  raw.liquor_sales: {n:,} rows")


# ---------------------------------------------------------------- curated star schema
# Typed and keyed like a small company's sales warehouse. Values are NOT cleaned: blanks become
# NULL and text becomes numbers/dates, nothing more. Cleaning is the agent's job, downstream.

def num(col):
    """Text -> numeric, blank -> NULL."""
    return f"NULLIF(trim({col}), '')::numeric"


CURATE_SQL = [
    ("drop old tables", """
        DROP TABLE IF EXISTS sales.invoice_line, sales.store, sales.item, sales.vendor, sales.category CASCADE"""),

    # One row per invoice line. Line-level attributes (price, pack, category) are kept as recorded
    # on that day, because items get re-categorized and re-priced over time.
    # ETL fix: the state's 2022, 2025 and 2026 exports repeat ~1.5M rows verbatim across CSV parts
    # (the portal's own 2026 row count matches the de-duplicated count), so exact duplicates are
    # dropped here. invoice_id is not unique: from 2025-09-01 it identifies a whole order.
    ("sales.invoice_line", f"""
        CREATE TABLE sales.invoice_line AS
        WITH dedup AS (SELECT DISTINCT {', '.join(RAW_COLS)} FROM raw.liquor_sales)
        SELECT row_number() OVER (ORDER BY ordered_on, invoice_id, item_no) AS line_id,
               invoice_id,
               ordered_on::date                      AS ordered_on,
               trim(store_no)                        AS store_no,
               trim(item_no)                         AS item_no,
               NULLIF(trim(vendor_number), '')       AS vendor_no,
               NULLIF(trim(category_code), '')       AS category_code,
               {num('pack')}::int                    AS pack,
               {num('bottle_volume_ml')}::int        AS bottle_volume_ml,
               {num('state_bottle_cost')}            AS state_bottle_cost,
               {num('state_bottle_retail')}          AS state_bottle_retail,
               {num('sales_bottles')}::int           AS sales_bottles,
               {num('sales_dollars')}                AS sales_dollars,
               {num('sales_liters')}                 AS sales_liters
        FROM dedup
        ORDER BY ordered_on"""),

    # Dimension tables keep each code's most recently recorded attributes (a "type 1" dimension).
    ("sales.store", """
        CREATE TABLE sales.store AS
        WITH latest AS (
            SELECT DISTINCT ON (trim(store_no)) trim(store_no) AS store_no,
                   NULLIF(trim(store_name), '') AS store_name, NULLIF(trim(store_address), '') AS address,
                   NULLIF(trim(store_city), '') AS city, NULLIF(trim(store_zip_code), '') AS zip_code,
                   NULLIF(trim(county_fips_code), '') AS county_fips, NULLIF(trim(county_name), '') AS county_name
            FROM raw.liquor_sales
            ORDER BY trim(store_no), ordered_on DESC, invoice_id DESC),
        span AS (
            SELECT store_no, min(ordered_on) AS first_order_on, max(ordered_on) AS last_order_on
            FROM sales.invoice_line GROUP BY store_no)
        SELECT latest.*, span.first_order_on, span.last_order_on
        FROM latest JOIN span USING (store_no)"""),

    ("sales.item", """
        CREATE TABLE sales.item AS
        SELECT DISTINCT ON (trim(item_no)) trim(item_no) AS item_no,
               NULLIF(trim(im_desc), '') AS item_desc,
               NULLIF(trim(vendor_number), '') AS vendor_no,
               NULLIF(trim(category_code), '') AS category_code,
               NULLIF(trim(pack), '')::int AS pack,
               NULLIF(trim(bottle_volume_ml), '')::numeric::int AS bottle_volume_ml
        FROM raw.liquor_sales
        ORDER BY trim(item_no), ordered_on DESC, invoice_id DESC"""),

    ("sales.vendor", """
        CREATE TABLE sales.vendor AS
        SELECT DISTINCT ON (trim(vendor_number)) trim(vendor_number) AS vendor_no,
               NULLIF(trim(vendor_name), '') AS vendor_name
        FROM raw.liquor_sales WHERE NULLIF(trim(vendor_number), '') IS NOT NULL
        ORDER BY trim(vendor_number), ordered_on DESC, invoice_id DESC"""),

    ("sales.category", """
        CREATE TABLE sales.category AS
        SELECT DISTINCT ON (trim(category_code)) trim(category_code) AS category_code,
               NULLIF(trim(category_name), '') AS category_name
        FROM raw.liquor_sales WHERE NULLIF(trim(category_code), '') IS NOT NULL
        ORDER BY trim(category_code), ordered_on DESC, invoice_id DESC"""),

    # lifetime stats on the item dimension, like first/last order on store: cheap lookups for search
    ("item stats", """
        ALTER TABLE sales.item ADD COLUMN first_order_on date, ADD COLUMN last_order_on date, ADD COLUMN total_bottles bigint;
        UPDATE sales.item i SET first_order_on = s.first_on, last_order_on = s.last_on, total_bottles = s.bottles
        FROM (SELECT item_no, min(ordered_on) AS first_on, max(ordered_on) AS last_on, sum(sales_bottles) AS bottles
              FROM sales.invoice_line GROUP BY 1) s
        WHERE s.item_no = i.item_no"""),

    ("keys", """
        ALTER TABLE sales.invoice_line ADD PRIMARY KEY (line_id);
        ALTER TABLE sales.store    ADD PRIMARY KEY (store_no);
        ALTER TABLE sales.item     ADD PRIMARY KEY (item_no);
        ALTER TABLE sales.vendor   ADD PRIMARY KEY (vendor_no);
        ALTER TABLE sales.category ADD PRIMARY KEY (category_code)"""),

    ("indexes", """
        CREATE INDEX ON sales.invoice_line USING brin (ordered_on);
        CREATE INDEX ON sales.invoice_line (invoice_id);
        CREATE INDEX ON sales.invoice_line (store_no, ordered_on);
        CREATE INDEX ON sales.invoice_line (item_no, ordered_on);
        CREATE INDEX ON sales.invoice_line (category_code, ordered_on);
        CREATE INDEX ON sales.invoice_line (vendor_no, ordered_on)"""),

    ("analyze", "ANALYZE sales.invoice_line, sales.store, sales.item, sales.vendor, sales.category"),
]


def curate():
    with connect() as conn:
        for label, sql in CURATE_SQL:
            run_sql(conn, label, sql)


# ---------------------------------------------------------------- reference tables

POP_URLS = [  # Census county population estimates (no API key needed)
    "https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/counties/totals/co-est2020-alldata.csv",
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv",
]
SAIPE_URL = ("https://www2.census.gov/programs-surveys/saipe/datasets/{y}/{y}-state-and-county/"
             "est{yy}all.txt")  # Census small-area median household income, one file per year
FIRST_YEAR, LAST_YEAR = min(YEAR_IDS), max(YEAR_IDS)


def county_population():
    """Iowa (state FIPS 19) county population, one row per county-year. Later vintages win."""
    rows = {}
    for url in POP_URLS:
        df = pd.read_csv(io.BytesIO(requests.get(url, timeout=120).content), encoding="latin-1", dtype={"STATE": str, "COUNTY": str})
        df = df[(df.STATE == "19") & (df.COUNTY != "000")]
        for col in df.columns:
            if col.startswith("POPESTIMATE") and col[11:].isdigit():
                year = int(col[11:])
                if FIRST_YEAR <= year <= LAST_YEAR:
                    for fips, pop in zip("19" + df.COUNTY, df[col]):
                        rows[(fips, year)] = int(pop)
    return pd.DataFrame([(f, y, p) for (f, y), p in rows.items()], columns=["county_fips", "year", "population"])


def county_income():
    """Iowa county median household income (SAIPE), one row per county-year, where published."""
    rows = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        r = requests.get(SAIPE_URL.format(y=year, yy=str(year)[2:]), timeout=120)
        if r.status_code != 200:
            print(f"  SAIPE {year}: not published yet")
            continue
        for line in r.content.decode("latin-1").splitlines():
            tok = line.split()
            # tokens: state, county, 18 poverty numbers, then median income estimate
            if len(tok) > 20 and tok[0] == "19" and tok[1] != "0":
                rows.append((f"19{int(tok[1]):03d}", year, int(tok[20])))
    return pd.DataFrame(rows, columns=["county_fips", "year", "median_household_income"])


def calendar():
    """One row per day with the calendar facts that drive liquor orders."""
    us = holidays.US(years=range(FIRST_YEAR, LAST_YEAR + 2))
    days = pd.date_range(f"{FIRST_YEAR}-01-01", f"{LAST_YEAR + 1}-12-31", freq="D")
    return pd.DataFrame({
        "cal_date": days.date,
        "year": days.year, "quarter": days.quarter, "month": days.month,
        "iso_week": days.isocalendar().week.to_numpy(), "day_of_week": days.dayofweek + 1,  # 1 = Monday
        "is_weekend": days.dayofweek >= 5,
        "holiday_name": [us.get(d) for d in days.date],
        "is_business_day": [(d.dayofweek < 5) and (d.date() not in us) for d in days],
    })


def load_frame(conn, df, table, ddl):
    """Replace a small table with the contents of a DataFrame."""
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(f"CREATE TABLE {table} ({ddl})")
    with conn.cursor() as cur, cur.copy(f"COPY {table} FROM STDIN") as copy:
        for row in df.itertuples(index=False):
            copy.write_row([None if pd.isna(v) else v for v in row])
    print(f"  {table}: {len(df):,} rows")


def ref():
    with connect() as conn:
        load_frame(conn, calendar(), "ref.calendar",
                   "cal_date date PRIMARY KEY, year int, quarter int, month int, iso_week int, "
                   "day_of_week int, is_weekend boolean, holiday_name text, is_business_day boolean")
        load_frame(conn, county_population(), "ref.county_population",
                   "county_fips text, year int, population int, PRIMARY KEY (county_fips, year)")
        load_frame(conn, county_income(), "ref.county_income",
                   "county_fips text, year int, median_household_income int, PRIMARY KEY (county_fips, year)")


# ---------------------------------------------------------------- clean: fix the known issues once, in the warehouse
# Each issue documented by explore_data.py is fixed here, so every forecast reads clean data and no forecast has
# to know about the problems. raw.liquor_sales stays untouched; docs/data_fixes.html shows before and after.

def item_families(conn):
    """Renumbered items -> product families. A successor has the same description and size, and its first order
    falls within -45..+90 days of its predecessor's last order. Chains collapse to the most recent item."""
    pairs = conn.execute("""
        SELECT o.item_no, n.item_no FROM sales.item o JOIN sales.item n
          ON n.item_desc = o.item_desc AND n.bottle_volume_ml = o.bottle_volume_ml AND n.item_no <> o.item_no
         AND n.first_order_on BETWEEN o.last_order_on - 45 AND o.last_order_on + 90
         AND n.last_order_on > o.last_order_on AND n.first_order_on > o.first_order_on
        WHERE o.last_order_on < (SELECT max(last_order_on) - 60 FROM sales.item)""").fetchall()
    parent = {}

    def root(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    for old, new in pairs:
        parent[root(old)] = root(new)
    members = {}
    for item in {i for pair in pairs for i in pair}:
        members.setdefault(root(item), set()).add(item)
    last = dict(conn.execute("SELECT item_no, last_order_on FROM sales.item").fetchall())
    rows = []
    for group in members.values():
        head = max(group, key=lambda i: (last[i], i))   # a family is named after its most recent item
        rows += [(i, head) for i in sorted(group) if i != head]
    return rows


CITY_ABBREVIATIONS = {"MT": "MOUNT", "ST": "SAINT", "FT": "FORT"}


def city_crosswalk(conn):
    """Spelling variants of one city (MT/MOUNT, CLEARLAKE/CLEAR LAKE, ARNOLD'S/ARNOLDS) -> one name: abbreviations
    spelled out, then the spaced form (as in official names: Lone Tree, Le Claire), then no apostrophe, then the
    spelling used by the most stores."""
    stores = conn.execute("SELECT city_recorded, county_fips, count(*) FROM sales.store "
                          "WHERE city_recorded IS NOT NULL GROUP BY 1, 2").fetchall()

    def key(city):
        words = [CITY_ABBREVIATIONS.get(w, w) for w in city.upper().split()]
        return "".join(ch for ch in "".join(words) if ch.isalpha())
    groups = {}
    for city, fips, n in stores:
        groups.setdefault((key(city), fips), []).append((city, n))
    rows = []
    for variants in groups.values():
        if len(variants) < 2:
            continue
        spelled = [v for v in variants if not any(w in CITY_ABBREVIATIONS for w in v[0].split())]
        best = max(spelled or variants, key=lambda v: (" " in v[0], "'" not in v[0], v[1]))[0]
        rows += [(c, best) for c, _ in variants if c != best]
    return rows


def copy_rows(conn, table, ddl, rows):
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(f"CREATE TABLE {table} ({ddl})")
    with conn.cursor() as cur, cur.copy(f"COPY {table} FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def clean():
    with connect() as conn:
        fixes = []
        dupes = conn.execute("SELECT (SELECT count(*) FROM raw.liquor_sales) - "
                             "(SELECT count(*) FROM sales.invoice_line)").fetchone()[0]
        fixes.append(("export_duplicates", "Rows repeated verbatim across CSV parts of the 2022, 2025 and 2026 "
                      "exports; exact duplicates removed when sales.invoice_line was built.", dupes))

        n = conn.execute("DELETE FROM sales.invoice_line WHERE sales_bottles <= 0 OR sales_dollars <= 0").rowcount
        fixes.append(("zero_value_lines", "Order lines with zero bottles or zero dollars (likely cancelled) removed.", n))

        fam = item_families(conn)
        copy_rows(conn, "sales.item_family", "item_no text PRIMARY KEY, family_item_no text NOT NULL", fam)
        conn.execute("ALTER TABLE sales.item DROP COLUMN IF EXISTS family_item_no")
        conn.execute("ALTER TABLE sales.item ADD COLUMN family_item_no text")
        conn.execute("UPDATE sales.item SET family_item_no = item_no")
        conn.execute("UPDATE sales.item i SET family_item_no = f.family_item_no FROM sales.item_family f "
                     "WHERE f.item_no = i.item_no")
        fixes.append(("item_renumbering", "Renumbered items joined into product families (sales.item_family, "
                      "item.family_item_no), so a product's history continues across a new item number.", len(fam)))

        conn.execute("DROP TABLE IF EXISTS sales.category_crosswalk")
        conn.execute("""
            CREATE TABLE sales.category_crosswalk AS
            WITH use AS (SELECT category_code, max(last_order_on) AS last_on, sum(total_bottles) AS bottles
                         FROM sales.item WHERE category_code IS NOT NULL GROUP BY 1),
                 named AS (SELECT c.category_code, c.category_name, u.last_on, u.bottles
                           FROM sales.category c LEFT JOIN use u USING (category_code)),
                 live AS (SELECT DISTINCT ON (category_name) category_name, category_code AS current_code
                          FROM named ORDER BY category_name, last_on DESC NULLS LAST, bottles DESC NULLS LAST)
            SELECT n.category_code, l.current_code FROM named n JOIN live l USING (category_name)
            WHERE n.category_code <> l.current_code""")
        n_codes = conn.execute("SELECT count(*) FROM sales.category_crosswalk").fetchone()[0]
        conn.execute("ALTER TABLE sales.item DROP COLUMN IF EXISTS category_current")
        conn.execute("ALTER TABLE sales.item ADD COLUMN category_current text")
        conn.execute("UPDATE sales.item SET category_current = category_code")
        conn.execute("UPDATE sales.item i SET category_current = x.current_code FROM sales.category_crosswalk x "
                     "WHERE x.category_code = i.category_code")
        restated = conn.execute("SELECT count(*) FROM sales.invoice_line l JOIN sales.item i USING (item_no) "
                                "WHERE l.category_code IS DISTINCT FROM i.category_current").fetchone()[0]
        fixes.append(("category_taxonomy", "History restated in today's categories: every line takes its item's "
                      f"current category (item.category_current), and {n_codes} retired codes map to the live code with "
                      "the same name (sales.category_crosswalk). Fixes the 2016-08-29 reassignment and the 2022 "
                      "Cocktails/RTD recode.", restated))

        # keep the source spelling first, so re-running this stage always starts from what was recorded
        conn.execute("ALTER TABLE sales.store ADD COLUMN IF NOT EXISTS city_recorded text")
        conn.execute("UPDATE sales.store SET city_recorded = city WHERE city_recorded IS NULL")
        xwalk = city_crosswalk(conn)
        copy_rows(conn, "sales.city_crosswalk", "city_recorded text PRIMARY KEY, city text NOT NULL", xwalk)
        conn.execute("UPDATE sales.store SET city = city_recorded")
        n = conn.execute("UPDATE sales.store s SET city = x.city FROM sales.city_crosswalk x "
                         "WHERE s.city_recorded = x.city_recorded").rowcount
        fixes.append(("city_spelling", f"{len(xwalk)} city spellings mapped to one name each (sales.city_crosswalk; "
                      "the original stays in store.city_recorded).", n))

        for table, col in (("ref.county_population", "population"), ("ref.county_income", "median_household_income")):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS carried_forward boolean DEFAULT false")
            n = conn.execute(f"""
                INSERT INTO {table} (county_fips, year, {col}, carried_forward)
                SELECT l.county_fips, y.year, l.{col}, true
                FROM (SELECT DISTINCT ON (county_fips) county_fips, year, {col} FROM {table}
                      ORDER BY county_fips, year DESC) l
                CROSS JOIN generate_series({FIRST_YEAR}, {LAST_YEAR + 1}) AS y(year)
                WHERE y.year > l.year
                ON CONFLICT (county_fips, year) DO NOTHING""").rowcount
            fixes.append((f"census_lag_{col}", f"{table}: the latest published year is carried forward to "
                          f"{LAST_YEAR + 1} and flagged carried_forward.", n))

        fixes += [
            ("invoice_id_meaning", "invoice_id changed from one id per line to one id per order on 2025-09-01; "
             "lines are keyed by the new line_id instead.", 0),
            ("missing_prices", "state_bottle_cost and state_bottle_retail are blank before 2025-09; unit price is "
             "sales_dollars / sales_bottles.", 0),
            ("large_volume_lines", "Lines of 6 liters or more were checked: pallet shippers and whole-cask purchases, "
             "genuine volume, kept as recorded.", 0),
        ]
        copy_rows(conn, "meta.data_fixes", "fix_id text PRIMARY KEY, description text, rows_affected bigint", fixes)
        conn.execute("DROP TABLE IF EXISTS meta.known_issues")   # superseded: the fixes now live in the warehouse
        conn.execute("ANALYZE sales.invoice_line, sales.item, sales.store")
        for fix_id, _, n in fixes:
            print(f"  {fix_id}: {n:,}")


# ---------------------------------------------------------------- data dictionary

TABLE_NOTES = {
    "sales.invoice_line": "One row per product line on a retailer's wholesale liquor order from the state (Iowa Class E licensees), 2016 onward, cleaned (see meta.data_fixes). Price, pack and category_code are as recorded on the order date.",
    "sales.store": "Licensed retail stores that ordered liquor. Attributes are the most recently recorded values.",
    "sales.item": "Liquor products. Attributes are the most recently recorded values. Use family_item_no for a product across renumberings and category_current for its category.",
    "sales.item_family": "Renumbered items: each old item_no and the current item_no of its product family.",
    "sales.category_crosswalk": "Retired category codes and the live code with the same name.",
    "sales.city_crosswalk": "City spelling variants and the one name used in store.city.",
    "meta.data_fixes": "Every data-quality fix applied to the warehouse, with the number of rows affected.",
    "sales.vendor": "Liquor vendors / distillers / importers.",
    "sales.category": "Product categories. Name is the most recently recorded name for the code.",
    "ref.calendar": "One row per calendar day, with US federal holidays and business days.",
    "ref.county_population": "Census Bureau annual population estimate per Iowa county (July 1 of each year).",
    "ref.county_income": "Census Bureau SAIPE median household income per Iowa county per year.",
    "meta.column_notes": "Data dictionary: one row per table column, with a description.",
}

COLUMN_NOTES = {
    "sales.invoice_line": {
        "line_id": "Unique id of the order line.",
        "invoice_id": "Id of the order (invoice); one order can have many lines.",
        "ordered_on": "Date the retailer placed the order with the state.",
        "store_no": "Ordering store; joins sales.store.",
        "item_no": "Product ordered; joins sales.item.",
        "vendor_no": "Vendor of the product; joins sales.vendor.",
        "category_code": "Product category on the order date; joins sales.category.",
        "pack": "Bottles per case.",
        "bottle_volume_ml": "Volume of one bottle in milliliters.",
        "state_bottle_cost": "Price the state paid the vendor per bottle, in dollars.",
        "state_bottle_retail": "Price the retailer paid the state per bottle, in dollars.",
        "sales_bottles": "Number of bottles ordered.",
        "sales_dollars": "Total order line value in dollars.",
        "sales_liters": "Total liters ordered.",
    },
    "sales.store": {
        "store_no": "Store number.", "store_name": "Store name.", "address": "Street address.",
        "city": "City, one spelling per city.", "city_recorded": "City as recorded by the source.", "zip_code": "ZIP code.", "county_fips": "5-digit county FIPS code; joins ref.county_population and ref.county_income.",
        "county_name": "County name.", "first_order_on": "Date of the store's first order.", "last_order_on": "Date of the store's latest order.",
    },
    "sales.item": {
        "item_no": "Item number.", "item_desc": "Product description.", "vendor_no": "Vendor; joins sales.vendor.",
        "category_code": "Category; joins sales.category.", "pack": "Bottles per case.", "bottle_volume_ml": "Bottle volume in milliliters.",
        "first_order_on": "Date of the item's first order.", "last_order_on": "Date of the item's latest order.",
        "total_bottles": "Bottles ordered over the item's lifetime.",
        "family_item_no": "Current item number of this product's family; equals item_no unless the item was renumbered.",
        "category_current": "The item's category in today's taxonomy; use it for category-level analysis over any period.",
    },
    "sales.vendor": {"vendor_no": "Vendor number.", "vendor_name": "Vendor name."},
    "sales.category": {"category_code": "Category code.", "category_name": "Category name."},
    "ref.calendar": {
        "cal_date": "Calendar date.", "year": "Year.", "quarter": "Quarter 1-4.", "month": "Month 1-12.",
        "iso_week": "ISO week number.", "day_of_week": "1 = Monday ... 7 = Sunday.", "is_weekend": "Saturday or Sunday.",
        "holiday_name": "US federal holiday name, else NULL.", "is_business_day": "Weekday that is not a federal holiday.",
    },
    "ref.county_population": {"county_fips": "5-digit county FIPS code.", "year": "Year.", "population": "Resident population estimate.",
                              "carried_forward": "True when the latest published year was carried forward."},
    "ref.county_income": {"county_fips": "5-digit county FIPS code.", "year": "Year.", "median_household_income": "Median household income in dollars.",
                          "carried_forward": "True when the latest published year was carried forward."},
}


def meta():
    with connect() as conn:
        rows = []
        for table, note in TABLE_NOTES.items():
            rows.append((table.split(".")[0], table.split(".")[1], None, note))
        for table, cols in COLUMN_NOTES.items():
            for col, note in cols.items():
                rows.append((table.split(".")[0], table.split(".")[1], col, note))
        load_frame(conn, pd.DataFrame(rows), "meta.column_notes",
                   "schema_name text, table_name text, column_name text, description text")
        # the same text as native Postgres comments, so any SQL client shows it
        quote = lambda s: "'" + s.replace("'", "''") + "'"  # COMMENT does not accept bind parameters
        for table, note in TABLE_NOTES.items():
            conn.execute(f"COMMENT ON TABLE {table} IS {quote(note)}")
        for table, cols in COLUMN_NOTES.items():
            for col, note in cols.items():
                conn.execute(f"COMMENT ON COLUMN {table}.{col} IS {quote(note)}")
        print("  comments written")


STAGES = {"download": download, "raw": raw, "curate": curate, "ref": ref, "clean": clean, "meta": meta}

if __name__ == "__main__":
    names = sys.argv[1:] or list(STAGES)
    for name in names:
        print(f"== {name}")
        STAGES[name]()
