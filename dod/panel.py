"""Spec -> SQL -> monthly panel (one column per series) plus exogenous features.

The aggregation SQL is generated here from the spec, never written by the LLM, and it reads only the clean
warehouse: products by family (renumbered items joined), categories in today's taxonomy, one spelling per city."""
from dataclasses import dataclass, field

import pandas as pd

from . import db

# How each spec kind maps to SQL. Kinds and targets come from Literal types in spec.py, so these fragments never
# contain user text; codes travel as bind parameters.
# Products resolve to their member item numbers first (member_items), so every query filters on the indexed
# l.item_no; filtering through the item join would scan all 26M order lines.
PRODUCT_FILTER = {"item": "l.item_no = ANY(%(items)s)", "category": "l.item_no = ANY(%(items)s)",
                  "vendor": "l.vendor_no = ANY(%(product)s)", "all": "TRUE"}
REGION_FILTER = {"county": "s.county_fips = ANY(%(region)s)", "city": "s.city = ANY(%(region)s)",
                 "store": "l.store_no = ANY(%(region)s)", "statewide": "TRUE"}
SERIES_EXPR = {"none": "'total'", "county": "coalesce(s.county_name, '(no county)')", "city": "s.city",
               "item": "i.family_item_no", "category": "coalesce(i.category_current, '(none)')"}


@dataclass
class Panel:
    series: pd.DataFrame                  # index = month start, one column per series code
    exog: dict                            # series code -> DataFrame of features, covering history + horizon
    future_index: pd.DatetimeIndex
    sql: str
    data_end: pd.Timestamp
    start: str
    labels: dict = field(default_factory=dict)    # series code -> readable label
    pool: tuple = None                            # (companion series, their exog): same product in other counties


def member_items(spec):
    """Item numbers behind a product scope: every member of the named families, or every item in the categories."""
    col = {"item": "family_item_no", "category": "category_current"}.get(spec.product.kind)
    if col is None:
        return []
    return list(db.query(f"SELECT item_no FROM sales.item WHERE {col} = ANY(%s)", (spec.product.codes,)).item_no)


def build_sql(spec, items=None):
    params = {"product": spec.product.codes, "region": spec.region.codes, "start": spec.start,
              "items": items if items is not None else member_items(spec)}
    sql = f"""
SELECT date_trunc('month', l.ordered_on)::date AS month,
       {SERIES_EXPR[spec.series_by]} AS series,
       sum(l.{spec.target}) AS value
FROM sales.invoice_line l
JOIN sales.item i USING (item_no)
JOIN sales.store s USING (store_no)
WHERE {PRODUCT_FILTER[spec.product.kind]}
  AND {REGION_FILTER[spec.region.kind]}
  AND l.ordered_on >= %(start)s
GROUP BY 1, 2
ORDER BY 1, 2"""
    return sql, params


def data_end():
    """Last day with orders, and the start of the last complete month."""
    end = pd.Timestamp(db.query("SELECT max(last_order_on) AS d FROM sales.store").d[0])
    # a month is complete when orders reach its last business day
    last_bd = db.query("SELECT max(cal_date) AS d FROM ref.calendar WHERE is_business_day AND cal_date <= %s "
                       "AND date_trunc('month', cal_date) = date_trunc('month', %s::date)", (end, end)).d[0]
    month = end.to_period("M").to_timestamp()
    return end, (month if end >= pd.Timestamp(last_bd) else month - pd.offsets.MonthBegin(1))


def to_wide(df, start, last_month):
    idx = pd.date_range(start=pd.Timestamp(start).to_period("M").to_timestamp(), end=last_month, freq="MS")
    wide = df.pivot_table(index="month", columns="series", values="value", aggfunc="sum")
    wide.index = pd.to_datetime(wide.index)
    wide = wide.reindex(idx).fillna(0.0).rename_axis(None, axis=1)   # a month with no orders is a real zero
    # a series starts at its first sale: zeros before a product launched (or a store opened) are not demand
    for c in wide:
        first = wide[c].gt(0).idxmax() if wide[c].gt(0).any() else None
        if first is not None:
            wide.loc[wide.index < first, c] = float("nan")
    return wide


def labels_for(spec, codes):
    if spec.series_by == "item":
        df = db.query("SELECT item_no, item_desc, bottle_volume_ml FROM sales.item WHERE item_no = ANY(%s)", (list(codes),))
        return {r.item_no: f"{r.item_desc} {r.bottle_volume_ml} ml ({r.item_no})" for r in df.itertuples()}
    if spec.series_by == "category":
        df = db.query("SELECT category_code, category_name FROM sales.category WHERE category_code = ANY(%s)", (list(codes),))
        return {r.category_code: f"{r.category_name} ({r.category_code})" for r in df.itertuples()}
    if spec.series_by == "none":
        return {"total": f"{spec.product.label}, {spec.region.label}"}
    return {c: c.title() for c in codes}


def calendar_features(index):
    cal = db.query("""SELECT date_trunc('month', cal_date)::date AS month,
                             count(*) FILTER (WHERE is_business_day) AS business_days,
                             count(*) FILTER (WHERE holiday_name IS NOT NULL) AS holidays
                      FROM ref.calendar GROUP BY 1""")
    cal.index = pd.to_datetime(cal.month)
    out = cal.reindex(index)[["business_days", "holidays"]].astype(float)
    out.insert(0, "month_of_year", index.month.astype(float))
    return out


def population_features(spec, index, series_codes):
    """Yearly Census population for each series' area (the warehouse already carries the latest year forward)."""
    pop = db.query("SELECT p.county_fips, s.county_name, p.year, p.population FROM ref.county_population p "
                   "JOIN (SELECT DISTINCT county_fips, county_name FROM sales.store) s USING (county_fips)")
    if spec.region.kind == "county":
        pop = pop[pop.county_fips.isin(spec.region.codes)]
    elif spec.region.kind in ("city", "store"):
        col = "store_no" if spec.region.kind == "store" else "city"
        fips = db.query(f"SELECT DISTINCT county_fips FROM sales.store WHERE {col} = ANY(%s)", (spec.region.codes,))
        pop = pop[pop.county_fips.isin(fips.county_fips)]
    years = pd.Series(index.year, index=index)

    def series_for(frame):
        return years.map(frame.groupby("year").population.sum()).astype(float).rename("population")

    if spec.series_by == "county":
        return {code: series_for(pop[pop.county_name == code]) for code in series_codes}
    total = series_for(pop)
    return {code: total for code in series_codes}


N_COMPANIONS = 15


def companions(spec, start, last_month, exclude, items):
    """The same product in the busiest other counties, for the model to learn shared patterns from."""
    sql = f"""
SELECT date_trunc('month', l.ordered_on)::date AS month, 'pool: ' || s.county_name AS series, sum(l.{spec.target}) AS value
FROM sales.invoice_line l JOIN sales.item i USING (item_no) JOIN sales.store s USING (store_no)
WHERE {PRODUCT_FILTER[spec.product.kind]} AND l.ordered_on >= %(start)s AND s.county_name IS NOT NULL
GROUP BY 1, 2"""
    df = db.query(sql, {"product": spec.product.codes, "items": items, "start": start})
    if df.empty:
        return None
    recent = df[pd.to_datetime(df.month) >= last_month - pd.DateOffset(years=2)].groupby("series").value.sum()
    keep = [c for c in recent.sort_values(ascending=False).index if c.removeprefix("pool: ") not in exclude][:N_COMPANIONS]
    wide = to_wide(df[df.series.isin(keep)], start, last_month)
    return wide if len(wide.columns) else None


def build(spec):
    end, last_month = data_end()
    items = member_items(spec)
    sql, params = build_sql(spec, items)
    raw = db.query(sql, params)
    if raw.empty:
        raise ValueError("No sales match this product and region.")
    wide = to_wide(raw, spec.start, last_month)

    horizon_idx = pd.date_range(last_month + pd.offsets.MonthBegin(1), periods=spec.horizon, freq="MS")
    full_idx = wide.index.append(horizon_idx)
    cal = calendar_features(full_idx) if "calendar" in spec.features else pd.DataFrame(index=full_idx)
    pops = population_features(spec, full_idx, wide.columns) if "population" in spec.features else {}
    exog = {c: pd.concat([cal, pops[c]], axis=1) if c in pops else cal.copy() for c in wide}

    # companions: skip the counties that ARE the requested series (a single county, or a county breakout)
    exclude = set(wide.columns) if spec.series_by == "county" else set()
    if spec.region.kind == "county" and spec.series_by == "none" and len(spec.region.codes) == 1:
        exclude |= set(db.query("SELECT DISTINCT county_name FROM sales.store WHERE county_fips = %s",
                                (spec.region.codes[0],)).county_name)
    comp = companions(spec, spec.start, last_month, exclude, items)
    pool = None
    if comp is not None:
        comp_exog = {}
        if "population" in spec.features:
            pop = db.query("SELECT s.county_name, p.year, sum(p.population) AS population FROM ref.county_population p "
                           "JOIN (SELECT DISTINCT county_fips, county_name FROM sales.store) s USING (county_fips) "
                           "GROUP BY 1, 2")
        for c in comp:
            ex = cal.copy()
            if "population" in spec.features:
                by_year = pop[pop.county_name == c.removeprefix("pool: ")].set_index("year").population
                ex["population"] = pd.Series(full_idx.year, index=full_idx).map(by_year).astype(float)
            comp_exog[c] = ex
        pool = (comp, comp_exog)

    display_sql = sql
    params["items"] = params["items"] if len(params["items"]) <= 30 else params["items"][:30] + ["..."]
    for k, v in params.items():  # a readable copy for the dashboard; execution used bind parameters
        display_sql = display_sql.replace(f"%({k})s", repr(v) if not isinstance(v, list) else "ARRAY" + repr(v))
    return Panel(series=wide, exog=exog, future_index=horizon_idx, sql=display_sql.strip(), data_end=end,
                 start=spec.start, labels=labels_for(spec, wide.columns), pool=pool)
