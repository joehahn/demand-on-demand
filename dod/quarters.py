"""Quarterly requests: the models forecast months, and fixed code adds them up into calendar quarters for the page.

The data rarely ends on a quarter's last day, so the quarter in progress is reported as months already sold plus the
months still to come, followed by the next full quarters. The models look at most 12 months ahead, so "the next 4
quarters" may stop one quarter short when the data ends mid-quarter; the page says so.

Each quarter's 80% range comes from the Testing period: the forecasts made there are added up over the same months
ahead, compared with what actually sold, and the middle 80% of those misses is applied to the quarter's forecast.
"""
import numpy as np
import pandas as pd

MAX_MONTHS = 12


def months_needed(last_month, quarters):
    """(months left in the quarter in progress, full quarters that fit, months to forecast) after last_month."""
    left = 2 - (pd.Timestamp(last_month).month - 1) % 3     # e.g. data through August: September is left
    fit = min(quarters, (MAX_MONTHS - left) // 3)
    return left, fit, left + 3 * fit


def label(d):
    d = pd.Timestamp(d)
    return f"Q{d.quarter} {d.year}"


def table(wide, res, left, fit):
    """One row per quarter: sold so far, forecast, total, 80% range and the same quarter last year (all series added
    up)."""
    fc = res["forecast"].groupby("month").pred.sum()
    total = wide.sum(axis=1, min_count=1)
    bt = res["backtest"].dropna(subset=["actual", "pred"]).groupby(["origin", "step"])[["pred", "actual"]].sum()
    rows = []
    blocks = ([("in progress", range(1, left + 1))] if left else []) + \
             [("forecast", range(left + 3 * k + 1, left + 3 * k + 4)) for k in range(fit)]
    for status, steps in blocks:
        months = [fc.index[s - 1] for s in steps]
        start = pd.Timestamp(months[0]).to_period("Q").start_time
        in_q = pd.date_range(start, periods=3, freq="MS")
        sold = float(total.reindex([m for m in in_q if m not in months]).sum()) if status == "in progress" else 0.0
        pred = float(fc.loc[months].sum())
        # the Testing period's misses over the same months ahead, added up
        b = bt[bt.index.get_level_values("step").isin(list(steps))].groupby("origin").agg(
            pred=("pred", "sum"), actual=("actual", "sum"), n=("pred", "size"))
        b = b[(b.n == len(steps)) & (b.pred > 0)]
        rel = (b.actual - b.pred) / b.pred
        lo, hi = (rel.quantile(0.1), rel.quantile(0.9)) if len(rel) else (np.nan, np.nan)
        last_year = in_q - pd.DateOffset(years=1)
        ly = float(total.reindex(last_year).sum()) if set(last_year) <= set(total.index) else np.nan
        rows.append({"quarter": label(start), "status": status,
                     "months": f"{in_q[0]:%b}–{in_q[-1]:%b %Y}",
                     "sold": sold, "forecast": pred, "total": sold + pred,
                     "low": sold + max(pred * (1 + lo), 0), "high": sold + pred * (1 + hi), "last_year": ly})
    return pd.DataFrame(rows)
