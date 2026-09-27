"""Run one forecast request end to end.

    python -m dod.run specs/titos_polk.json [more specs...]

Writes out/<slug>/: dashboard.html, forecast.csv, backtest.csv, summary.json."""
import json
import sys
import time
from pathlib import Path

import pandas as pd

from . import dashboard, model, panel
from .spec import load

OUT = Path(__file__).parent.parent / "out"


def facts_for(spec, p, res):
    """The numbers the narrator may use, and nothing else."""
    fc, wide = res["forecast"], p.series
    last_year = {f"{m:%Y-%m}": float(sum(wide.at[m - pd.DateOffset(years=1), c] for c in fc.series.unique()
                                         if (m - pd.DateOffset(years=1)) in wide.index))
                 for m in sorted(fc.month.unique())}
    by_month = {f"{m:%Y-%m}": float(v) for m, v in fc.groupby("month").pred.sum().items()}
    pct = lambda a, b: f"{(a / b - 1) * 100:+.0f}%" if b else "n/a"
    return {"title": spec.title, "unit": spec.target.replace("sales_", ""),
            "forecast_total": round(sum(by_month.values())), "same_months_last_year_total": round(sum(last_year.values())),
            "change_vs_last_year_total": pct(sum(by_month.values()), sum(last_year.values())),
            "by_month": [{"month": k, "forecast": round(v), "same_month_last_year": round(last_year[k]),
                          "change": pct(v, last_year[k])} for k, v in by_month.items()],
            "forecast_by_series": {p.labels.get(c, c): round(float(v)) for c, v in fc.groupby("series").pred.sum().items()},
            "model": res["best"].get("model"), "test_window": [f"{d:%Y-%m}" for d in res["test_window"]],
            "error_relative_to_seasonal_naive": round(res["test_rel_mae"], 3),
            "accuracy_vs_baseline": (f"{(1 - res['test_rel_mae']) * 100:.0f}% more accurate" if res["test_rel_mae"] < 1
                                     else f"{(res['test_rel_mae'] - 1) * 100:.0f}% less accurate"),
            "by_months_ahead": [{"months_ahead": r["step"], "model_error_pct": round(100 * r["wape"], 1),
                                 "baseline_error_pct": round(100 * r["wape_naive"], 1), "verdict": r["reliability"]}
                                for r in res["per_step"].to_dict("records")],
            "not_forecast": {p.labels.get(c, c): why for c, why in res["skipped"].items()},
            "unvalidated": [p.labels.get(c, c) for c in res["unvalidated"]]}


def run(spec, out_root=OUT, usage=None, agent=None, narrate=None, log=print):
    t0 = time.time()
    log(f"== {spec.title}")
    p = panel.build(spec)
    log(f"  panel: {p.series.shape[1]} series x {p.series.shape[0]} months from {p.start}")
    res = model.run(p.series, p.exog, p.future_index, spec.horizon, spec.features, log=log)
    facts = facts_for(spec, p, res)
    if narrate:
        agent["summary"] = narrate(facts)
    out = out_root / spec.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard.html").write_text(dashboard.build(spec, p, res, usage, agent))
    res["forecast"].assign(label=res["forecast"].series.map(p.labels)).to_csv(out / "forecast.csv", index=False)
    res["backtest"].to_csv(out / "backtest.csv", index=False)
    summary = {"title": spec.title, "spec": spec.model_dump(), "best": res["best"],
               "feature_groups": res["feature_groups"], "test_rel_mae": res["test_rel_mae"],
               "per_step": res["per_step"].to_dict("records"),
               "forecast_total": float(res["forecast"].pred.sum()), "seconds": round(time.time() - t0, 1),
               "agent": {k: v for k, v in (agent or {}).items()}, "dashboard": str(out / "dashboard.html"),
               "facts": facts}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log(f"  wrote {out}/dashboard.html in {time.time() - t0:.0f}s")
    return summary


if __name__ == "__main__":
    for path in sys.argv[1:]:
        run(load(path))
