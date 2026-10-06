"""Model inputs beyond past sales, offered to model selection as groups (model.FEATURE_GROUPS); a group is kept only
if the model does better with it on the model-selection window. Each is known before the period it describes.

  calendar       month of year, business days and federal holidays in the period (monthly and quarterly forecasts)
  population     Census population of the counties where the series' stores are (monthly and quarterly forecasts)
  season         sine and cosine of the time of year: a smooth yearly cycle a linear model can use (weekly)
  holiday_weeks  1 if the week contains Thanksgiving, Christmas, New Year's Day or July 4th (weekly)
  stores         stores that ordered the product in the 12 months before the period, counted one forecast horizon
                 earlier, so every value is known when the forecast is made, in backtests too (weekly)

Which grain gets which inputs follows the benchmarks: calendar and population for months (benchmark/pooling.md: without
them 13 of 30 forecasts beat last year instead of 20), season, holiday weeks and stores for weeks
(benchmark/features.md: median error vs last year 0.857 -> 0.826).
"""
import numpy as np
import pandas as pd

from . import db

GROUPS = {"week": ["season", "holiday_weeks", "stores"], "month": ["calendar", "population"],
          "quarter": ["calendar", "population"]}
# exact names in ref.calendar: the holiday itself, not the "(observed)" day off, and not Juneteenth (whose official name,
# "Juneteenth National Independence Day", also contains "Independence")
HOLIDAYS = {"thanksgiving_week": "Thanksgiving Day", "christmas_week": "Christmas Day", "new_year_week": "New Year's Day",
            "july4_week": "Independence Day"}


def season(index):
    """Sine and cosine of the time of year, at the middle of each period."""
    index = pd.DatetimeIndex(index)
    mid = 14 if (index.freqstr or pd.infer_freq(index) or "").startswith("M") else 3
    t = 2 * np.pi * (index.dayofyear + mid) / 365.25
    return pd.DataFrame({"season_sin": np.sin(t), "season_cos": np.cos(t)}, index=index)


def holiday_weeks(index):
    """For weeks (by their Monday): 1 if the week contains one of the four big holidays."""
    cal = db.query("SELECT cal_date, holiday_name FROM ref.calendar WHERE holiday_name IS NOT NULL")
    day = pd.to_datetime(cal.cal_date)
    cal["week"] = day - pd.to_timedelta(day.dt.weekday, unit="D")
    out = pd.DataFrame(0.0, index=index, columns=list(HOLIDAYS))
    for col, name in HOLIDAYS.items():
        weeks = set(cal[cal.holiday_name == name].week)
        out[col] = [1.0 if w in weeks else 0.0 for w in index]
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
