"""Report periods: the models forecast weeks or months, and fixed code adds them up into the period the request asked
for (temporal aggregation). One rule for every request:

  requested    model at   period size   calendar-aligned
  week         weeks      1             -
  fortnight    weeks      2             no: fortnights start with the first week forecast
  month        months     1             -
  quarter      months     3             yes: Q1 to Q4, starting with the quarter in progress
  half         months     6             yes: H1 and H2, starting with the half in progress
  year         months     12            no: the next 12 months (a calendar year ahead would need forecasts up to 16
                                        months out, further than can be tested honestly)

A calendar period in progress is reported as the months already sold plus the months still to come. The models look
at most 12 months (52 weeks) ahead, so a request may stop short; the page says so. Each period's 80% range comes from
the Testing period: forecasts made there are added up over the same steps ahead, compared with what actually sold, and
the middle 80% of those misses is applied to the period's forecast.
"""
import numpy as np
import pandas as pd

# requested grain -> (model grain, periods of the model grain per period, calendar-aligned)
PERIODS = {"week": ("week", 1, False), "fortnight": ("week", 2, False), "month": ("month", 1, False),
           "quarter": ("month", 3, True), "half": ("month", 6, True), "year": ("month", 12, False)}
MAX_STEPS = {"week": 52, "month": 12}
NAMES = {"fortnight": "fortnight", "quarter": "quarter", "half": "half-year", "year": "year"}


def steps_needed(grain, horizon, last_month):
    """(model grain, steps of the model grain left in the period in progress, full periods that fit, steps to forecast)."""
    model_grain, size, aligned = PERIODS[grain]
    left = (size - 1) - (pd.Timestamp(last_month).month - 1) % size if aligned else 0
    fit = min(horizon, (MAX_STEPS[model_grain] - left) // size)
    return model_grain, left, fit, left + size * fit


def label(grain, first, last):
    """A period's name: 'Q3 2026', 'H2 2026', 'Sep 2026 to Aug 2027' or 'Aug 31 to Sep 13, 2026'."""
    first, last = pd.Timestamp(first), pd.Timestamp(last)
    if grain == "quarter":
        return f"Q{first.quarter} {first.year}"
    if grain == "half":
        return f"H{1 if first.month <= 6 else 2} {first.year}"
    if grain == "fortnight":
        end = last + pd.Timedelta(days=6)
        return f"{first:%b} {first.day} to {end:%b} {end.day}, {end.year}"
    return f"{first:%b %Y} to {last:%b %Y}"


def blocks(grain, index):
    """Model periods (weeks or months, oldest first) -> period start for each, for the history chart: calendar periods
    for quarters and halves, and blocks counted back from the latest period for fortnights and years."""
    _, size, aligned = PERIODS[grain]
    index = pd.DatetimeIndex(index)
    if aligned:
        return [pd.Timestamp(d.year, (d.month - 1) // size * size + 1, 1) for d in index]
    back = np.arange(len(index))[::-1] // size   # 0 for the latest block
    first = {b: index[(back == b).nonzero()[0][0]] for b in set(back)}
    return [first[b] for b in back]


def table(grain, wide, res, left, fit):
    """One row per reported period: sold so far, forecast, total, 80% range, the same period last year (all series
    added up)."""
    model_grain, size, aligned = PERIODS[grain]
    step = pd.tseries.frequencies.to_offset("W-MON" if model_grain == "week" else "MS")
    year_back = 52 if model_grain == "week" else 12
    fc = res["forecast"].groupby("month").pred.sum()
    total = wide.sum(axis=1, min_count=1)
    bt = res["backtest"].dropna(subset=["actual", "pred"]).groupby(["origin", "step"])[["pred", "actual"]].sum()
    parts = ([("in progress", range(1, left + 1))] if left else []) + \
            [("forecast", range(left + size * k + 1, left + size * k + size + 1)) for k in range(fit)]
    rows = []
    for status, steps in parts:
        ahead = [fc.index[s - 1] for s in steps]
        if status == "in progress":   # the whole calendar period: months already sold, then the ones forecast
            start = pd.Timestamp(ahead[-1]) - (size - 1) * step
            span = pd.date_range(start, periods=size, freq=step)
        else:
            span = pd.DatetimeIndex(ahead)
        sold = float(total.reindex([m for m in span if m not in ahead]).sum())
        pred = float(fc.loc[ahead].sum())
        # the Testing period's misses over the same steps ahead, added up
        b = bt[bt.index.get_level_values("step").isin(list(steps))].groupby("origin").agg(
            pred=("pred", "sum"), actual=("actual", "sum"), n=("pred", "size"))
        b = b[(b.n == len(steps)) & (b.pred > 0)]
        rel = (b.actual - b.pred) / b.pred
        lo, hi = (rel.quantile(0.1), rel.quantile(0.9)) if len(rel) else (np.nan, np.nan)
        last_year = span - year_back * step
        ly = float(total.reindex(last_year).sum()) if set(last_year) <= set(total.index) else np.nan
        rows.append({"period": label(grain, span[0], span[-1]), "status": status, "first": span[0], "last": span[-1],
                     "span": f"{span[0]:%b %Y}" if size == 1 else label("year" if model_grain == "month" else "fortnight",
                                                                         span[0], span[-1]),
                     "sold": sold, "forecast": pred, "total": sold + pred,
                     "low": sold + max(pred * (1 + lo), 0), "high": sold + pred * (1 + hi), "last_year": ly})
    return pd.DataFrame(rows)
