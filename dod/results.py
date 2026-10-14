"""A forecast's saved results as tidy tables, for custom charts and follow-up questions about a forecast already made.

    from dod.results import load, latest
    r = load(latest())          # the newest forecast in out/ (or load("out/<slug>"))
    r.actual    # one row per period and series: period, series, value (actual sales)
    r.forecast  # one row per period and series: period, series, forecast, low, high (80% range)
    r.title, r.unit, r.grain, r.dashboard

Custom charts use exactly the numbers on the dashboard: nothing is re-forecast or re-queried.
"""
import pickle
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent.parent / "out"


@dataclass
class Results:
    title: str
    unit: str
    grain: str
    actual: pd.DataFrame
    forecast: pd.DataFrame
    dashboard: str


def latest():
    """The folder of the most recent forecast in out/."""
    return max((p.parent for p in OUT.glob("*/page.pkl")), key=lambda p: (p / "page.pkl").stat().st_mtime)


def load(folder):
    folder = Path(folder)
    page = pickle.loads((folder / "page.pkl").read_bytes())
    spec, panel, res = page["spec"], page["panel"], page["res"]
    names = panel.labels
    actual = (panel.series.rename(columns=names).rename_axis("period").reset_index()
              .melt(id_vars="period", var_name="series", value_name="value").dropna(subset=["value"]))
    fc = res["forecast"].rename(columns={"month": "period", "pred": "forecast", "lo": "low", "hi": "high"})
    fc["series"] = fc.series.map(lambda c: names.get(c, c))
    return Results(spec.title, spec.target.replace("sales_", ""), spec.grain, actual,
                   fc[["period", "series", "forecast", "low", "high"]], str(folder / "dashboard.html"))
