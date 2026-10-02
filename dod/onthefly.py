"""The on-the-fly path (prototype): forecasts by week, month, quarter or year from AI-written SQL.

    python -m dod.onthefly "weekly forecast of Tito's minis in Des Moines for the next 8 weeks"

Who does what:
  - The AI (the same agent and tools as dod/nl2sql.py, with its rules) writes SQL that returns DAILY totals: it
    decides which order lines and which measure. It also names the time grain and horizon, and fills in the request
    form's product, place and measure where the form can express them.
  - Fixed code does the rest: buckets the daily totals into the grain, keeps complete periods only, fills empty
    periods with 0, runs the grain-aware harness (dod/model.use_grain: same period last year as the baseline, lags
    and windows one or two seasons long), and cross-checks the AI's data against the reference: the daily totals
    summed by month must equal the monthly series the slot-filling harness builds from the form.
A yearly request is forecast by month (12 months ahead) and reported as the year's total.
"""
import json
import sys
import time

import anthropic
import numpy as np
import pandas as pd

from . import db, features, model, panel, tools
from .agent import EFFORT, MAX_TURNS, MODEL, add_usage, call_tool, schema_text, short
from .nl2sql import RULES
from .spec import Spec
from .sqlcheck import check_sql

SYSTEM = """You are the forecasting analyst for a company that sells to Iowa liquor retailers. A business user asks for a
demand forecast in plain English, by week, month, quarter or year. Your job is to write ONE SQL query that returns the
DAILY history to forecast, and to say the time grain and horizon. Fixed code buckets the days into weeks, months or
quarters, trains and backtests models, and draws the results.

## Workflow
1. Resolve every business word to warehouse codes with find_values (products, places).
2. Test your query with run_select (at most 100 rows come back), then call submit_daily. Aim for 3 to 6 tool calls.
If the request cannot be served (a product or place not in the data, more than one year ahead), do not submit;
explain why in plain words. Write plain text without em dashes.

## The query you submit
One SELECT over the sales and ref schemas (schema-qualified tables) returning exactly these columns:
  day    (date: the order date, l.ordered_on)
  series (text: 'total' for one forecast; for a breakout, one readable name per series)
  value  (number: the measure summed over the day: bottles unless dollars/revenue or liters/volume are asked)
Group by day and series. Include all history from 2016-01-01.

## Grain and horizon
grain: "week" | "month" | "quarter" | "year" (as asked; "month" if not stated). horizon: periods ahead in that grain
(weeks up to 52, months up to 12, quarters up to 4, years 1).

## Reference scope (for the cross-check)
If the request is a plain sum of bottles, dollars or liters for products and a place, also give the request form's
fields as JSON, so fixed code can rebuild the same history independently and check yours:
  {{"target": "sales_bottles" | "sales_dollars" | "sales_liters",
    "product": {{"kind": "all" | "item" | "category" | "vendor" | "name", "codes": [...], "label": "..."}},
    "region": {{"kind": "statewide" | "county" | "city" | "store", "codes": [...], "label": "..."}},
    "series_by": "none" | "county" | "city" | "item" | "category"}}
(item codes are product families as find_values returns them; name codes are the words of one brand; county codes are
5-digit FIPS). If the request is something else (a ratio, a count of stores, a group of stores defined by a condition
such as a chain name), or if you could only list part of what your query selects, give an empty string.

{rules}## Warehouse tables (read-only)
{schema}
"""

SUBMIT = {"name": "submit_daily",
          "description": "Submit the daily-history SQL, the grain, the horizon in periods of that grain, a short "
                         "title, the reference scope (JSON string, or empty), and your assumptions in plain English.",
          "input_schema": {"type": "object", "properties": {
              "sql": {"type": "string"}, "grain": {"type": "string", "enum": ["week", "month", "quarter", "year"]},
              "horizon": {"type": "integer"}, "title": {"type": "string"}, "reference_scope": {"type": "string"},
              "assumptions": {"type": "array", "items": {"type": "string"}}},
              "required": ["sql", "grain", "horizon", "title", "reference_scope", "assumptions"],
              "additionalProperties": False},
          "strict": True}
TOOLS = [t for t in tools.TOOLS if t["name"] in ("find_values", "run_select", "ask_user")] + [SUBMIT]
MAX_AHEAD = {"week": 52, "month": 12, "quarter": 4, "year": 1}


def run_daily(sql):
    """Check and run the AI's query under the read-only login; return (rows, None) or (None, error)."""
    sql = sql.strip().rstrip(";")
    problem = check_sql(sql)
    if problem:
        return None, f"Error: rejected ({problem})."
    try:
        df = db.query(sql)
    except Exception as e:
        return None, f"Error: {str(e).splitlines()[0]}"
    if list(df.columns) != ["day", "series", "value"]:
        return None, f"Error: the query must return exactly day, series, value (got {', '.join(df.columns)})."
    return (df, None) if len(df) else (None, "Error: the query returned no rows.")


def ask(request, log=print):
    """The AI's part: SQL for daily history, grain, horizon and (when possible) the reference scope."""
    client = anthropic.Anthropic()
    system = SYSTEM.format(schema=schema_text(), rules=RULES)
    messages = [{"role": "user", "content": request}]
    usage = {"model": MODEL, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0,
             "cache_read_tokens": 0, "est_cost_usd": 0.0}
    trace, t0 = [], time.time()
    for turn in range(MAX_TURNS):
        msg = client.messages.create(
            model=MODEL, max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS, messages=messages, thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"})
        add_usage(usage, msg)
        messages.append({"role": "assistant", "content": msg.content})
        calls = [b for b in msg.content if b.type == "tool_use"]
        if not calls:
            return {"status": "no_forecast", "usage": usage, "trace": trace,
                    "message": " ".join(b.text for b in msg.content if b.type == "text").strip()}
        results, done = [], None
        for call in calls:
            if call.name == "submit_daily":
                a = call.input
                rows, err = run_daily(a["sql"])
                if not err and not 1 <= a["horizon"] <= MAX_AHEAD[a["grain"]]:
                    err = f"Error: horizon must be 1 to {MAX_AHEAD[a['grain']]} for grain {a['grain']}."
                out = err or f"Accepted: {len(rows)} daily rows."
                if not err:
                    done = {**a, "rows": rows}
            else:
                out = call_tool(call.name, call.input, interactive=False)
            trace.append({"turn": turn + 1, "tool": call.name, "input": short(json.dumps(call.input), 400),
                          "result": short(out), "error": str(out).startswith("Error")})
            log(f"  [{turn + 1}] {call.name}")
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": str(out),
                            "is_error": str(out).startswith("Error")})
        if done:
            usage["agent_seconds"] = round(time.time() - t0, 1)
            return {"status": "ok", **done, "request": request, "usage": usage, "trace": trace}
        messages.append({"role": "user", "content": results})
    return {"status": "error", "message": f"No query after {MAX_TURNS} turns.", "usage": usage, "trace": trace}


def bucket(rows, grain, last_day):
    """Fixed code: daily totals -> one column per series at the grain, complete periods only, empty periods 0,
    periods before a series' first sale blank."""
    freq = {"week": "W-MON", "month": "MS", "quarter": "QS", "year": "MS"}[grain]
    day = pd.to_datetime(rows.day)
    start = {"week": day - pd.to_timedelta(day.dt.weekday, unit="D"), "quarter": day.dt.to_period("Q").dt.start_time}.get(
        grain, day.dt.to_period("M").dt.start_time)
    df = rows.assign(period=start.dt.normalize())
    wide = df.pivot_table(index="period", columns="series", values="value", aggfunc="sum")
    # the last complete period ends on or before the last day with orders
    step = pd.tseries.frequencies.to_offset(freq)
    last = pd.Timestamp(last_day)
    idx = pd.date_range(wide.index.min(), last, freq=freq)
    idx = idx[[p + step - pd.Timedelta(days=1) <= last for p in idx]]
    wide = wide.reindex(idx).fillna(0.0)
    for c in wide:
        first = wide[c].gt(0).idxmax()
        wide.loc[wide.index < first, c] = np.nan
    wide.index.freq = None
    return wide.rename_axis(None, axis=1)


def cross_check(rows, scope_json, last_month):
    """Reference check: the AI's daily totals summed by month must equal the monthly series the slot-filling harness
    builds from the request form. Returns a dict for the report."""
    if not scope_json.strip():
        return {"status": "not available", "why": "the form cannot express this request"}
    try:
        scope = json.loads(scope_json)
        spec = Spec(title="check", horizon=1, **scope)
    except Exception as e:
        return {"status": "not available", "why": f"the form fields did not validate ({str(e).splitlines()[0][:80]})"}
    sql, params = panel.build_sql(spec)
    ref = panel.to_wide(db.query(sql, params), spec.start, last_month)
    ai = panel.to_wide(rows.assign(month=pd.to_datetime(rows.day).dt.to_period("M").dt.start_time)
                       .groupby(["month", "series"], as_index=False).value.sum(), spec.start, last_month)
    r, a = ref.sum(axis=1), ai.sum(axis=1).reindex(ref.index).fillna(0)   # compare the totals across series
    bad = (r - a).abs() > (r.abs() * 1e-9).clip(lower=0.5)
    return {"status": "passed" if not bad.any() else "failed", "months": int(len(r)), "bad_months": int(bad.sum()),
            "reference_total": float(r.sum()), "ai_total": float(a.sum()),
            "first_bad": str(bad.idxmax().date()) if bad.any() else None}


def forecast(request, log=print, out_root=None):
    """End to end: the AI's part, then fixed bucketing, the grain-aware harness, the reference cross-check, and (when
    the AI filled in the request form) a full dashboard, written to out/<title>/dashboard.html."""
    a = ask(request, log=log)
    if a["status"] != "ok":
        return a
    t0 = time.time()
    end, last_month = panel.data_end()
    panel.check_months("2016-01-01", last_month)   # a period with no orders must be a real zero, not missing data
    grain = a["grain"]
    model_grain, steps = ("month", 12) if grain == "year" else (grain, a["horizon"])
    wide = bucket(a["rows"], model_grain, end)
    step = pd.tseries.frequencies.to_offset(model.GRAINS[model_grain]["freq"])
    future = pd.date_range(wide.index[-1] + step, periods=steps, freq=step)
    idx = wide.index.append(future)
    spec = form_spec(a, model_grain, steps)
    store_rows = None
    if spec is not None:   # per-store monthly rows from the tested path: for the stores input, store list and map
        items = panel.member_items(spec) if spec.product.kind in ("item", "category", "name") else []
        store_rows = db.query(*panel.build_sql(spec, items))
    # inputs offered to model selection (dod/features.py): weekly only, as tested (benchmark/feature_experiment.py)
    groups, extra = [], pd.DataFrame(index=idx)
    if model_grain == "week":
        groups = ["season", "holiday_weeks"]
        extra = features.season(pd.DatetimeIndex(idx, freq="W-MON")).join(features.holiday_weeks(idx))
        if store_rows is not None and len(store_rows):
            groups.append("stores")
            extra = extra.assign(active_stores=features.stores(store_rows[store_rows.value > 0], idx, wide.index[-1]).values)
    exog = {c: extra.copy() for c in wide}
    with model.use_grain(model_grain):
        res = model.run(wide, exog, future, steps, groups, log=lambda *x: None)
    check = cross_check(a["rows"], a["reference_scope"], last_month)
    out = {**a, "status": "ok", "model_grain": model_grain, "wide": wide, "res": res, "check": check,
           "harness_seconds": round(time.time() - t0, 1)}
    if spec is not None:
        spec = spec.model_copy(update={"features": groups})   # the dashboard reports which inputs were tried
        out["dashboard"] = write_dashboard(spec, a, wide, exog, future, res, check, end, last_month, out_root, t0,
                                           store_rows)
    return out


def form_spec(a, grain, steps):
    """The request form the AI filled in, as a Spec at the forecast's grain (None if the form cannot express it)."""
    try:
        scope = json.loads(a["reference_scope"]) if a["reference_scope"].strip() else None
        return Spec(title=a["title"], horizon=steps, grain=grain, features=[], **scope) if scope else None
    except Exception:
        return None


def write_dashboard(spec, a, wide, exog, future, res, check, end, last_month, out_root, t0, store_rows=None):
    """A full dashboard, like the monthly ones: same builder, with the AI's SQL, form fill and cross-check."""
    from pathlib import Path
    from . import agent as agent_mod, dashboard, run as run_mod
    items = panel.member_items(spec) if spec.product.kind in ("item", "category", "name") else []
    if store_rows is None:
        store_rows = db.query(*panel.build_sql(spec, items))
    stores = panel.store_list(store_rows, last_month)   # store list and map, from the tested path's query
    p = panel.Panel(series=wide, exog=exog, future_index=future, sql=a["sql"], data_end=end, start=spec.start,
                    labels={c: f"{spec.product.label}, {spec.region.label}" if c == "total" else c for c in wide},
                    stores=stores, unknown_packs=panel.unknown_packs(spec, items))
    usage = a["usage"]
    with model.use_grain(spec.grain):
        facts = run_mod.facts_for(spec, p, res)
    summary = agent_mod.narrate(anthropic.Anthropic(), facts, usage) + " " + run_mod.trust_sentence(res["test_rel_mae"])
    agent = {"request": a["title"] if not a.get("request") else a["request"], "assumptions": a["assumptions"],
             "trace": a["trace"], "usage": usage, "summary": summary}
    html = dashboard.build(spec, p, res, usage, agent, harness_seconds=time.time() - t0,
                           ai={"sql": a["sql"], "check": check})
    out = Path(out_root or Path(__file__).parent.parent / "out") / spec.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard.html").write_text(html)
    # the numbers the summary sentence was written from, like the monthly path, so evals/grounding.py checks it too
    (out / "summary.json").write_text(json.dumps({"title": spec.title, "grain": spec.grain, "facts": facts,
                                                  "agent": {"summary": summary}}, indent=2, default=str))
    return str(out / "dashboard.html")


if __name__ == "__main__":
    out = forecast(" ".join(x for x in sys.argv[1:] if not x.startswith("--")))
    if out["status"] != "ok":
        print(out["status"], out.get("message", ""))
    else:
        fc = out["res"]["forecast"]
        print(out["title"], "|", out["grain"], out["horizon"], "| cross-check:", out["check"])
        print(f"test rel MAE {out['res']['test_rel_mae']:.3f} | forecast total {fc.pred.sum():,.0f}")
        print(fc[["month", "pred", "lo", "hi"]].to_string(index=False))
