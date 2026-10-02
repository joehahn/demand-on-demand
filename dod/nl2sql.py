"""The on-the-fly path (prototype): the same Claude agent, but it writes the SQL for the series itself (NL2SQL)
instead of filling in the request form. Same data dictionary, same lookup tools, same safety check (one read-only
SELECT) and same read-only login as the slot-filling agent in dod/agent.py; only its instructions and its final tool
differ. Used by evals/differential.py to test AI-written SQL against the slot-filling path as a reference.

    python -m dod.nl2sql "monthly forecast of Tito's minis in Des Moines for the next 5 months"
"""
import json
import sys
import time

import anthropic

from . import db, tools
from .agent import EFFORT, MAX_TURNS, MODEL, add_usage, call_tool, schema_text, short
from .spec import MAX_HORIZON
from .sqlcheck import check_sql

SYSTEM = """You are the forecasting analyst for a company that sells to Iowa liquor retailers. A business user asks for a
demand forecast in plain English. Your job is to write ONE SQL query that returns the monthly history to forecast,
quickly. Fixed code then fills months with no orders with 0, trains and backtests models, and draws the dashboard.

## Workflow
1. Resolve every business word to warehouse codes with find_values (products, places). Read the table and column
   descriptions below carefully: they say how products, categories, places and measures must be used.
2. Test your query with run_select (it returns at most 100 rows), then call submit_series with the final query.
   Aim for 3 to 6 tool calls in total.
Ask the user (ask_user) only when a wrong guess would change the answer, and at most once.
If the request cannot be served as asked (a product or place not in the data, a horizon over {max_h} months), do not
submit; explain why in plain words. Never substitute a different place, product or horizon for the one asked.
Write plain text without em dashes.

## The query you submit
One SELECT over the sales and ref schemas (schema-qualified tables) returning exactly these columns:
  month  (date: the first day of the month, e.g. date_trunc('month', ordered_on)::date)
  series (text: 'total' for one forecast; for a breakout, one readable name per series, e.g. the county name)
  value  (number: the measure summed over the month: bottles unless dollars/revenue or liters/volume are asked)
Include all history from 2016-01-01. Do not filter out the latest month; fixed code drops incomplete months.

## Warehouse tables (read-only)
{schema}
"""

SUBMIT = {"name": "submit_series",
          "description": "Submit the final SQL query for the monthly series, the forecast horizon in months, a short "
                         "title, and the assumptions you made in plain English. The query is checked (one read-only "
                         "SELECT) and run; you get an error back if it fails, so you can fix it.",
          "input_schema": {"type": "object", "properties": {
              "sql": {"type": "string"}, "horizon": {"type": "integer"}, "title": {"type": "string"},
              "assumptions": {"type": "array", "items": {"type": "string"}}},
              "required": ["sql", "horizon", "title", "assumptions"], "additionalProperties": False},
          "strict": True}
TOOLS = [t for t in tools.TOOLS if t["name"] in ("find_values", "run_select", "ask_user")] + [SUBMIT]


def run_series(sql):
    """Check and run the submitted query under the read-only login; return (DataFrame, None) or (None, error)."""
    sql = sql.strip().rstrip(";")
    problem = check_sql(sql)
    if problem:
        return None, f"Error: rejected ({problem}). Write one SELECT over sales or ref, schema-qualified."
    try:
        df = db.query(sql)
    except Exception as e:  # database errors go back to the model so it can correct its query
        return None, f"Error: {str(e).splitlines()[0]}"
    if list(df.columns) != ["month", "series", "value"]:
        return None, f"Error: the query must return exactly month, series, value (got {', '.join(df.columns)})."
    if df.empty:
        return None, "Error: the query returned no rows."
    return df, None


def ask(request, log=print):
    """Turn a request into a checked monthly series via AI-written SQL. Returns a dict with status, sql, series rows,
    horizon, title, assumptions, usage and trace."""
    client = anthropic.Anthropic()
    system = SYSTEM.format(max_h=MAX_HORIZON, schema=schema_text())
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
            text = " ".join(b.text for b in msg.content if b.type == "text").strip()
            return {"status": "no_forecast", "message": text, "usage": usage, "trace": trace}
        results, done = [], None
        for call in calls:
            if call.name == "submit_series":
                df, err = run_series(call.input["sql"])
                out = err or f"Accepted: {len(df)} rows, {df.series.nunique()} series."
                if df is not None:
                    done = {"status": "ok", "sql": call.input["sql"], "rows": df, "horizon": call.input["horizon"],
                            "title": call.input["title"], "assumptions": call.input["assumptions"]}
            else:
                out = call_tool(call.name, call.input, interactive=False)
            is_error = str(out).startswith("Error")
            trace.append({"turn": turn + 1, "tool": call.name, "input": short(json.dumps(call.input), 400),
                          "result": short(out), "error": is_error})
            log(f"  [{turn + 1}] {call.name}" + ("  -> ERROR" if is_error else ""))
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": str(out), "is_error": is_error})
        if done:
            usage["agent_seconds"] = round(time.time() - t0, 1)
            return {**done, "usage": usage, "trace": trace}
        messages.append({"role": "user", "content": results})
    return {"status": "error", "message": f"No query after {MAX_TURNS} turns.", "usage": usage, "trace": trace}


if __name__ == "__main__":
    r = ask(" ".join(a for a in sys.argv[1:] if not a.startswith("--")))
    print(r["status"], r.get("message", ""))
    if r["status"] == "ok":
        print(r["sql"]); print(r["rows"].groupby("series").value.sum())
