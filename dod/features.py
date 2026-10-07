"""Model inputs beyond past sales: the same menu for every forecast, weekly or monthly. Each group is offered to
model selection (model.FEATURE_GROUPS) and kept only if the forecast is better with it. Each is known before the
period it describes.

  season       time of year: the sine and cosine of the date, so the input repeats smoothly each year. Ridge
               regression sees these; LightGBM sees the month number instead (model.LGBM_MONTH)
  calendar     business days in the period, and four flags: Thanksgiving, Christmas, New Year's Day or July 4th falls in
               the period
  population   Census population of the counties where the series' stores are
  stores       stores that ordered the product in the 12 months before the period, counted one forecast horizon
               earlier, so every value is known when the forecast is made, in backtests too

One menu, and ridge with sine and cosine while LightGBM gets the month number, after benchmark/menu.md (vs the earlier
per-grain menus: monthly better on 21 of 30 forecasts, mean error vs last year 0.952 -> 0.913; weekly better on 16,
worse on 10, median 0.833 both).
"""
import numpy as np
import pandas as pd

from . import db

GROUPS = ["season", "calendar", "population", "stores"]   # offered to every forecast
# exact names in ref.calendar: the holiday itself, not the "(observed)" day off, and not Juneteenth (whose official name,
# "Juneteenth National Independence Day", also contains "Independence")
HOLIDAYS = {"thanksgiving": "Thanksgiving Day", "christmas": "Christmas Day", "new_year": "New Year's Day",
            "july4": "Independence Day"}


def season(index):
    """Sine and cosine of the time of year, at the middle of each period."""
    index = pd.DatetimeIndex(index)
    mid = 14 if (index.freqstr or pd.infer_freq(index) or "").startswith("M") else 3
    t = 2 * np.pi * (index.dayofyear + mid) / 365.25
    return pd.DataFrame({"season_sin": np.sin(t), "season_cos": np.cos(t)}, index=index)


def holidays(index, grain):
    """1 if the holiday (its actual day) falls in the period: a week (by its Monday) or a month."""
    cal = db.query("SELECT cal_date, holiday_name FROM ref.calendar WHERE holiday_name IS NOT NULL")
    day = pd.to_datetime(cal.cal_date)
    cal["period"] = (day - pd.to_timedelta(day.dt.weekday, unit="D")) if grain == "week" else \
        day.dt.to_period("M").dt.start_time
    out = pd.DataFrame(0.0, index=index, columns=list(HOLIDAYS))
    for col, name in HOLIDAYS.items():
        periods = set(cal[cal.holiday_name == name].period)
        out[col] = [1.0 if p in periods else 0.0 for p in index]
    return out


def active_stores(store_rows, months):
    """For each month: stores with orders in the 12 months before it (not including it)."""
    by_month = store_rows.groupby("month").store_no.apply(set)
    out = []
    for m in months:
        window = by_month[(by_month.index < m) & (by_month.index >= m - pd.DateOffset(months=12))]
        out.append(float(len(set().union(*window))) if len(window) else 0.0)
    return pd.Series(out, index=months)


def stores(store_rows, index, lag):
    """Active stores on any grain, shifted back by the forecast horizon (lag): each period takes the count for the month
    `lag` before it (stores with orders in the 12 months before that month). So every value a forecast uses was known
    when the forecast was made, in backtests too: without the shift, a backtest's later periods would count orders
    placed after its starting point. store_rows: month, store_no (orders > 0)."""
    rows = store_rows.assign(month=pd.to_datetime(store_rows.month))
    months = pd.date_range(rows.month.min(), rows.month.max() + pd.offsets.MonthBegin(1), freq="MS")
    act = active_stores(rows, months)
    when = [(pd.Timestamp(d) - lag).to_period("M").to_timestamp() for d in index]
    return pd.Series([act.get(m, 0.0) for m in when], index=index, name="active_stores")


def calendar(index, grain):
    """Month of year (of the period's first day), business days and federal holidays in each period."""
    days = db.query("SELECT cal_date, is_business_day, holiday_name IS NOT NULL AS holiday FROM ref.calendar")
    day = pd.to_datetime(days.cal_date)
    start = {"week": day - pd.to_timedelta(day.dt.weekday, unit="D"),
             "quarter": day.dt.to_period("Q").dt.start_time}.get(grain, day.dt.to_period("M").dt.start_time)
    per = days.assign(period=start.dt.normalize()).groupby("period")[["is_business_day", "holiday"]].sum()
    out = per.reindex(pd.DatetimeIndex(index)).astype(float).set_axis(["business_days", "holidays"], axis=1)
    out.insert(0, "month_of_year", pd.DatetimeIndex(index).month.astype(float))
    return out


def population(store_rows, index):
    """For each series: the yearly Census population of the counties its stores are in (stores with no county are
    skipped; the warehouse carries the latest year forward). store_rows: series, store_no."""
    counties = db.query("SELECT store_no, county_fips FROM sales.store WHERE county_fips IS NOT NULL")
    pop = db.query("SELECT county_fips, year, population FROM ref.county_population")
    years = pd.Series(pd.DatetimeIndex(index).year, index=index)
    where = store_rows[["series", "store_no"]].drop_duplicates().merge(counties, on="store_no")
    out = {}
    for name, g in where.groupby("series"):
        by_year = pop[pop.county_fips.isin(set(g.county_fips))].groupby("year").population.sum()
        out[name] = years.map(by_year).astype(float).rename("population")
    return out
