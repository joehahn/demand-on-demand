"""Spec -> SQL -> monthly panel (one column per series) plus exogenous features.

All aggregation SQL is generated here from the spec, never written by the LLM, so every forecast is
built the same auditable way. Each mitigation that changes the data is logged with a before/after copy
of the affected series for the dashboard."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import db, register

# How each spec kind maps to SQL. Targets and kinds come from Literal types in spec.py, so these
# fragments never contain user text; codes and mappings travel as bind parameters.
PRODUCT_FILTER = {"item": "l.item_no = ANY(%(product)s)", "category": "l.category_code = ANY(%(product)s)",
                  "vendor": "l.vendor_no = ANY(%(product)s)", "all": "TRUE"}
REGION_FILTER = {"county": "s.county_fips = ANY(%(region)s)", "city": "{city} = ANY(%(region)s)",
                 "store": "l.store_no = ANY(%(region)s)", "statewide": "TRUE"}
SERIES_EXPR = {"none": "'total'", "county": "coalesce(s.county_name, '(no county)')", "city": "{city}",
               "item": "{item}", "category": "coalesce(l.category_code, '(none)')"}


@dataclass
class Panel:
    series: pd.DataFrame                  # index = month start, one column per series label
    exog: dict                            # series label -> DataFrame of features, covering history + horizon
    future_index: pd.DatetimeIndex
    sql: str
    data_end: pd.Timestamp
    start: str
    changes: list = field(default_factory=list)   # mitigation log: rule, series, note, before/after
    actuals: pd.DataFrame = None          # the series before outlier caps: what forecasts are scored against
    labels: dict = field(default_factory=dict)    # series code -> readable label


def _case(expr, mapping, prefix, params):
    """CASE expression mapping variant values to canonical ones, with bind parameters."""
    if not mapping:
        return expr
    whens = []
    for n, (src, dst) in enumerate(mapping.items()):
        params[f"{prefix}_src{n}"], params[f"{prefix}_dst{n}"] = src, dst
        whens.append(f"WHEN %({prefix}_src{n})s THEN %({prefix}_dst{n})s")
    return f"CASE {expr} {' '.join(whens)} ELSE {expr} END"


def build_sql(spec, start, sql_mitigations=True):
    params = {"product": spec.product.codes, "region": spec.region.codes, "start": start}
    city_map, item_map = {}, {}
    if sql_mitigations:
        for m in spec.mitigations:
            if m.rule == "normalize_values" and m.params.get("column") == "city":
                city_map.update(m.params["mapping"])
            if m.rule == "stitch_successor" and m.params.get("column", "item_no") == "item_no":
                item_map[str(m.params["from"])] = str(m.params["to"])
    city = _case("s.city", city_map, "city", params)
    item = _case("l.item_no", item_map, "item", params)
    series = SERIES_EXPR[spec.series_by].format(city=city, item=item)
    sql = f"""
SELECT date_trunc('month', l.ordered_on)::date AS month,
       {series} AS series,
       sum(l.{spec.target}) AS value
FROM sales.invoice_line l
JOIN sales.store s USING (store_no)
WHERE {PRODUCT_FILTER[spec.product.kind]}
  AND {REGION_FILTER[spec.region.kind].format(city=city)}
  AND l.ordered_on >= %(start)s
  AND l.sales_bottles > 0 AND l.sales_dollars > 0   -- register: zero_value_lines
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
    # a month with no orders in scope is a real zero, not missing
    return wide.reindex(idx).fillna(0.0).rename_axis(None, axis=1)


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


def cap_outliers(s, k=5.0):
    """Cap months more than k robust deviations from a centered 13-month median."""
    level = s.rolling(13, center=True, min_periods=7).median()
    resid = s - level
    mad = 1.4826 * np.nanmedian(np.abs(resid - np.nanmedian(resid)))
    if not mad:
        return s
    return s.clip(lower=level - k * mad, upper=level + k * mad).fillna(s)


def calendar_features(index):
    cal = db.query("""SELECT date_trunc('month', cal_date)::date AS month, count(*) FILTER (WHERE is_business_day) AS business_days,
                             count(*) FILTER (WHERE holiday_name IS NOT NULL) AS holidays
                      FROM ref.calendar GROUP BY 1""")
    cal.index = pd.to_datetime(cal.month)
    out = cal.reindex(index)[["business_days", "holidays"]].astype(float)
    out.insert(0, "month_of_year", index.month.astype(float))
    return out


def population_features(spec, index, series_codes):
    """Yearly Census population for each series' area, latest year carried forward (register: reference_data_lag)."""
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
        by_year = frame.groupby("year").population.sum()
        filled = by_year.reindex(range(by_year.index.min(), index.year.max() + 1)).ffill()
        return years.map(filled).astype(float).rename("population")

    if spec.series_by == "county":
        return {code: series_for(pop[pop.county_name == code]) for code in series_codes}
    total = series_for(pop)
    return {code: total for code in series_codes}


def build(spec, decisions):
    start = register.start_date(spec, decisions)
    end, last_month = data_end()
    sql, params = build_sql(spec, start)
    raw = db.query(sql, params)
    if raw.empty:
        raise ValueError("No sales match this product and region.")
    wide = to_wide(raw, start, last_month)
    changes = []

    # before/after for request-level fixes applied inside the SQL
    if any(m.rule in ("stitch_successor", "normalize_values") for m in spec.mitigations):
        sql0, params0 = build_sql(spec, start, sql_mitigations=False)
        before = to_wide(db.query(sql0, params0), start, last_month)
        for m in spec.mitigations:
            if m.rule in ("stitch_successor", "normalize_values"):
                changes.append({"rule": m.rule, "source": m.source, "params": m.params, "note": m.reason,
                                "before": before, "after": wide})

    # post-aggregation fixes: per-series start dates, dropped series, outlier caps
    for m in spec.mitigations:
        if m.rule == "exclude_series":
            dropped = [c for c in m.params.get("series", []) if c in wide]
            wide = wide.drop(columns=dropped)
            changes.append({"rule": m.rule, "source": m.source, "params": m.params, "note": m.reason})
        if m.rule == "min_date" and "series" in m.params:
            for c in m.params["series"]:
                if c in wide:
                    before = wide[c].copy()
                    wide.loc[wide.index < pd.Timestamp(m.params["date"]), c] = np.nan
                    changes.append({"rule": m.rule, "source": m.source, "params": m.params, "note": m.reason,
                                    "series": c, "before": before, "after": wide[c].copy()})
    actuals = wide.copy()  # caps below change model inputs only, never the numbers the model is judged on
    caps = [d for d in decisions if d["rule"] == "cap_outliers" and d["action"] == "applied"]
    caps += [{"params": m.params, "issue_id": None, "source": m.source} for m in spec.mitigations if m.rule == "cap_outliers"]
    for cap in caps[:1]:  # one cap pass, whichever source asked for it
        for c in wide:
            before = wide[c].copy()
            wide[c] = cap_outliers(wide[c], cap["params"].get("k", 5))
            n = int((before.round(6) != wide[c].round(6)).sum())
            if n:
                changes.append({"rule": "cap_outliers", "source": cap.get("source", "register"), "series": c,
                                "params": cap["params"], "note": f"{n} month(s) capped", "before": before,
                                "after": wide[c].copy()})

    horizon_idx = pd.date_range(last_month + pd.offsets.MonthBegin(1), periods=spec.horizon, freq="MS")
    full_idx = wide.index.append(horizon_idx)
    exog = {}
    cal = calendar_features(full_idx) if "calendar" in spec.features else pd.DataFrame(index=full_idx)
    pops = population_features(spec, full_idx, wide.columns) if "population" in spec.features else {}
    for c in wide:
        exog[c] = pd.concat([cal, pops[c]], axis=1) if c in pops else cal.copy()

    display_sql = sql
    for k, v in params.items():  # a readable copy for the dashboard; execution used bind parameters
        display_sql = display_sql.replace(f"%({k})s", repr(v) if not isinstance(v, list) else "ARRAY" + repr(v))
    return Panel(series=wide, exog=exog, future_index=horizon_idx, sql=display_sql.strip(), data_end=end,
                 start=start, changes=changes, labels=labels_for(spec, wide.columns), actuals=actuals)
