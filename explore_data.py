"""
explore_data.py: profile the Iowa liquor warehouse and publish docs/data_exploration.html.

The page documents two things: what the demand looks like (trend, seasonality, geography),
and the data-quality traps an AI agent must handle before any forecast is trustworthy.

    python explore_data.py            # reuse cached query results in cache/explore/
    python explore_data.py --fresh    # re-run every query (~5 minutes)

Connects as dod_owner (reads raw.* to show what the loader fixed). Never prints credentials.
"""
import html
from decimal import Decimal
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import psycopg
from dotenv import load_dotenv

from dod.viz import AQUA, BLUE, ORANGE, SEQ_BLUE, Plots, line, page, style, table

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CACHE = ROOT / "cache" / "explore"
OUT = ROOT / "docs" / "data_exploration.html"

# ---------------------------------------------------------------- queries
# Each query's result is cached as parquet so re-styling the page doesn't rescan 26M rows.

QUERIES = {
    "monthly": """
        SELECT date_trunc('month', ordered_on)::date AS month,
               sum(sales_dollars) AS dollars, sum(sales_bottles) AS bottles, sum(sales_liters) AS liters,
               count(*) AS lines, count(DISTINCT store_no) AS stores, count(DISTINCT item_no) AS items
        FROM sales.invoice_line GROUP BY 1 ORDER BY 1""",

    # published rows vs de-duplicated rows, per month: the state's export bug
    "dupes": """
        SELECT r.month, r.published, c.distinct_rows FROM
          (SELECT date_trunc('month', ordered_on::date)::date AS month, count(*) AS published
           FROM raw.liquor_sales GROUP BY 1) r
        JOIN
          (SELECT date_trunc('month', ordered_on)::date AS month, count(*) AS distinct_rows
           FROM sales.invoice_line GROUP BY 1) c USING (month)
        ORDER BY 1""",

    # share of blank values per column per year, as published
    "blanks": """
        SELECT left(ordered_on, 4)::int AS year,
               avg((NULLIF(trim(store_address), '') IS NULL)::int)       AS store_address,
               avg((NULLIF(trim(county_name), '') IS NULL)::int)         AS county_name,
               avg((NULLIF(trim(category_name), '') IS NULL)::int)       AS category_name,
               avg((NULLIF(trim(vendor_name), '') IS NULL)::int)         AS vendor_name,
               avg((NULLIF(trim(state_bottle_cost), '') IS NULL)::int)   AS state_bottle_cost,
               avg((NULLIF(trim(state_bottle_retail), '') IS NULL)::int) AS state_bottle_retail
        FROM raw.liquor_sales GROUP BY 1 ORDER BY 1""",

    # category codes whose name changed: a naive join to sales.category mislabels history
    "category_reuse": """
        SELECT category_code, category_name,
               min(ordered_on) AS first_seen, max(ordered_on) AS last_seen, count(*) AS lines
        FROM raw.liquor_sales
        WHERE category_code IN (SELECT category_code FROM raw.liquor_sales WHERE category_code <> ''
                                GROUP BY 1 HAVING count(DISTINCT category_name) > 1)
        GROUP BY 1, 2 ORDER BY 1, 3""",

    "categories_per_year": """
        SELECT left(ordered_on, 4)::int AS year,
               count(DISTINCT category_name) AS category_names, count(DISTINCT category_code) AS category_codes
        FROM raw.liquor_sales WHERE category_code <> '' GROUP BY 1 ORDER BY 1""",

    # one real product, many item numbers: what "Tito's" has to resolve to
    "titos": """
        SELECT l.item_no, i.item_desc, i.bottle_volume_ml, count(*) AS lines, sum(l.sales_bottles) AS bottles,
               min(l.ordered_on) AS first_order, max(l.ordered_on) AS last_order
        FROM sales.invoice_line l JOIN sales.item i USING (item_no)
        WHERE i.item_desc ILIKE '%tito%' GROUP BY 1, 2, 3 ORDER BY bottles DESC""",

    # city spellings that differ only by abbreviation
    "city_variants": """
        SELECT x.city_recorded AS spelling, x.city AS same_city_as, count(DISTINCT s.store_no) AS stores
        FROM sales.city_crosswalk x JOIN sales.store s ON s.city_recorded = x.city_recorded GROUP BY 1, 2 ORDER BY 2""",

    # stores whose recorded attributes change over time
    "store_drift": """
        SELECT count(*) AS stores,
               count(*) FILTER (WHERE n_name > 1)   AS changed_name,
               count(*) FILTER (WHERE n_city > 1)   AS changed_city,
               count(*) FILTER (WHERE n_county > 1) AS changed_county,
               count(*) FILTER (WHERE n_addr > 1)   AS changed_address
        FROM (SELECT store_no, count(DISTINCT store_name) n_name, count(DISTINCT store_city) n_city,
                     count(DISTINCT county_name) n_county, count(DISTINCT store_address) n_addr
              FROM raw.liquor_sales GROUP BY 1) s""",

    "bottle_sizes": """
        SELECT bottle_volume_ml, count(*) AS lines FROM sales.invoice_line GROUP BY 1 ORDER BY 1""",

    "suspect_lines": """
        SELECT left(ordered_on, 4)::int AS year,
               count(*) FILTER (WHERE NULLIF(trim(sales_dollars), '')::numeric <= 0) AS zero_dollar,
               count(*) FILTER (WHERE NULLIF(trim(sales_bottles), '')::numeric <= 0) AS zero_bottles,
               count(*) FILTER (WHERE NULLIF(trim(bottle_volume_ml), '')::numeric >= 10000) AS huge_bottles
        FROM (SELECT DISTINCT invoice_id, ordered_on, store_no, store_name, store_address, store_city, store_zip_code, county_fips_code, county_name, category_code, category_name, vendor_number, vendor_name, item_no, im_desc, pack, bottle_volume_ml, state_bottle_cost, state_bottle_retail, sales_bottles, sales_dollars, sales_liters, sales_gallons FROM raw.liquor_sales) r GROUP BY 1 ORDER BY 1""",

    # the Cocktails/RTD category moved to a new code in July 2022
    "rtd_codes": """
        SELECT date_trunc('month', ordered_on)::date AS month, category_code, sum(sales_bottles) AS bottles
        FROM sales.invoice_line WHERE category_code IN ('1071100', '1071000', '1070000') GROUP BY 1, 2 ORDER BY 1, 2""",

    # renumbered items: same product, new item number (detected by the loader's clean stage)
    "renumbered": """
        SELECT f.item_no AS old_item, f.family_item_no AS new_item, o.item_desc, o.bottle_volume_ml AS ml,
               o.last_order_on AS old_last_order, n.first_order_on AS new_first_order, o.total_bottles AS old_bottles
        FROM sales.item_family f JOIN sales.item o ON o.item_no = f.item_no JOIN sales.item n ON n.item_no = f.family_item_no
        ORDER BY o.total_bottles DESC""",

    # order ids changed meaning on 2025-09-01
    "lines_per_invoice": """
        SELECT date_trunc('month', ordered_on)::date AS month,
               count(*)::float / count(DISTINCT invoice_id) AS lines_per_invoice
        FROM sales.invoice_line WHERE ordered_on >= '2024-01-01' GROUP BY 1 ORDER BY 1""",

    "counties": """
        WITH c AS (SELECT s.county_fips, max(s.county_name) AS county, sum(l.sales_dollars) AS dollars
                   FROM sales.invoice_line l JOIN sales.store s USING (store_no)
                   WHERE l.ordered_on >= '2025-01-01' AND l.ordered_on < '2026-01-01' GROUP BY 1)
        SELECT c.county_fips, c.county, c.dollars, p.population, c.dollars / p.population AS dollars_per_person
        FROM c LEFT JOIN ref.county_population p ON p.county_fips = c.county_fips AND p.year = 2025
        ORDER BY c.dollars DESC""",

    "store_lifespans": """
        SELECT date_trunc('month', first_order_on)::date AS month, count(*) AS opened
        FROM sales.store GROUP BY 1 ORDER BY 1""",

    "row_counts": """
        SELECT 'raw.liquor_sales' AS tbl, count(*) AS n FROM raw.liquor_sales
        UNION ALL SELECT 'sales.invoice_line', count(*) FROM sales.invoice_line
        UNION ALL SELECT 'sales.store', count(*) FROM sales.store
        UNION ALL SELECT 'sales.item', count(*) FROM sales.item
        UNION ALL SELECT 'sales.vendor', count(*) FROM sales.vendor
        UNION ALL SELECT 'sales.category', count(*) FROM sales.category
        UNION ALL SELECT 'stores with no county', count(*) FROM sales.store WHERE county_fips IS NULL""",
}


def floats(df):
    """Postgres numeric arrives as Python Decimal; convert those columns to float for pandas/plotly."""
    for c in df.columns:
        first = df[c].dropna().head(1)
        if len(first) and isinstance(first.iloc[0], Decimal):
            df[c] = df[c].astype(float)
    return df


def load_all(fresh):
    """Run (or reuse) every query; return {name: DataFrame}."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    conn = None
    for name, sql in QUERIES.items():
        path = CACHE / f"{name}.parquet"
        if path.exists() and not fresh:
            out[name] = floats(pd.read_parquet(path))
            continue
        if conn is None:
            conn = psycopg.connect(os.environ["DOD_OWNER_DSN"])
            conn.execute("SET work_mem = '1GB'")
        print(f"  querying {name}")
        cur = conn.execute(sql)
        df = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
        df.to_parquet(path)
        out[name] = floats(df)
    if conn is not None:
        conn.close()
    return out


# ---------------------------------------------------------------- figures

def fig_demand(d):
    m = d["monthly"]  # the 2026 file ends on a month boundary (Aug 31), so every month is complete
    figs = []
    for col, label, fmt in [("dollars", "Sales dollars per month", "$,.3s"),
                            ("bottles", "Bottles per month", ",.3s"),
                            ("liters", "Liters per month", ",.3s")]:
        f = go.Figure(line(m.month, m[col], label, BLUE))
        f.update_traces(hovertemplate="%{x|%b %Y}: %{y:" + fmt + "}<extra></extra>")
        figs.append(style(f, label, height=260))
    return figs


def fig_dupes(d):
    x = d["dupes"]
    f = go.Figure([line(x.month, x.published, "Rows as published", ORANGE),
                   line(x.month, x.distinct_rows, "Distinct rows (loaded)", BLUE)])
    f.update_traces(hovertemplate="%{y:,.0f}")
    return style(f, "The state's export repeats rows: published vs distinct lines per month", "lines", legend=True)


def fig_blanks(d):
    b = d["blanks"].set_index("year")
    cols = list(b.columns)
    f = go.Figure(go.Heatmap(
        z=(b[cols].T.values * 100), x=b.index, y=cols, colorscale=[[i / 6, c] for i, c in enumerate(SEQ_BLUE)],
        zmin=0, zmax=100, xgap=2, ygap=2, colorbar=dict(title="% blank", ticksuffix="%"),
        texttemplate="%{z:.1f}%", textfont=dict(size=11),
        hovertemplate="%{y}, %{x}: %{z:.1f}% blank<extra></extra>"))
    f.update_xaxes(dtick=1)
    return style(f, "Share of blank values by column and year (as published)", height=320).update_layout(hovermode="closest")


def fig_categories(d):
    c = d["categories_per_year"]
    f = go.Figure([line(c.year, c.category_names, "Distinct category names", BLUE),
                   line(c.year, c.category_codes, "Distinct category codes", ORANGE, dash="dot")])
    f.update_traces(mode="lines+markers", marker=dict(size=8))
    f.update_xaxes(dtick=1)
    return style(f, "The product taxonomy was reorganized", "count", legend=True)


def fig_rtd(d):
    r = d["rtd_codes"].pivot_table(index="month", columns="category_code", values="bottles", aggfunc="sum")
    names = {"1071100": "code 1071100", "1071000": "code 1071000", "1070000": "code 1070000"}
    f = go.Figure([line(r.index, r[c], names[c], col) for c, col in zip(["1071100", "1071000", "1070000"], [BLUE, ORANGE, AQUA])
                   if c in r])
    f.update_traces(hovertemplate="%{y:,.0f}")
    return style(f, "Cocktails/RTD bottles per month by recorded category code", "bottles", legend=True)


def fig_lines_per_invoice(d):
    x = d["lines_per_invoice"]
    f = go.Figure(line(x.month, x.lines_per_invoice, "Lines per invoice_id", BLUE))
    f.update_traces(mode="lines+markers", marker=dict(size=8), hovertemplate="%{x|%b %Y}: %{y:.1f}<extra></extra>")
    return style(f, "invoice_id changed meaning on 2025-09-01 (line id became order id)", "lines per id")


def fig_bottle_sizes(d):
    b = d["bottle_sizes"].dropna()
    top = b.nlargest(15, "lines").sort_values("bottle_volume_ml")
    f = go.Figure(go.Bar(x=top.bottle_volume_ml.astype(int).astype(str) + " ml", y=top.lines, marker_color=BLUE,
                         hovertemplate="%{x}: %{y:,} lines<extra></extra>"))
    f.update_xaxes(type="category")
    return style(f, "The 15 most common bottle sizes", "lines", height=320).update_layout(hovermode="closest")


def fig_counties(d):
    c = d["counties"].dropna(subset=["population"]).sort_values("dollars_per_person", ascending=False).head(25)
    f = go.Figure(go.Bar(x=c.county, y=c.dollars_per_person, marker_color=BLUE,
                         customdata=c[["dollars", "population"]],
                         hovertemplate="%{x}: $%{y:,.0f} per person<br>$%{customdata[0]:,.0f} total, "
                                       "pop %{customdata[1]:,}<extra></extra>"))
    f.update_xaxes(tickangle=-60)
    return style(f, "2025 liquor sales per resident, top 25 counties (joins ref.county_population)",
                 "$ per person", height=380).update_layout(hovermode="closest")


def fig_store_openings(d):
    s = d["store_lifespans"]
    s = s[s.month > s.month.min()]  # the first month is "already open in 2016", not an opening
    f = go.Figure(go.Bar(x=s.month, y=s.opened, marker_color=BLUE,
                         hovertemplate="%{x|%b %Y}: %{y} stores first ordered<extra></extra>"))
    return style(f, "Stores placing their first order each month: series start and stop mid-history",
                 "stores").update_layout(hovermode="closest")


# ---------------------------------------------------------------- page



def build_page(d):
    rc = dict(zip(d["row_counts"].tbl, d["row_counts"].n))
    m = d["monthly"]
    sd = d["store_drift"].iloc[0]
    dup_rows = rc["raw.liquor_sales"] - rc["sales.invoice_line"]

    plot = Plots()  # plotly.js loaded once, from the CDN

    tiles = [
        (f"{rc['sales.invoice_line'] / 1e6:.1f}M", "order lines, 2016 to Aug 2026"),
        (f"${m.dollars.sum() / 1e9:.2f}B", "wholesale sales"),
        (f"{rc['sales.store']:,}", "stores"),
        (f"{rc['sales.item']:,}", "products"),
        (f"{dup_rows / 1e6:.2f}M", "duplicate rows removed"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in tiles)

    cat = d["category_reuse"].copy()
    for c in ("first_seen", "last_seen"):
        cat[c] = cat[c].astype(str)

    titos = d["titos"].copy()
    for c in ("first_order", "last_order"):
        titos[c] = titos[c].astype(str)

    sus = d["suspect_lines"]
    bs = d["bottle_sizes"].dropna()
    top15 = bs.nlargest(15, "lines").lines.sum()
    comma = lambda v: f"{int(v):,}"

    body = f"""
<h1>Iowa liquor sales: what the data looks like</h1>
<p>Every wholesale liquor order placed by an Iowa retailer since 2016, loaded into a local Postgres
warehouse. This page is the first step of <a href="https://github.com/joehahn/demand-on-demand">demand-on-demand</a>:
before an AI agent can answer "forecast Tito's in Polk County for the next 5 months," someone has to
know what traps are in the data. These are the ones we found; <a href="data_fixes.html">the data fixes page</a> shows
how each one was fixed in the warehouse, once, so no forecast has to deal with it.</p>
<div class="tiles">{tiles_html}</div>

<h2>1. Demand: trend and seasonality</h2>
<p>Strong December peaks every year, a step up during 2020, and a plateau since 2023. This is the
signal the forecaster has to learn.</p>
{"".join(plot(f) for f in fig_demand(d))}

<h2>2. The state's own export duplicates rows</h2>
<p>The 2022, 2025 and 2026 downloads repeat {dup_rows:,} rows verbatim across CSV parts. Left in, 2022
sales would be inflated by roughly 23%. The portal's own 2026 row count matches the distinct count, so the
loader drops exact duplicates. This was the first bug, and it was upstream of us.</p>
{plot(fig_dupes(d))}

<h2>3. Missing values move around over time</h2>
<p>Bottle cost and retail price are blank on every line from 2016 through 2024 and are only partly filled
after that, so any price feature has to be derived as dollars per bottle. County and address are blank on
a few percent of early lines.</p>
{plot(fig_blanks(d))}

<h2>4. Category codes were reused for different categories</h2>
<p>At the end of August 2016 the state reorganized its product taxonomy: about 100 category names became
about 48, and many codes were shifted to mean something else. Code 1011400 meant "Bottled in Bond Bourbon"
until 2016-08-25 and "Tennessee Whiskies" after. In July 2025 several names were shortened again. A naive
join of sales to the category table labels old sales with today's name, so an agent asked for "Tennessee
whiskey since 2016" has to notice this. The first 24 reassigned codes:</p>
{plot(fig_categories(d))}
{table(cat.head(24), {"lines": comma})}

<h2>4b. A category that looks discontinued was recoded</h2>
<p>COCKTAILS/RTD stops dead under code 1071100 on 2022-07-15 and restarts three days later under code 1071000,
same name, same products. A forecast of "ready-to-drink cocktails" built on either code alone is wrong.</p>
{plot(fig_rtd(d))}

<h2>5. One product, many item numbers</h2>
<p>"Tito's" is not one row. It is several item numbers across bottle sizes and packs, and the 50 ml mini was
renumbered in July 2020 (38180 to 38194, with a temporary 938180 in between). Across the whole catalog,
{len(d["renumbered"])} items were renumbered like this, carrying {d["renumbered"].old_bottles.sum() / 1e6:.1f}M bottles of
history. The largest:</p>
{table(titos, {"lines": comma, "bottles": comma})}
{table(d["renumbered"].head(12).astype({"old_last_order": str, "new_first_order": str}), {"old_bottles": comma})}

<h2>6. Stores drift, open and close</h2>
<p>Of {int(sd.stores):,} stores, {int(sd.changed_name):,} changed recorded name, {int(sd.changed_address):,}
changed address, {int(sd.changed_city):,} changed city and {int(sd.changed_county):,} changed county over
time. {rc['stores with no county']} stores have no county at all. City spellings are not standardized either; these
{len(d["city_variants"])} spellings each name a city also spelled another way:</p>
{table(d["city_variants"])}
{plot(fig_store_openings(d))}

<h2>7. Outliers and odd lines</h2>
<p>{len(bs):,} distinct bottle sizes appear, but the 15 most common cover {top15 / bs.lines.sum():.1%} of lines.
The tail runs from {int(bs.bottle_volume_ml.min())} ml to {int(bs.bottle_volume_ml.max()):,} ml.</p>
{plot(fig_bottle_sizes(d))}
{table(sus, {"zero_dollar": comma, "zero_bottles": comma, "huge_bottles": comma})}
<p class="note">Since 2022, a few thousand lines a year have zero bottles and zero dollars (likely cancelled
lines). huge_bottles = lines with a bottle volume of 10 liters or more.</p>

<h2>8. invoice_id changed meaning</h2>
<p>Until August 2025 each order line had its own invoice_id. From September 2025 one id covers the whole
order, and at the same time bottle prices start being filled in: signs that the state switched source
systems. Anything that counts "orders" by invoice_id breaks across that date, so the loader keys lines on a
new line_id.</p>
{plot(fig_lines_per_invoice(d))}

<h2>9. Geography: joins to Census reference data</h2>
{plot(fig_counties(d))}

<footer>
Data: <a href="https://catalog.data.gov/dataset/iowa-liquor-sales">Iowa Liquor Sales</a>, State of Iowa,
Alcohol Operations Bureau, via the Iowa Data Hub, licensed
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Modified: exact duplicate rows removed,
values typed, aggregated. County population and income: U.S. Census Bureau (Population Estimates, SAIPE).
Not endorsed by the State of Iowa.<br>
Built by Joseph M. Hahn, Ph.D., <a href="https://jmh-datasciences.com">JMH DataSciences</a>, with
<a href="https://claude.com/claude-code">Claude Code</a>.
</footer>"""

    return page("Iowa Liquor Data Exploration", body)


if __name__ == "__main__":
    data = load_all(fresh="--fresh" in sys.argv)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(build_page(data))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e3:.0f} KB)")
