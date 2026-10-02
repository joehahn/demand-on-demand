"""Model inputs beyond past sales, offered to model selection as groups (model.FEATURE_GROUPS); a group is kept only
if the model does better with it on the model-selection window. Each is known before the period it describes.

  season         sine and cosine of the time of year: a smooth yearly cycle a linear model can use
  holiday_weeks  1 if the week contains Thanksgiving, Christmas, New Year's Day or July 4th (weekly forecasts)
  stores         stores that ordered the product in the 12 months before the period; carried forward unchanged into
                 the forecast periods, so nothing from the future leaks in

Adopted for weekly forecasts after benchmark/feature_experiment.py (median error vs last year 0.857 -> 0.826).
"""
import numpy as np
import pandas as pd

from . import db

HOLIDAYS = {"thanksgiving_week": "Thanksgiving", "christmas_week": "Christmas", "new_year_week": "New Year",
            "july4_week": "Independence"}


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
        weeks = set(cal[cal.holiday_name.str.contains(name, case=False)].week)
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


def stores(store_rows, index, last_period):
    """Active stores on any grain: each period takes its month's value (counted from the 12 months before that
    month), and periods past the last complete one keep the last value. store_rows: month, store_no (orders > 0)."""
    rows = store_rows.assign(month=pd.to_datetime(store_rows.month))
    months = pd.date_range(rows.month.min(), pd.Timestamp(last_period).to_period("M").to_timestamp(), freq="MS")
    act = active_stores(rows, months)
    return pd.Series([act.get(min(pd.Timestamp(d).to_period("M").to_timestamp(), months[-1]), act.iloc[-1])
                      for d in index], index=index, name="active_stores")
