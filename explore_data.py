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

    # records per day as published, and how many of them are distinct (the rest are export duplicates)
    "daily": """
        WITH published AS (SELECT ordered_on, count(*) AS n FROM raw.liquor_sales GROUP BY 1),
             distinct_rows AS (SELECT ordered_on, count(*) AS n
                               FROM (SELECT DISTINCT invoice_id, ordered_on, store_no, store_name, store_address, store_city, store_zip_code, county_fips_code, county_name, category_code, category_name, vendor_number, vendor_name, item_no, im_desc, pack, bottle_volume_ml, state_bottle_cost, state_bottle_retail, sales_bottles, sales_dollars, sales_liters, sales_gallons FROM raw.liquor_sales) d GROUP BY 1)
        SELECT p.ordered_on::date AS day, p.n AS published, d.n AS distinct_rows
        FROM published p JOIN distinct_rows d USING (ordered_on) ORDER BY 1""",

    "line_sizes": """
        SELECT sales_bottles AS bottles, count(*) AS lines FROM sales.invoice_line GROUP BY 1 ORDER BY 1""",

    "top_categories": """
        SELECT c.category_name AS name, sum(l.sales_dollars) AS dollars, count(*) AS lines
        FROM sales.invoice_line l JOIN sales.item i USING (item_no) JOIN sales.category c ON c.category_code = i.category_current
        GROUP BY 1 ORDER BY 2 DESC LIMIT 15""",

    "top_vendors": """
        SELECT v.vendor_name AS name, sum(l.sales_dollars) AS dollars, count(*) AS lines
        FROM sales.invoice_line l JOIN sales.vendor v USING (vendor_no) GROUP BY 1 ORDER BY 2 DESC LIMIT 15""",

    "top_stores": """
        SELECT s.store_name || ' (' || s.city || ')' AS name, sum(l.sales_dollars) AS dollars, count(*) AS lines
        FROM sales.invoice_line l JOIN sales.store s USING (store_no) GROUP BY 1 ORDER BY 2 DESC LIMIT 15""",

    # bottles per month by category, in today's taxonomy: the slices that forecasts are actually asked about
    "category_monthly": """
        SELECT date_trunc('month', l.ordered_on)::date AS month, c.category_name AS category, sum(l.sales_bottles) AS bottles
        FROM sales.invoice_line l JOIN sales.item i USING (item_no) JOIN sales.category c ON c.category_code = i.category_current
        GROUP BY 1, 2 ORDER BY 1, 2""",

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

def volume(d):
    """Daily published vs distinct records, with the duplicates split out."""
    v = d["daily"].copy()
    v["day"] = pd.to_datetime(v.day)
    # every calendar day, zero when no orders were placed, so a step line drops to zero on weekends and holidays
    v = v.set_index("day").reindex(pd.date_range(v.day.min(), v.day.max(), freq="D"), fill_value=0)
    v = v.rename_axis("day").reset_index()
    v["duplicates"] = v.published - v.distinct_rows
    return v


def stacked(x, v, title, shape="hv", height=340, outline=True):
    """Step-style stacked areas: distinct records in blue, export duplicates stacked on top in orange.
    shape "hv" steps at each date (a period starts at its date); "hvh" centers each step on a category label."""
    common = dict(mode="lines", line=dict(shape=shape, width=1.5 if outline else 0), stackgroup="lines",
                  hovertemplate="%{y:,.0f}")
    f = go.Figure([go.Scatter(x=x, y=v.distinct_rows, name="Distinct records", line_color=BLUE,
                              fillcolor="rgba(42,120,214,0.55)" if outline else "rgba(42,120,214,0.85)", **common),
                   go.Scatter(x=x, y=v.duplicates, name="Duplicate records (removed)", line_color=ORANGE,
                              fillcolor="rgba(235,104,52,0.55)" if outline else "rgba(235,104,52,0.9)", **common)])
    f = style(f, title, "records", height=height, legend=True)
    return f.update_layout(legend_traceorder="normal")


def with_end(v, freq):
    """Repeat the last period one step later, so a step line gives the final period its full width."""
    last = v.iloc[[-1]].copy()
    last.index = last.index + pd.tseries.frequencies.to_offset(freq)
    return pd.concat([v, last])


def fig_daily(d):
    v = with_end(volume(d).set_index("day")[["distinct_rows", "duplicates"]], "D")
    # ~3,900 days that drop to zero every weekend: filled areas without outlines, or the strokes hide the fill
    return stacked(v.index, v, "Records per day", height=380, outline=False)


def fig_monthly_lines(d):
    v = volume(d).set_index("day").resample("MS")[["distinct_rows", "duplicates"]].sum()
    return stacked(with_end(v, "MS").index, with_end(v, "MS"), "Records per month")


def fig_yearly_lines(d):
    v = volume(d)
    v = v.groupby(v.day.dt.year)[["distinct_rows", "duplicates"]].sum()
    f = stacked(v.index.astype(str), v, "Records per year (2026 through August)", shape="hvh")
    f.update_xaxes(type="category")
    return f


def fig_weekday(d):
    v = volume(d)
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    w = v.groupby(v.day.dt.dayofweek)[["distinct_rows", "duplicates"]].sum().reindex(range(7), fill_value=0)
    f = stacked([names[i] for i in w.index], w, "Records by day of week", shape="hvh")
    f.update_xaxes(type="category")
    return f


def fig_month_of_year(d):
    v = volume(d)
    v = v[v.day.dt.year <= 2025]  # complete years only, or Jan-Aug would count one more year than Sep-Dec
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    m = v.groupby(v.day.dt.month)[["distinct_rows", "duplicates"]].sum().reindex(range(1, 13), fill_value=0)
    f = stacked([names[i - 1] for i in m.index], m, "Records by month of year, 2016 to 2025", shape="hvh")
    f.update_xaxes(type="category")
    return f


def fig_line_sizes(d):
    b = d["line_sizes"]
    edges = [1, 2, 3, 6, 7, 12, 13, 24, 25, 48, 49, 120, 121, 600, 601, 10 ** 9]
    labels = ["1", "2", "3-6", "7-12", "13-24", "25-48", "49-120", "121-600", "over 600"]
    bins = [(1, 1), (2, 2), (3, 6), (7, 12), (13, 24), (25, 48), (49, 120), (121, 600), (601, 10 ** 9)]
    counts = [b[(b.bottles >= lo) & (b.bottles <= hi)].lines.sum() for lo, hi in bins]
    f = go.Figure(go.Bar(x=labels, y=counts, marker_color=BLUE, hovertemplate="%{x} bottles: %{y:,} records<extra></extra>"))
    f.update_xaxes(type="category", title="bottles on the record")
    return style(f, "Order size: bottles per record", "records").update_layout(hovermode="closest")


def fig_top(df, title):
    t = df.sort_values("dollars")
    f = go.Figure(go.Bar(x=t.dollars, y=t.name.str.title(), orientation="h", marker_color=BLUE,
                         customdata=t.lines, hovertemplate="%{y}: $%{x:,.0f}, %{customdata:,} records<extra></extra>"))
    return style(f, title, height=460).update_layout(hovermode="closest", margin=dict(l=260))


def by_category(d):
    """Monthly bottles, one column per category (today's taxonomy), plus the statewide total."""
    c = d["category_monthly"].pivot_table(index="month", columns="category", values="bottles", aggfunc="sum")
    c.index = pd.to_datetime(c.index)
    c["ALL LIQUOR"] = d["monthly"].set_index(pd.to_datetime(d["monthly"].month)).bottles
    return c


def fig_slice_seasonality(d):
    """Two holiday categories against the total, each as a share of its own average month."""
    c = by_category(d)
    series = [("ALL LIQUOR", "All liquor", BLUE), ("CREAM LIQUEURS", "Cream liqueurs", ORANGE),
              ("TEMPORARY & SPECIALTY PACKAGES", "Gift and specialty packs", AQUA)]
    f = go.Figure([line(c.index, 100 * c[k] / c[k].mean(), name, col) for k, name, col in series])
    f.update_traces(hovertemplate="%{y:.0f}% of its average month")
    return style(f, "Monthly bottles vs each series' own average", "% of the series' average month (100% = average)", height=380, legend=True)


def fig_peak_to_trough(d):
    """For the 40 biggest categories: busiest month of the year divided by the quietest, 2016 to 2025."""
    c = by_category(d)
    c = c[c.index.year <= 2025]  # complete years only
    top = c.drop(columns="ALL LIQUOR").sum().nlargest(40).index.tolist() + ["ALL LIQUOR"]
    moy = c[top].groupby(c.index.month).mean()  # average bottles in each month of the year
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    t = pd.DataFrame({"ratio": moy.max() / moy.min(), "peak": [names[m - 1] for m in moy.idxmax()]}).sort_values("ratio")
    colors = [ORANGE if k == "ALL LIQUOR" else BLUE for k in t.index]
    f = go.Figure(go.Bar(x=t.ratio, y=t.index.str.title(), orientation="h", marker_color=colors, customdata=t.peak,
                         hovertemplate="%{y}: busiest month %{x:.1f}x the quietest (peak in %{customdata})<extra></extra>"))
    f.update_xaxes(title="busiest month of the year / quietest month", ticksuffix="x")
    return style(f, "Seasonal swing of the 40 largest categories (all liquor in orange)", height=820).update_layout(
        hovermode="closest", margin=dict(l=260))


def fig_rtd_step(d):
    """Ready-to-drink cocktails jumped in 2020 and stayed up; the total barely moved."""
    c = by_category(d)
    c = c[c.index.year <= 2025]  # complete years only
    y = c.groupby(c.index.year)[["ALL LIQUOR", "COCKTAILS/RTD"]].sum()
    y = 100 * y / y.loc[2019]
    f = go.Figure([line(y.index, y["ALL LIQUOR"], "All liquor", BLUE),
                   line(y.index, y["COCKTAILS/RTD"], "Cocktails/RTD", ORANGE)])
    f.update_traces(mode="lines+markers", marker=dict(size=8), hovertemplate="%{y:.0f}")
    f.update_xaxes(dtick=1)
    return style(f, "Bottles per year, 2019 = 100", "index (2019 = 100)", legend=True)


def fixed(anchor, what):
    """Link to the section of the data fixes page that explains this issue and its correction."""
    return f'<p class="fixlink">Corrected in the warehouse: <a href="data_fixes.html#{anchor}">{what}</a></p>'


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
    return style(f, "The state's export repeats rows: published vs distinct records per month", "records", legend=True)


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
                         hovertemplate="%{x}: %{y:,} records<extra></extra>"))
    f.update_xaxes(type="category")
    return style(f, "The 15 most common bottle sizes", "records", height=320).update_layout(hovermode="closest")


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

    plot = Plots(numbered=True)  # plotly.js loaded once, from the CDN; figures numbered in page order

    tiles = [
        (f"{rc['sales.invoice_line'] / 1e6:.1f}M", "records, 2016 to Aug 2026"),
        (f"${m.dollars.sum() / 1e9:.2f}B", "wholesale sales"),
        (f"{rc['sales.store']:,}", "stores"),
        (f"{rc['sales.item']:,}", "products"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in tiles)

    cat = d["category_reuse"].copy()
    for c in ("first_seen", "last_seen"):
        cat[c] = cat[c].astype(str)

    titos = d["titos"].copy()
    for c in ("first_order", "last_order"):
        titos[c] = titos[c].astype(str)

    sus = d["suspect_lines"]
    comma = lambda v: f"{int(v):,}"

    body = f"""
<h1>Iowa liquor sales: what the data looks like</h1>
<p>Every wholesale liquor order placed by an Iowa retailer since 2016, loaded into a local Postgres
warehouse. This page is the first step of <a href="https://github.com/joehahn/demand-on-demand">demand-on-demand</a>:
before an AI agent can answer "forecast Tito's in Polk County for the next 5 months," someone has to
know what traps are in the data. Claude found these while loading and profiling the data, and proposed a fix for each;
a person reviewed and approved every fix before it went into the warehouse. <a href="data_fixes.html">The data fixes page</a>
shows how each one was fixed there, once, so no forecast has to deal with it.</p>
<div class="tiles">{tiles_html}</div>

<h2>How many orders, and when</h2>
<p>Records (order lines) per day, month, weekday, month of year and year, as published. Orange: export duplicates, removed.</p>
{plot(fig_daily(d))}
{plot(fig_monthly_lines(d))}
{plot(fig_weekday(d))}
{plot(fig_month_of_year(d))}
{plot(fig_yearly_lines(d))}
{fixed('duplicates', 'how the duplicate rows were found and removed')}

<h2>Demand: trend and seasonality</h2>
<p>Statewide dollars, bottles and liters per month.</p>
{"".join(plot(f) for f in fig_demand(d))}
<p>Slices swing far more than the total. Each line is that series' monthly bottles as a percent of its own average
month, so 100% is a normal month and 300% is three times normal.</p>
{plot(fig_slice_seasonality(d))}
<p>Busiest month of the year divided by the quietest, 2016 to 2025. Hover for the peak month.</p>
{plot(fig_peak_to_trough(d))}
<p>Ready-to-drink cocktails stepped up in 2020 and stayed up.</p>
{plot(fig_rtd_step(d))}

<h2>The state's own export duplicates rows</h2>
<p>Rows as published vs distinct rows per month.</p>
{plot(fig_dupes(d))}
{fixed('duplicates', 'duplicate rows: the issue and the fix')}

<h2>Missing values move around over time</h2>
<p>Share of blank values by column and year.</p>
{plot(fig_blanks(d))}
{fixed('checked', 'missing prices: why no fix is needed (price = dollars / bottles)')}

<h2>Category codes were reused for different categories</h2>
<p>Distinct category names and codes per year, and the first 24 reassigned codes.</p>
{plot(fig_categories(d))}
{table(cat.head(24).rename(columns={"lines": "records"}), {"records": comma})}
{fixed('categories', 'category codes: history restated in today\'s taxonomy')}

<h2>A category that looks discontinued was recoded</h2>
<p>Cocktails/RTD bottles per month by recorded category code.</p>
{plot(fig_rtd(d))}
{fixed('categories', 'the Cocktails/RTD recode: one continuous category')}

<h2>One product, many item numbers</h2>
<p>Tito's item numbers, then the largest of the {len(d["renumbered"])} renumbered items.</p>
{table(titos.rename(columns={"lines": "records"}), {"records": comma, "bottles": comma})}
{table(d["renumbered"].head(12).astype({"old_last_order": str, "new_first_order": str}), {"old_bottles": comma})}
{fixed('renumbering', 'renumbered items joined into product families')}

<h2>Stores drift, open and close</h2>
<p>{int(sd.changed_name):,} of {int(sd.stores):,} stores changed name, {int(sd.changed_address):,} address,
{int(sd.changed_city):,} city and {int(sd.changed_county):,} county; {rc['stores with no county']} have no county.
City spellings that name the same city:</p>
{table(d["city_variants"])}
{fixed('cities', 'city spellings unified')}
{plot(fig_store_openings(d))}

<h2>Outliers and odd lines</h2>
<p>Records by bottle size, and odd lines per year (huge_bottles: 10 liters or more).</p>
{plot(fig_bottle_sizes(d))}
{table(sus, {"zero_dollar": comma, "zero_bottles": comma, "huge_bottles": comma})}
{fixed('zero-lines', 'zero lines removed')}
{fixed('checked', 'large bottle sizes checked: genuine pallet and cask buys, kept')}

<h2>invoice_id changed meaning</h2>
<p>Lines per invoice_id per month: one id per line until August 2025, one per order after.</p>
{plot(fig_lines_per_invoice(d))}
{fixed('checked', 'invoice_id: lines keyed by a new line_id')}

<h2>Geography: joins to Census reference data</h2>
{plot(fig_counties(d))}
{fixed('census', 'Census data lag: latest year carried forward')}

<h2>Who orders what</h2>
<p>Order sizes, and the largest categories, vendors and stores by wholesale dollars.</p>
{plot(fig_line_sizes(d))}
{plot(fig_top(d["top_categories"], "Top 15 categories by sales dollars"))}
{plot(fig_top(d["top_vendors"], "Top 15 vendors by sales dollars"))}
{plot(fig_top(d["top_stores"], "Top 15 stores by sales dollars"))}

<footer>
Data: <a href="https://catalog.data.gov/dataset?q=iowa+liquor+sales">Iowa Liquor Sales</a>, State of Iowa,
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
