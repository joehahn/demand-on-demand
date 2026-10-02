"""Experiment: new model inputs, offered to model selection like the existing ones.

    python benchmark/feature_experiment.py            # monthly and weekly, the benchmark's 30 forecasts (about an hour)
    python benchmark/feature_experiment.py --n 3      # a quick smoke test

For each benchmark forecast (benchmark/run_benchmark.sample_specs, seed 0), at two grains:
  monthly  A: today's inputs (calendar, population)      B: A + season + stores
  weekly   A: no inputs (today's on-the-fly path)        B: season + holiday weeks + stores
New inputs (each a group that model selection keeps only if it helps on the model-selection window):
  season         sine and cosine of the time of year (a smooth yearly cycle; a linear model cannot use a 1-12 month number well)
  holiday_weeks  1 if the week contains Thanksgiving, Christmas, New Year's Day or July 4th (weekly only)
  stores         stores that ordered the product in the 12 months before the period (known in advance; carried forward
                 unchanged into the forecast periods, so nothing from the future leaks in)
Scored like the harness: error relative to the same period last year on the test window. No LLM calls. Writes
benchmark/features.csv and benchmark/features.md.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import db, model, panel  # noqa: E402
from run_benchmark import sample_specs  # noqa: E402

HERE = Path(__file__).parent
HOLIDAYS = {"thanksgiving_week": "Thanksgiving", "christmas_week": "Christmas", "new_year_week": "New Year",
            "july4_week": "Independence"}


def store_months(spec, last_month):
    """Per-store monthly volume for the product, statewide with county, through the last complete month."""
    items = panel.member_items(spec)
    sql = f"""
SELECT date_trunc('month', l.ordered_on)::date AS month, s.county_name AS county, l.store_no, sum(l.{spec.target}) AS v
FROM sales.invoice_line l JOIN sales.item i USING (item_no) JOIN sales.store s USING (store_no)
WHERE {panel.PRODUCT_FILTER[spec.product.kind]} AND l.ordered_on >= %(start)s AND l.ordered_on < %(end)s
GROUP BY 1, 2, 3"""
    df = db.query(sql, {"product": spec.product.codes, "items": items, "start": spec.start,
                        "end": last_month + pd.offsets.MonthBegin(1)})
    df["month"] = pd.to_datetime(df.month)
    return df[df.v > 0]


def active_stores(rows, months):
    """For each month: stores with orders in the 12 months before it (not including it)."""
    by_month = rows.groupby("month").store_no.apply(set)
    out = []
    for m in months:
        window = by_month[(by_month.index < m) & (by_month.index >= m - pd.DateOffset(months=12))]
        out.append(float(len(set().union(*window))) if len(window) else 0.0)
    return pd.Series(out, index=months)


def season(index):
    t = 2 * np.pi * (pd.Index(index).dayofyear + (14 if index.freqstr == "MS" else 3)) / 365.25  # mid-period
    return pd.DataFrame({"season_sin": np.sin(t), "season_cos": np.cos(t)}, index=index)


def holiday_weeks(index):
    cal = db.query("SELECT cal_date, holiday_name FROM ref.calendar WHERE holiday_name IS NOT NULL")
    cal["week"] = pd.to_datetime(cal.cal_date) - pd.to_timedelta(pd.to_datetime(cal.cal_date).dt.weekday, unit="D")
    out = pd.DataFrame(0.0, index=index, columns=list(HOLIDAYS))
    for col, name in HOLIDAYS.items():
        weeks = set(cal[cal.holiday_name.str.contains(name, case=False)].week)
        out[col] = [1.0 if w in weeks else 0.0 for w in index]
    return out


def region_rows(rows, spec):
    """Store rows inside the forecast's region (statewide or one county)."""
    if spec.region.kind == "statewide":
        return rows
    names = set(db.query("SELECT DISTINCT county_name FROM sales.store WHERE county_fips = ANY(%s)",
                         (spec.region.codes,)).county_name)
    return rows[rows.county.isin(names)]


def add_stores(exog, idx_full, rows, last_period, grain):
    """Active stores as an input: computed by month, mapped onto the grain (a week takes its previous month's
    value), carried forward unchanged past the last complete period."""
    months = pd.date_range(rows.month.min(), last_period.to_period("M").to_timestamp(), freq="MS")
    act = active_stores(rows, months)
    keyed = pd.Series([act.get(min(d.to_period("M").to_timestamp(), months[-1]), act.iloc[-1]) for d in idx_full],
                      index=idx_full)
    return exog.assign(active_stores=keyed.values)


def monthly_case(spec, rows, last_month, only=None):
    p = panel.build(spec)
    idx = p.series.index.append(p.future_index)
    season_df = season(pd.date_range(idx[0], idx[-1], freq="MS"))
    for c in p.series:
        p.exog[c] = add_stores(p.exog[c].join(season_df), idx, region_rows(rows, spec), p.series.index[-1], "month")
    if p.pool is not None:   # the pooled counties get the same inputs, each from its own stores
        comp, comp_exog = p.pool
        for c in comp:
            r = rows[rows.county == c.removeprefix("pool: ")]
            comp_exog[c] = add_stores(comp_exog[c].join(season_df), idx, r if len(r) else rows, p.series.index[-1], "month")
    out = {}
    for name, groups in (("A", list(spec.features)), ("B", list(spec.features) + ["season", "stores"])):
        if only and name != only:
            continue
        res = model.run(p.series, p.exog, p.future_index, spec.horizon, groups, log=lambda *a: None, pool=p.pool)
        out[name] = (res["test_rel_mae"], res["feature_groups"])
    return out


def weekly_case(spec, rows, end, only=None):
    sql, params = panel.build_sql(spec)
    raw = db.query(sql.replace("date_trunc('month', l.ordered_on)::date AS month", "l.ordered_on AS day")
                   .replace("GROUP BY 1, 2, 3\nORDER BY 1, 2, 3", "GROUP BY 1, 2, 3"), params)
    from dod.onthefly import bucket
    daily = raw.groupby(["day", "series"], as_index=False).value.sum()
    wide = bucket(daily, "week", end)
    steps = min(spec.horizon * 4, 52)   # the same span ahead, in weeks
    step = pd.tseries.frequencies.to_offset("W-MON")
    fut = pd.date_range(wide.index[-1] + step, periods=steps, freq=step)
    idx = wide.index.append(fut)
    feats = season(pd.DatetimeIndex(idx, freq="W-MON")).join(holiday_weeks(idx))
    exog = {c: add_stores(feats.copy(), idx, region_rows(rows, spec), wide.index[-1], "week") for c in wide}
    out = {}
    with model.use_grain("week"):
        for name, groups in (("A", []), ("B", ["season", "holiday_weeks", "stores"])):
            if only and name != only:
                continue
            res = model.run(wide, exog, fut, steps, groups, log=lambda *a: None)
            out[name] = (res["test_rel_mae"], res["feature_groups"])
    return out


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    end, last_month = panel.data_end()
    results = []
    for spec in sample_specs(n):
        t0 = time.time()
        row = {"forecast": spec.title}
        try:
            rows = store_months(spec, last_month)
            m = monthly_case(spec, rows, last_month)
            w = weekly_case(spec, rows, end)
            row.update(month_A=m["A"][0], month_B=m["B"][0], month_kept=",".join(m["B"][1]) or "none",
                       week_A=w["A"][0], week_B=w["B"][0], week_kept=",".join(w["B"][1]) or "none")
        except Exception as e:   # too little history etc. is a result, not a crash
            row["error"] = str(e)[:120]
        results.append(row)
        print(f"  {time.time() - t0:4.0f}s  {row.get('month_A', float('nan')):.3f}->{row.get('month_B', float('nan')):.3f}"
              f"  week {row.get('week_A', float('nan')):.3f}->{row.get('week_B', float('nan')):.3f}"
              f"  kept: {row.get('month_kept', '')} | {row.get('week_kept', '')}  {spec.title}", flush=True)
    df = pd.DataFrame(results)
    df.to_csv(HERE / "features.csv", index=False)
    ok = df.dropna(subset=["month_A", "week_A"])
    md = ["# Experiment: new model inputs (season, holiday weeks, active stores)\n",
          "Each new input group is offered to model selection, which keeps it only if it helps on the model-selection",
          "window; scored on the test window as error relative to the same period last year (below 1 beats it).\n"]
    for g in ("month", "week"):
        a, b = ok[f"{g}_A"], ok[f"{g}_B"]
        md += [f"**{g}ly** ({len(ok)} forecasts): beat last year {(a < 1).sum()} -> {(b < 1).sum()}; median {a.median():.3f} -> "
               f"{b.median():.3f}; better on {(b < a - 1e-9).sum()}, worse on {(b > a + 1e-9).sum()}, unchanged on "
               f"{(abs(b - a) <= 1e-9).sum()}.\n"]
    md += ["| forecast | month A | month B | kept | week A | week B | kept |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r.forecast} | {r.month_A:.3f} | {r.month_B:.3f} | {r.month_kept} | {r.week_A:.3f} | {r.week_B:.3f} | "
           f"{r.week_kept} |" for r in ok.itertuples()]
    (HERE / "features.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[3:5]))
