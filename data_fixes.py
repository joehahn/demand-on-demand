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

from dod.viz import AQUA, BLUE, ORANGE, SEQ_BLUE, Plots, line, page, style, table

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
        FROM (SELECT DISTINCT invoice_id, ordered_on, store_no, store_name, store_address, store_city, store_zip_code, county_fips_code, county_name, category_code, category_name, vendor_number, vendor_name, item_no, im_desc, pack, bottle_volume_ml, state_bottle_cost, state_bottle_retail, sales_bottles, sales_dollars, sales_liters, sales_gallons FROM raw.liquor_sales) r
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
        SELECT date_trunc('month', l.ordered_on)::date AS month, l.item_no, i.family_item_no,
               sum(l.sales_bottles_recorded) AS bottles
        FROM sales.invoice_line l JOIN sales.item i USING (item_no)
        WHERE i.family_item_no = '38194' GROUP BY 1, 2, 3 ORDER BY 1""",
    # mini sleeves: liters as recorded fall ~10x on 2019-08-01 although the same sleeves kept selling
    "mini_liters": """
        SELECT date_trunc('month', l.ordered_on)::date AS month, sum(l.sales_liters_recorded) AS as_recorded,
               sum(l.sales_liters) AS clean
        FROM sales.invoice_line l JOIN sales.item_units u USING (item_no)
        WHERE u.units_per_sale IS NOT NULL GROUP BY 1 ORDER BY 1""",
    "units_evidence": """
        SELECT CASE WHEN u.units_per_sale IS NULL THEN 'flagged: pack size unknown'
                    WHEN u.evidence LIKE 'recorded as%%' THEN 'sleeve volume recorded earlier'
                    WHEN u.evidence LIKE 'same product family%%' THEN 'product family'
                    ELSE 'pack size in the item name' END AS evidence,
               count(DISTINCT u.item_no) AS items, sum(l.sales_bottles_recorded) AS units_as_recorded,
               sum(l.sales_bottles) AS bottles_clean
        FROM sales.item_units u JOIN sales.invoice_line l USING (item_no) GROUP BY 1 ORDER BY 3 DESC""",
    "units_top": """
        SELECT u.item_no, i.item_desc, u.units_per_sale AS bottles_per_unit, u.bottle_ml AS ml, u.evidence,
               sum(l.sales_bottles_recorded) AS units_as_recorded
        FROM sales.item_units u JOIN sales.item i USING (item_no) JOIN sales.invoice_line l USING (item_no)
        GROUP BY 1, 2, 3, 4, 5 ORDER BY 6 DESC""",
    # liters truncated to whole liters, Nov 2025 - Jan 2026
    "liters_truncated": """
        SELECT date_trunc('month', ordered_on)::date AS month, sum(sales_liters_recorded) AS as_recorded,
               sum(sales_bottles_recorded * bottle_volume_ml_recorded / 1000.0) AS clean
        FROM sales.invoice_line WHERE ordered_on >= '2025-01-01' GROUP BY 1 ORDER BY 1""",
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
    # 2016 is split at the reorganization (2016-08-29) so neither half mixes the old and new taxonomies
    "categories_per_year": """
        SELECT CASE WHEN ordered_on < '2016-08-29' THEN '2016 to Aug 28'
                    WHEN ordered_on < '2017-01-01' THEN '2016 from Aug 29' ELSE left(ordered_on, 4) END AS period,
               count(DISTINCT category_name) AS category_names, count(DISTINCT category_code) AS category_codes
        FROM raw.liquor_sales WHERE category_code <> '' GROUP BY 1 ORDER BY min(ordered_on)""",
    # stores whose recorded attributes change over time
    "store_drift": """
        SELECT count(*) AS stores,
               count(*) FILTER (WHERE n_name > 1)   AS changed_name,
               count(*) FILTER (WHERE n_city > 1)   AS changed_city,
               count(*) FILTER (WHERE n_county > 1) AS changed_county,
               count(*) FILTER (WHERE n_addr > 1)   AS changed_address,
               (SELECT count(*) FROM sales.store WHERE county_name IS NULL) AS no_county
        FROM (SELECT store_no, count(DISTINCT store_name) n_name, count(DISTINCT store_city) n_city,
                     count(DISTINCT NULLIF(trim(county_name), '')) n_county, count(DISTINCT store_address) n_addr
              FROM raw.liquor_sales GROUP BY 1) s""",
    "store_lifespans": """
        SELECT date_trunc('month', first_order_on)::date AS month, count(*) AS opened
        FROM sales.store GROUP BY 1 ORDER BY 1""",
    # as recorded: volume and price per selling unit of the mini sleeves and packs
    "mini_units": """
        SELECT date_trunc('month', l.ordered_on)::date AS month,
               1000 * sum(l.sales_liters_recorded) / sum(l.sales_bottles_recorded) AS ml_per_unit,
               sum(l.sales_dollars) / sum(l.sales_bottles_recorded) AS dollars_per_unit
        FROM sales.invoice_line l JOIN sales.item_units u USING (item_no)
        WHERE u.units_per_sale IS NOT NULL GROUP BY 1 ORDER BY 1""",
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


def fig_categories(d):
    c = d["categories_per_year"].set_index("period")   # '2016 to Aug 28', '2016 from Aug 29', '2017', ...
    before, after = c.category_codes.iloc[0], c.category_codes.iloc[1]
    f = go.Figure([line(c.index, c.category_names, "Distinct category names", BLUE),
                   line(c.index, c.category_codes, "Distinct category codes", ORANGE, dash="dot")])
    f.update_traces(mode="lines+markers", marker=dict(size=8))
    f.update_xaxes(type="category")
    return style(f, f"Categories were consolidated in August 2016 (about {before:.0f} codes became {after:.0f})", "count",
                 legend=True)


def fig_mini_units(d):
    m = d["mini_units"]
    # milliliters on the left axis, dollars on the right: the price stays flat while the recorded volume falls
    ml = line(m.month, m.ml_per_unit, "ml per unit, as recorded (left)", ORANGE)
    usd = line(m.month, m.dollars_per_unit, "dollars per unit (right)", BLUE)
    ml.update(hovertemplate="%{y:,.0f} ml")
    usd.update(yaxis="y2", hovertemplate="$%{y:,.2f}")
    f = style(go.Figure([ml, usd]), "Mini sleeves: price per unit stayed flat while the recorded volume fell tenfold in 2019",
              "ml per selling unit, as recorded", legend=True)
    # both axes on round ticks that share gridlines (0-800 ml by 200, $0-16 by $4); legend below, clear of the title
    return f.update_layout(margin=dict(r=60, b=70), yaxis=dict(range=[0, 800], dtick=200),
                           yaxis2=dict(title="dollars per selling unit", overlaying="y", side="right", range=[0, 16],
                                       dtick=4, tickprefix="$", showgrid=False, zeroline=False),
                           legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, xanchor="left"))


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


def fig_store_openings(d):
    s = d["store_lifespans"]
    s = s[s.month > s.month.min()]  # the first month is "already open in 2016", not an opening
    f = go.Figure(go.Bar(x=s.month, y=s.opened, marker_color=BLUE,
                         hovertemplate="%{x|%b %Y}: %{y} stores first ordered<extra></extra>"))
    return style(f, "Stores placing their first order each month", "stores").update_layout(hovermode="closest")


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
    fig_tm = style(fig_tm.update_traces(hovertemplate="%{y:,.0f}"),
                   "Tito's 50 ml mini sleeves per month, statewide (units as recorded)", legend=True)
    ml = d["mini_liters"]
    fig_ml = before_after(ml.month, [ml.as_recorded], ml.clean, "Liters per month of minis sold in sleeves and packs",
                          "as recorded", "clean")
    lt = d["liters_truncated"]
    fig_lt = before_after(lt.month, [lt.as_recorded], lt.clean, "Liters per month, statewide, 2025 to 2026",
                          "as recorded", "clean")
    known = d["units_top"][d["units_top"].bottles_per_unit.notna()].head(12)
    flagged = d["units_top"][d["units_top"].bottles_per_unit.isna()].head(12).drop(columns=["bottles_per_unit", "ml"])

    fams = d["families"].astype({"old_last_order": str, "new_first_order": str})
    cat = d["category_reuse"].astype({"first_seen": str, "last_seen": str}).rename(columns={"lines": "records"})
    sd = d["store_drift"].iloc[0]
    body = f"""
<h1>Iowa liquor sales: data problems and fixes</h1>
<p>Every known problem in the published data: what it looks like, and how the loader fixes it once, in the warehouse.
The raw landing table stays exactly as published, so each fix is shown before and after, and forecasts read only the
clean tables. <a href="data_exploration.html">The data exploration page</a> shows what the clean data looks like.</p>
{table(d["fixes"], {"rows_affected": lambda v: f"{int(v):,}" if v else "checked"})}

<h2 id="duplicates">1. Duplicate rows in the state's export</h2>
<p>{n("export_duplicates"):,} rows repeated verbatim across CSV parts of the 2022, 2025 and 2026 downloads were removed.
The portal's own 2026 row count matches the de-duplicated count.</p>
{plot(fig_dupes)}

<h2 id="zero-lines">2. Zero records</h2>
<p>{n("zero_value_lines"):,} order lines with zero bottles or zero dollars, likely cancelled lines, were removed.</p>
{table(d["zero_lines"], {"zero_lines_removed": comma})}

<h2 id="categories">3. Category codes that changed meaning</h2>
<p>Every line now takes its item's <em>current</em> category, so all ten years are in today's taxonomy, and retired
codes map to the live code with the same name. {n("category_taxonomy"):,} lines changed category. Before, code
1011400 meant "Bottled in Bond Bourbon" until 2016-08-25, so Tennessee whiskey looked like it jumped 20-fold that
week:</p>
{plot(fig_tn)}
<p>The reorganization folded the categories into about half as many, and many old codes were given to different
categories. Here 2016 is shown as two points: before and after the change on August 29, 2016. The table lists the first
12 codes whose name changed.</p>
{plot(fig_categories(d))}
{table(cat.head(12), {"records": comma})}
<p>And Cocktails/RTD, which looked discontinued in July 2022, is one continuous series:</p>
{plot(fig_rtd)}
{table(d["crosswalk"])}

<h2 id="renumbering">4. Renumbered products</h2>
<p>The state sometimes gives a product a new item number. Tito's 50 ml mini was item 38180 until July 2020 and 38194
after, so selecting today's number alone would lose four years of sales. The loader found {n("item_renumbering")}
renumbered items (same description and size, the new number starting within weeks of the old one stopping) and links
each old number to its product's current number, a product family, so the product's history is continuous. Tito's
50 ml mini, before and after:</p>
{plot(fig_tm)}
<p>The 12 largest renumberings:</p>
{table(fams.head(12), {"old_bottles": comma})}

<h2 id="units">5. A sleeve of minis counted as one bottle</h2>
<p>The state records a sleeve of minis (e.g. Tito's 12 × 50 ml) as one "bottle". Its price per sleeve stayed about
$13 (blue), but its recorded volume fell from the whole sleeve (about 700 ml) to one mini (about 50 to 70 ml) in
mid-2019 (orange). So only the bookkeeping changed, not what stores bought. The dip near zero in late 2025 is a
separate rounding error (section 6).</p>
{plot(fig_mini_units(d))}
<p>Where the pack size is known, the warehouse now counts each mini as a bottle and computes liters as bottles times
one mini's volume, keeping the recorded values alongside. {n("multi_bottle_units"):,} records changed:</p>
{plot(fig_ml)}
{table(d["units_evidence"], {"units_as_recorded": comma, "bottles_clean": comma})}
<p>The largest converted items:</p>
{table(known, {"units_as_recorded": comma, "bottles_per_unit": comma})}
<p>Items priced like a multi-pack (over $0.10 per ml) but with no evidence of the pack size are not converted, since
a guess would put a wrong multiplier into their history. They stay in selling units and are flagged in
the warehouse. The largest:</p>
{table(flagged, {"units_as_recorded": comma})}

<h2 id="liters">6. Liters rounded down to whole liters</h2>
<p>From November 2025 to January 2026 the state rounded each record's liters sold down to a whole liter (bottle sizes
were unaffected). A case of six 750 ml bottles (4.5 L) became 4 L, and a sleeve of 12 minis (0.6 L) became 0 L.
Statewide that loses about 3.5% of liters in those months ({n("liters_truncated"):,} records). Liters are now bottles
times bottle volume on every record, which matches what was recorded in every other month.</p>
{plot(fig_lt)}

<h2 id="cities">7. Store details change, and cities are spelled several ways</h2>
<p>{int(sd.changed_name):,} of {int(sd.stores):,} stores changed name over the years, {int(sd.changed_address):,}
address, {int(sd.changed_city):,} city and {int(sd.changed_county):,} county. A store keeps its number for life, so its sales
stay together through these changes; the warehouse uses each store's most recent name, address and county. The
{int(sd.no_county)} stores whose most recent records leave the county blank count in city and statewide requests but not
county ones. Some cities are spelled more than one way, which would split one city into two; each now has one
spelling:</p>
{table(d["cities"])}
<p>Stores also open and close throughout the history. That is real, not an error, and the models see it through the
number of stores ordering:</p>
{plot(fig_store_openings(d))}

<h2 id="census">8. Census data lags sales</h2>
<p>Census publishes county population about a year late and income about two years late. The latest published year
is carried forward, flagged, so every sales month has a reference value:</p>
{table(d["census"])}

<h2 id="checked">9. Checked and left as is</h2>
<p><strong>Missing values.</strong> Blank values come and go by column and year. The state's bottle cost and retail
price are blank before September 2025, which needs no fix because unit price is dollars divided by bottles. Blank
counties affect a few percent of early records, and county comes from the store instead.</p>
{plot(fig_blanks(d))}
<p><strong>invoice_id changed meaning.</strong> Until August 2025 every order line had its own invoice_id; from
September 1, 2025 one invoice_id covers a whole order, about 20 lines. Counting distinct invoice_ids would overstate
orders about twentyfold before September 2025. Forecasts never use it: the warehouse gives every order line its own new
ID, and the data dictionary warns that invoice_id identifies orders only from September 2025.</p>
<p><strong>Large-volume records</strong> (6 liters or more) looked like errors but are genuine: pallet shippers and
whole-cask purchases, kept as recorded.</p>
{table(d["large_lines"], {"lines": comma, "liters": comma})}

<footer>
Data: <a href="https://data.iowa.gov/catalog?q=liquor+sales">Iowa Liquor Sales</a>, State of Iowa, via the Iowa
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
