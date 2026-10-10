"""One forecast request end to end: the agent's part, then fixed code for everything else.

    python -m dod.forecast "weekly forecast of Tito's minis in Des Moines for the next 8 weeks" [--interactive]

  1. the agent (dod/agent.py) writes SQL for the order lines and says how it read the request
  2. fixed code adds the lines up by week or month and builds the inputs (dod/history.py, dod/features.py)
  3. fixed code picks and tests the model (dod/model.py, grain-aware), and a short summary is written from its numbers
  4. fixed code draws the dashboard (dod/dashboard.py)
Writes out/<slug>/: dashboard.html, forecast.csv, backtest.csv, stores.csv, summary.json, and page.pkl (everything the
page is drawn from).

    python -m dod.forecast --rebuild out/<slug> [...]   # redraw pages with the current dashboard code, from page.pkl:
                                                         # no AI call, no model training (for wording and layout changes)
"""
import datetime
import json
import pickle
import sys
import time
from pathlib import Path

import anthropic
import pandas as pd

from . import agent, dashboard, history, model, panel as panel_mod, periods

OUT = Path(__file__).parent.parent / "out"


def facts_for(plan, p, res):
    """The numbers the summary writer may use, and nothing else."""
    fc, wide = res["forecast"], p.series
    fmt = "%Y-%m" if model.GRAIN == "month" else "%Y-%m-%d"   # weeks and quarters are labeled by their first day
    ago = model.SEASON * pd.tseries.frequencies.to_offset(model.FREQ)   # the same period last year
    last_year = {f"{m:{fmt}}": float(sum(wide.at[m - ago, c] for c in fc.series.unique() if (m - ago) in wide.index))
                 for m in sorted(fc.month.unique())}
    by_month = {f"{m:{fmt}}": float(v) for m, v in fc.groupby("month").pred.sum().items()}
    pct = lambda a, b: f"{(a / b - 1) * 100:+.0f}%" if b else "n/a"
    return {"title": plan.title, "unit": plan.target.replace("sales_", ""),
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
            "unvalidated": [p.labels.get(c, c) for c in res["unvalidated"]],
            # weeks or quarters: say so, since the keys above are named for months (monthly facts stay as they were)
            **({"period": model.GRAIN, "compare_with": f"the same {model.GRAIN}s last year",
                "note": f"each 'month' entry above is one {model.GRAIN}, labeled by its first day"}
               if model.GRAIN != "month" else {}),
            # longer periods (fortnights, quarters, half-years, a year): the page reports those (dod/periods.py)
            **(period_facts(res, pct) if "periods" in res else {})}


def period_facts(res, pct):
    """The reported periods, for the summary writer: their total and change, and each period."""
    q, name = res["periods"], periods.NAMES[res["period_grain"]]
    return {"periods_reported": f"{q.period.iloc[0]} to {q.period.iloc[-1]}" if len(q) > 1 else q.period.iloc[0],
            "period": name, "periods_total": round(q.total.sum()),
            "periods_change_vs_last_year": pct(q.total.sum(), q.last_year.sum()),
            "by_period": [{name: r.period, "status": r.status, "sold_so_far": round(r.sold),
                           "forecast_total": round(r.total),
                           "same_period_last_year": round(r.last_year) if r.last_year == r.last_year else None,
                           "change": pct(r.total, r.last_year) if r.last_year == r.last_year else "n/a"}
                          for r in q.itertuples()],
            "note": f"The request asked for {name}s: quote periods_total and periods_change_vs_last_year for "
                    f"periods_reported (a period in progress includes what already sold), not the totals above."}


def trust_sentence(rel):
    """The accuracy half of the summary, worded the same way on every dashboard (from the backtest, not the AI)."""
    pct = round(abs(1 - rel) * 100)
    if pct == 0:
        return "This forecast is about as accurate as simply repeating last year's outcome."
    return f"This forecast is {pct}% {'more' if rel < 1 else 'less'} accurate than simply repeating last year's outcome."


def run(plan, usage=None, trace=None, narrate=True, out_root=OUT, log=print):
    """Fixed code from the agent's Plan to the dashboard. narrate=False skips the one AI call (the summary sentence),
    e.g. for the benchmark. Returns the summary dict written to summary.json."""
    t0 = time.time()
    grain, steps = plan.model_grain
    if periods.PERIODS[plan.grain][1] > 1:   # a longer period: the exact weeks or months to forecast (dod/periods.py)
        grain, left, fit, steps = periods.steps_needed(plan.grain, plan.horizon, panel_mod.data_end()[1])
    p, groups = history.build(plan.sql, grain, steps)
    shown = plan.model_copy(update={"grain": grain, "horizon": steps, "features": groups})
    log(f"  history: {p.series.shape[1]} series x {p.series.shape[0]} {grain}s ({time.time() - t0:.0f}s)")
    with model.use_grain(grain):
        res = model.run(p.series, p.exog, p.future_index, steps, groups, log=log)
        if periods.PERIODS[plan.grain][1] > 1:
            res["periods"] = periods.table(plan.grain, p.series, res, left, fit)
            res["period_grain"], res["periods_asked"] = plan.grain, plan.horizon
        facts = facts_for(shown, p, res)
        info = {"request": plan.request or plan.title, "assumptions": plan.assumptions, "trace": trace or [],
                "usage": usage or {}}
        if narrate:
            usage = usage if usage is not None else {"model": agent.MODEL, "calls": 0, "input_tokens": 0,
                                                     "output_tokens": 0, "cache_write_tokens": 0,
                                                     "cache_read_tokens": 0, "est_cost_usd": 0.0}
            info["summary"] = (agent.narrate(anthropic.Anthropic(), facts, usage) + " "
                               + trust_sentence(res["test_rel_mae"]))
        p.built_at = datetime.datetime.now().astimezone()
        page = {"spec": shown, "panel": p, "res": res, "usage": usage, "agent": info if plan.request else None,
                "harness_seconds": time.time() - t0}
        html = dashboard.build(**page)
    out = Path(out_root) / plan.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "page.pkl").write_bytes(pickle.dumps(page))   # for rebuild: the page's inputs, not its code
    (out / "dashboard.html").write_text(html)
    res["forecast"].to_csv(out / "forecast.csv", index=False)
    res["backtest"].to_csv(out / "backtest.csv", index=False)
    p.stores.to_csv(out / "stores.csv", index=False)
    summary = {"title": plan.title, "grain": grain, "plan": plan.model_dump(), "best": res["best"],
               "feature_groups": res["feature_groups"], "test_rel_mae": res["test_rel_mae"],
               "per_step": res["per_step"].to_dict("records"), "forecast_total": float(res["forecast"].pred.sum()),
               "seconds": round(time.time() - t0, 1), "agent": {k: v for k, v in info.items() if k != "trace"},
               "dashboard": str(out / "dashboard.html"), "facts": facts}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log(f"  wrote {out}/dashboard.html in {time.time() - t0:.0f}s")
    return {**summary, "res": res, "panel": p}


def forecast(request, interactive=False, log=print, out_root=OUT):
    """Plain English in, dashboard out. Returns {"status": "ok", "summary": ...} or the reason there is no forecast."""
    a = agent.ask(request, interactive=interactive, log=log)
    if a["status"] != "ok":
        return a
    try:
        summary = run(a["plan"], a["usage"], a["trace"], out_root=out_root, log=log)
    except (ValueError, model.TooLittleData) as e:   # e.g. too little history: fixed code declines, in plain words
        return {**a, "status": "no_forecast", "message": str(e)}
    return {**a, "status": "ok", "summary": summary}


def rebuild(out_dir):
    """Redraw out_dir/dashboard.html from its saved page.pkl with the current dashboard code (same numbers)."""
    page = pickle.loads((Path(out_dir) / "page.pkl").read_bytes())
    with model.use_grain(page["spec"].grain):
        html = dashboard.build(**page)
    (Path(out_dir) / "dashboard.html").write_text(html)
    return str(Path(out_dir) / "dashboard.html")


if __name__ == "__main__":
    if "--rebuild" in sys.argv:
        for d in sys.argv[sys.argv.index("--rebuild") + 1:]:
            print("rebuilt", rebuild(d))
        sys.exit()
    r = forecast(" ".join(x for x in sys.argv[1:] if not x.startswith("--")), interactive="--interactive" in sys.argv)
    print(f"\n{r['status']}: {r.get('message', '')}" if r["status"] != "ok" else r["summary"]["dashboard"])
