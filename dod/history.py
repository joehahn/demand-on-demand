"""Fixed code: the AI's query -> the history to forecast, plus everything the dashboard shows about its data.

The AI's query picks order lines: one row per line with day, store_no, item_no, series and value (see dod/agent.py).
It is never run as is. Fixed code wraps it in its own sums, so the database does the adding up:
  by month, store and series   the series at month grain, the store list and map, active stores, population
  by week and series           the series at week grain (weeks do not fit inside months)
  by product                   which products are in the forecast: renumbered items, sleeves and packs of minis
"""
import pandas as pd

from . import db, features
from .panel import Panel, check_months, data_end, older_numbers, store_list
from .sqlcheck import check_sql

COLUMNS = ["day", "store_no", "item_no", "series", "value"]
FREQ = {"week": "W-MON", "month": "MS", "quarter": "QS"}


def check_query(sql):
    """None if the AI's query is one read-only SELECT returning the five columns, else an error for the AI."""
    problem = check_sql(sql)
    if problem:
        return f"Error: rejected ({problem}). Write one SELECT over sales or ref, schema-qualified."
    try:
        cols = list(db.query(f"SELECT * FROM ({sql}) q LIMIT 0").columns)
    except Exception as e:   # database errors go back to the AI so it can correct its query
        return f"Error: {str(e).splitlines()[0]}"
    if cols != COLUMNS:
        return f"Error: the query must return exactly {', '.join(COLUMNS)} (got {', '.join(cols)})."
    return None


def monthly_rows(sql):
    """The AI's order lines summed by month, store and series."""
    return db.query(f"SELECT date_trunc('month', day)::date AS month, store_no, series, sum(value) AS value, "
                    f"count(*) AS records FROM ({sql}) q GROUP BY 1, 2, 3")


def weekly_rows(sql):
    """The AI's order lines summed by week (Monday) and series."""
    return db.query(f"SELECT date_trunc('week', day)::date AS period, series, sum(value) AS value "
                    f"FROM ({sql}) q GROUP BY 1, 2")


def product_rows(sql, last_month):
    """The AI's order lines summed by item number: the last 12 complete months, and the first and last month sold."""
    since, until = last_month - pd.DateOffset(months=11), last_month + pd.offsets.MonthBegin(1)
    # the dates are written in (fixed code makes them), not passed as parameters: the AI's SQL may contain % signs
    return db.query(f"SELECT item_no, sum(value) FILTER (WHERE day >= '{since:%Y-%m-%d}' AND day < '{until:%Y-%m-%d}') "
                    f"AS last_12_months, min(day) AS first_day, max(day) AS last_day FROM ({sql}) q GROUP BY 1")


def product_list(rows):
    """One row per product (old item numbers joined to their product's current one), largest first."""
    names = db.query("SELECT i.item_no, i.family_item_no AS product_id, h.item_desc AS product, h.bottle_volume_ml "
                     "AS ml, c.category_name AS category FROM sales.item i JOIN sales.item h ON h.item_no = "
                     "i.family_item_no LEFT JOIN sales.category c ON c.category_code = h.category_current "
                     "WHERE i.item_no = ANY(%s)", (list(rows.item_no),))
    g = rows.merge(names, on="item_no").groupby(["product_id", "product", "ml", "category"], dropna=False)
    out = g.agg(first_sold=("first_day", "min"), last_sold=("last_day", "max"),
                last_12_months=("last_12_months", "sum")).reset_index()
    out["product"], out["category"] = out["product"].str.title(), out["category"].str.title()
    for c in ("first_sold", "last_sold"):
        out[c] = pd.to_datetime(out[c]).dt.strftime("%Y-%m")
    return out.fillna({"last_12_months": 0}).sort_values(["last_12_months", "product"], ascending=[False, True])


def to_grain(rows, grain, end, last_month):
    """Period totals (columns period, series, value) -> one column per series, complete periods only. A period with no
    orders is 0 (check_months makes sure the warehouse has every month); periods before a series' first sale are blank."""
    wide = rows.pivot_table(index="period", columns="series", values="value", aggfunc="sum")
    wide.index = pd.to_datetime(wide.index)
    step = pd.tseries.frequencies.to_offset(FREQ[grain])
    # complete periods: a month or quarter must end by the last complete month, a week by the last day with orders
    last = last_month + pd.offsets.MonthBegin(1) - pd.Timedelta(days=1) if grain != "week" else pd.Timestamp(end)
    idx = pd.date_range(pd.Timestamp("2016-01-01") if grain != "week" else wide.index.min(), last, freq=FREQ[grain])
    idx = idx[[p + step - pd.Timedelta(days=1) <= last for p in idx]]
    wide = wide.reindex(idx).fillna(0.0).rename_axis(None, axis=1)
    for c in wide:
        first = wide[c].gt(0).idxmax() if wide[c].gt(0).any() else None
        if first is not None:
            wide.loc[wide.index < first, c] = float("nan")
    wide.index.freq = None
    return wide


def unknown_packs(items):
    """Items sold as a sleeve or pack of unknown size (they count one bottle per pack), largest first."""
    return list(db.query("SELECT i.item_desc FROM sales.item_units u JOIN sales.item i USING (item_no) "
                         "WHERE u.units_per_sale IS NULL AND u.item_no = ANY(%s) ORDER BY i.total_bottles DESC NULLS LAST",
                         (items,)).item_desc)


def build(sql, grain, steps):
    """The history for one forecast: series at the grain, the inputs offered to model selection (dod/features.py),
    the periods ahead, and the store and product details the dashboard shows. Returns (Panel, input groups offered)."""
    end, last_month = data_end()
    check_months("2016-01-01", last_month)   # a period with no orders must be a real zero, not missing data
    months = monthly_rows(sql)
    if months.empty or not (months.value > 0).any():
        raise ValueError("The query found no sales for this request.")
    months["month"] = pd.to_datetime(months.month)
    months = months[months.month <= last_month]   # complete months only, as forecast
    if grain == "week":
        rows = weekly_rows(sql)
    else:
        start = months.month.dt.to_period("Q").dt.start_time if grain == "quarter" else months.month
        rows = months.assign(period=start)[["period", "series", "value"]]
    wide = to_grain(rows, grain, end, last_month)
    step = pd.tseries.frequencies.to_offset(FREQ[grain])
    future = pd.date_range(wide.index[-1] + step, periods=steps, freq=step)
    idx = wide.index.append(future)

    groups = features.GROUPS[grain]
    sold = months[months.value > 0]
    if grain == "week":
        common = features.season(pd.DatetimeIndex(idx, freq="W-MON")).join(features.holiday_weeks(idx))
        common["active_stores"] = features.stores(sold, idx, steps * step).values   # shifted by the horizon
        exog = {c: common.copy() for c in wide}
    else:
        cal = features.calendar(idx, grain)
        pops = features.population(sold, idx)
        exog = {c: cal.join(pops[c]) if c in pops else cal.copy() for c in wide}

    products = product_rows(sql, last_month)
    items = list(products.item_no)
    store_rows = months.groupby(["month", "store_no"], as_index=False).value.sum()
    p = Panel(series=wide, exog=exog, future_index=future, sql=sql, data_end=end, start="2016-01-01",
              labels={c: c for c in wide}, stores=store_list(store_rows, last_month), unknown_packs=unknown_packs(items))
    p.items, p.older, p.products = items, older_numbers(items), product_list(products)
    p.records, p.records_through = int(months.records.sum()), last_month
    return p, groups
