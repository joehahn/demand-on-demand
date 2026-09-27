"""
data_fixes.py: publish docs/data_fixes.html, the before/after record of every fix the loader applied.

    python data_fixes.py            # reuse cached query results in cache/fixes/
    python data_fixes.py --fresh    # re-run every query (~3 minutes)

"Before" comes from raw.liquor_sales and the as-recorded columns; "after" from the cleaned warehouse.
Connects as dod_owner (reads raw.*). Never prints credentials.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import psycopg
from dotenv import load_dotenv

from dod.viz import AQUA, BLUE, ORANGE, Plots, line, page, style, table

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CACHE = ROOT / "cache" / "fixes"
OUT = ROOT / "docs" / "data_fixes.html"

QUERIES = {
    "fixes": "SELECT fix_id, description, rows_affected FROM meta.data_fixes",
    "dupes": """
        SELECT r.month, r.published, c.clean FROM
          (SELECT date_trunc('month', ordered_on::date)::date AS month, count(*) AS published
           FROM raw.liquor_sales GROUP BY 1) r
        JOIN (SELECT date_trunc('month', ordered_on)::date AS month, count(*) AS clean
              FROM sales.invoice_line GROUP BY 1) c USING (month) ORDER BY 1""",
    "zero_lines": """
        SELECT left(ordered_on, 4)::int AS year, count(*) AS zero_lines_removed
        FROM (SELECT DISTINCT * FROM raw.liquor_sales) r
        WHERE NULLIF(trim(sales_bottles), '')::numeric <= 0 OR NULLIF(trim(sales_dollars), '')::numeric <= 0
        GROUP BY 1 ORDER BY 1""",
    "tennessee": """
        SELECT date_trunc('month', l.ordered_on)::date AS month,
               sum(l.sales_bottles) FILTER (WHERE l.category_code = '1011400') AS as_recorded,
               sum(l.sales_bottles) FILTER (WHERE i.category_current = '1011400') AS clean
        FROM sales.invoice_line l JOIN sales.item i USING (item_no)
        WHERE l.ordered_on < '2018-01-01' GROUP BY 1 ORDER BY 1""",
    "rtd": """
        SELECT date_trunc('month', l.ordered_on)::date AS month,
               sum(l.sales_bottles) FILTER (WHERE l.category_code = '1071100') AS code_1071100,
               sum(l.sales_bottles) FILTER (WHERE l.category_code = '1071000') AS code_1071000,
               sum(l.sales_bottles) FILTER (WHERE i.category_current = '1071000') AS clean
        FROM sales.invoice_line l JOIN sales.item i USING (item_no)
        WHERE l.category_code IN ('1071100', '1071000', '1070000') OR i.category_current = '1071000'
        GROUP BY 1 ORDER BY 1""",
    "crosswalk": """
        SELECT x.category_code AS retired_code, x.current_code, c.category_name
        FROM sales.category_crosswalk x JOIN sales.category c ON c.category_code = x.current_code ORDER BY 3""",
    "tito_minis": """
        SELECT date_trunc('month', l.ordered_on)::date AS month, l.item_no, i.family_item_no, sum(l.sales_bottles) AS bottles
        FROM sales.invoice_line l JOIN sales.item i USING (item_no)
        WHERE i.family_item_no = '38194' GROUP BY 1, 2, 3 ORDER BY 1""",
    "families": """
        SELECT f.item_no AS old_item, f.family_item_no AS current_item, o.item_desc, o.bottle_volume_ml AS ml,
               o.last_order_on AS old_last_order, n.first_order_on AS new_first_order, o.total_bottles AS old_bottles
        FROM sales.item_family f JOIN sales.item o ON o.item_no = f.item_no JOIN sales.item n ON n.item_no = f.family_item_no
        ORDER BY o.total_bottles DESC""",
    "cities": """
        SELECT x.city_recorded AS recorded, x.city AS cleaned, count(s.store_no) AS stores
        FROM sales.city_crosswalk x JOIN sales.store s ON s.city_recorded = x.city_recorded GROUP BY 1, 2 ORDER BY 2""",
    "census": """
        SELECT 'population' AS measure, year, count(*) FILTER (WHERE carried_forward) AS carried_forward_counties
        FROM ref.county_population WHERE year >= 2023 GROUP BY 1, 2
        UNION ALL
        SELECT 'median income', year, count(*) FILTER (WHERE carried_forward)
        FROM ref.county_income WHERE year >= 2023 GROUP BY 1, 2 ORDER BY 1, 2""",
    "large_lines": """
        SELECT l.item_no, i.item_desc, l.bottle_volume_ml AS ml, count(*) AS lines, sum(l.sales_liters) AS liters
        FROM sales.invoice_line l JOIN sales.item i USING (item_no) WHERE l.bottle_volume_ml >= 6000
        GROUP BY 1, 2, 3 ORDER BY liters DESC""",
}


def load_all(fresh):
    CACHE.mkdir(parents=True, exist_ok=True)
    out, conn = {}, None
    for name, sql in QUERIES.items():
        path = CACHE / f"{name}.parquet"
        if path.exists() and not fresh:
            df = pd.read_parquet(path)
        else:
            conn = conn or psycopg.connect(os.environ["DOD_OWNER_DSN"])
            print(f"  querying {name}")
            cur = conn.execute(sql)
            df = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
            df.to_parquet(path)
        for c in df.columns:  # Postgres numeric arrives as Decimal
            if len(df) and isinstance(df[c].dropna().head(1).tolist()[0] if df[c].notna().any() else None, Decimal):
                df[c] = df[c].astype(float)
        out[name] = df
    if conn:
        conn.close()
    return out


def before_after(x, before, after, title, before_name="before (as published)", after_name="after (clean)"):
    f = go.Figure()
    for i, (series, name) in enumerate(zip(before, before_name if isinstance(before_name, list) else [before_name])):
        f.add_trace(line(x, series, name, [ORANGE, AQUA][i % 2], dash="dot"))
    f.add_trace(line(x, after, after_name, BLUE))
    f.update_traces(hovertemplate="%{y:,.0f}")
    return style(f, title, legend=True)


def build(d):
    plot = Plots()
    comma = lambda v: f"{int(v):,}"
    fx = d["fixes"].set_index("fix_id")
    n = lambda k: int(fx.at[k, "rows_affected"])

    du = d["dupes"]
    fig_dupes = before_after(du.month, [du.published], du.clean, "Order lines per month")
    tn = d["tennessee"]
    fig_tn = before_after(tn.month, [tn.as_recorded], tn.clean, "Tennessee whiskey bottles per month, 2016-2017",
                          "code 1011400 as recorded", "Tennessee whiskies, clean")
    rt = d["rtd"]
    fig_rtd = before_after(rt.month, [rt.code_1071100, rt.code_1071000], rt.clean, "Cocktails/RTD bottles per month",
                           ["code 1071100 as recorded", "code 1071000 as recorded"], "Cocktails/RTD, clean")
    tm = d["tito_minis"]
    items = tm.pivot_table(index="month", columns="item_no", values="bottles", aggfunc="sum")
    fam = tm.groupby("month").bottles.sum()
    fig_tm = go.Figure([line(items.index, items[c], f"item {c} as recorded", col, dash="dot")
                        for c, col in zip(["38180", "938180"], [ORANGE, AQUA]) if c in items])
    fig_tm.add_trace(line(fam.index, fam.values, "family 38194, clean", BLUE))
    fig_tm = style(fig_tm.update_traces(hovertemplate="%{y:,.0f}"), "Tito's 50 ml mini bottles per month, statewide",
                   legend=True)

    fams = d["families"].astype({"old_last_order": str, "new_first_order": str})
    body = f"""
<h1>Iowa liquor sales: what was fixed</h1>
<p>Every problem documented on <a href="data_exploration.html">the data exploration page</a> is fixed once, in the
warehouse, by the loader's clean stage. The raw landing table stays exactly as published, so each fix below is shown
before and after. Forecasts read only the clean tables, so none of them has to know these problems existed.</p>
{table(d["fixes"], {"rows_affected": comma})}

<h2>1. Duplicate rows in the state's export</h2>
<p>{n("export_duplicates"):,} rows repeated verbatim across CSV parts of the 2022, 2025 and 2026 downloads were removed.
The portal's own 2026 row count matches the de-duplicated count.</p>
{plot(fig_dupes)}

<h2>2. Zero lines</h2>
<p>{n("zero_value_lines"):,} order lines with zero bottles or zero dollars, likely cancelled lines, were removed.</p>
{table(d["zero_lines"], {"zero_lines_removed": comma})}

<h2>3. Category codes that changed meaning</h2>
<p>Every line now takes its item's <em>current</em> category, so all ten years are in today's taxonomy, and retired
codes map to the live code with the same name. {n("category_taxonomy"):,} lines changed category. Before, code
1011400 meant "Bottled in Bond Bourbon" until 2016-08-25, so Tennessee whiskey looked like it jumped 20-fold that
week:</p>
{plot(fig_tn)}
<p>And Cocktails/RTD, which looked discontinued in July 2022, is one continuous series:</p>
{plot(fig_rtd)}
{table(d["crosswalk"])}

<h2>4. Renumbered items</h2>
<p>{n("item_renumbering")} items were renumbered: same description and size, the new number starting within weeks of
the old one stopping. Each old number now belongs to a product family named after its current item, so the product's
history is continuous. Tito's 50 ml mini, before and after:</p>
{plot(fig_tm)}
<p>The 20 largest renumberings:</p>
{table(fams.head(20), {"old_bottles": comma})}

<h2>5. City spellings</h2>
<p>Each city now has one spelling in <code>store.city</code>; the source spelling is kept in
<code>store.city_recorded</code>.</p>
{table(d["cities"])}

<h2>6. Census data lags sales</h2>
<p>Census publishes county population about a year late and income about two years late. The latest published year
is carried forward, flagged, so every sales month has a reference value:</p>
{table(d["census"])}

<h2>7. Checked and left as is</h2>
<p><strong>Large-volume lines</strong> (6 liters or more) looked like errors but are genuine: pallet shippers and
whole-cask purchases. <strong>Missing prices</strong> before September 2025 need no fix, because unit price is
dollars divided by bottles. <strong>invoice_id</strong> changed meaning in September 2025, so lines are keyed by the
new line_id.</p>
{table(d["large_lines"], {"lines": comma, "liters": comma})}

<footer>
Data: <a href="https://catalog.data.gov/dataset/iowa-liquor-sales">Iowa Liquor Sales</a>, State of Iowa, via the Iowa
Data Hub, licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Modified as described on this
page. County population and income: U.S. Census Bureau. Not endorsed by the State of Iowa.<br>
Built by Joseph M. Hahn, Ph.D., <a href="https://jmh-datasciences.com">JMH DataSciences</a>, with
<a href="https://claude.com/claude-code">Claude Code</a>.
</footer>"""
    return page("Iowa Liquor Data Fixes", body)


if __name__ == "__main__":
    data = load_all(fresh="--fresh" in sys.argv)
    OUT.write_text(build(data))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e3:.0f} KB)")
