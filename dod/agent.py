"""The forecasting agent: one Claude agent with read-only tools that turns a plain-English request into a
spec for the fixed harness, which trains, backtests and draws the dashboard.

    python -m dod.agent "monthly forecast of Tito's minis in Des Moines for the next 5 months" [--interactive]
    python -m dod.agent "..." --spec-only       # resolve the request, skip training
"""
import json
import os
import sys
import time

import anthropic

from . import db, run, tools
from .spec import MAX_HORIZON

MODEL = os.environ.get("DOD_AGENT_MODEL", "claude-sonnet-5")
EFFORT = os.environ.get("DOD_AGENT_EFFORT", "medium")
PRICES = {  # $ per 1M tokens: input, output, cache write, cache read
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
}
MAX_TURNS = 12


def schema_text():
    rows = db.query("""
        SELECT c.table_schema || '.' || c.table_name AS tbl, c.column_name, c.data_type,
               col_description((c.table_schema || '.' || c.table_name)::regclass, c.ordinal_position) AS note
        FROM information_schema.columns c WHERE c.table_schema IN ('sales', 'ref')
        ORDER BY c.table_schema, c.table_name, c.ordinal_position""")
    out = []
    for tbl, g in rows.groupby("tbl", sort=False):
        out.append(f"{tbl}: " + "; ".join(f"{r.column_name} {r.data_type}" + (f" ({r.note})" if r.note else "")
                                          for r in g.itertuples()))
    return "\n".join(out)


SYSTEM = """You are the forecasting analyst for a company that sells to Iowa liquor retailers. A business user asks for a
demand forecast in plain English. Your job is to turn the request into a precise spec for the forecasting harness,
quickly. The harness, not you, builds the monthly series, trains and backtests models against a seasonal-naive
baseline, and draws the dashboard. The warehouse is already clean: renumbered products are joined into one product
(search returns one row per product), categories use today's taxonomy for all history, each city has one spelling.

## Workflow
1. Resolve every business word to warehouse codes with find_values (products, places). Check sizes, dates and volumes.
2. Call preview_spec once to confirm the series look right (enough history, the right products and places).
3. Call submit_spec with your assumptions. Aim for 3 to 6 tool calls in total.
Ask the user (ask_user) only when a wrong guess would change the answer, and at most once.
If the request cannot be served as asked (a product or place not in the data, a horizon over {max_h} months, or
under 24 months of history for everything requested), do not submit; explain why in plain words and suggest what
you could do instead. Never substitute a different place, product or horizon for the one the user asked for.
Write plain text without em dashes.

## Spec (JSON string passed to preview_spec and submit_spec)
{{
  "title": "short title, e.g. Tito's minis, Polk County, next 5 months",
  "target": "sales_bottles" | "sales_dollars" | "sales_liters",   // bottles unless dollars/revenue or liters/volume asked
  "horizon": 1-{max_h},                                             // months ahead; 6 if not stated
  "product": {{"kind": "all" | "item" | "category" | "vendor", "codes": [...], "label": "readable name"}},
  "region":  {{"kind": "statewide" | "county" | "city" | "store", "codes": [...], "label": "readable name"}},
  "series_by": "none" | "county" | "city" | "item" | "category"    // one series per value; "none" = one total
}}
Codes: item -> item_no values exactly as find_values returns them; category -> category_code; vendor -> vendor_no;
county -> 5-digit county_fips; city -> city names as returned; store -> store_no.
Products: a brand means all its sizes unless a size is named ("minis" = 50 ml). A kind of spirit ("whiskey",
"vodka") means every category of that kind. Places: a county name -> that county; a city name -> the city (ask if
the user might mean the metro or county); "Iowa" or no place -> statewide. series_by: use it only when the user asks
for each / by / per / broken out.

## Warehouse tables (read-only)
{schema}
"""


def narrate(client, facts, usage):
    """Plain-English summary written only from the harness's numbers."""
    msg = client.messages.create(
        model=MODEL, max_tokens=2000,
        system="You write the one-line summary at the top of a forecast dashboard for a business reader who will give it "
               "a few seconds: one or two short sentences, at most 40 words, with the forecast total, its change from "
               "the same months last year, and how far to trust it. "
               "Quote only numbers and percentages that appear in the facts JSON; never compute new ones (no ranges you "
               "derived yourself). Round large numbers to about three significant figures ($15.2 million, 53,000 "
               "bottles); a forecast is not precise to the unit. For trust, use the backtest against the seasonal-naive "
               "baseline (\"8% more accurate than repeating last year\"). Mention unvalidated or skipped series only if there are any. Do not name the model. No em dashes.",
        messages=[{"role": "user", "content": json.dumps(facts, default=str)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
            "type": "object", "properties": {"summary": {"type": "string"}},
            "required": ["summary"], "additionalProperties": False}}},
    )
    add_usage(usage, msg)
    return json.loads(next(b.text for b in msg.content if b.type == "text"))["summary"]


def add_usage(usage, msg):
    u = msg.usage
    usage["calls"] += 1
    usage["input_tokens"] += u.input_tokens
    usage["output_tokens"] += u.output_tokens
    usage["cache_write_tokens"] += u.cache_creation_input_tokens or 0
    usage["cache_read_tokens"] += u.cache_read_input_tokens or 0
    p_in, p_out, p_cw, p_cr = PRICES.get(MODEL, PRICES["claude-sonnet-5"])
    usage["est_cost_usd"] = round((usage["input_tokens"] * p_in + usage["output_tokens"] * p_out +
                                   usage["cache_write_tokens"] * p_cw + usage["cache_read_tokens"] * p_cr) / 1e6, 4)


def short(text, n=600):
    text = str(text)
    return text if len(text) <= n else text[:n] + f" ... ({len(text) - n} more characters)"


def call_tool(name, args, interactive):
    if name == "find_values":
        return tools.find_values(args["kind"], args["text"])
    if name == "run_select":
        return tools.run_select(args["sql"])
    if name == "preview_spec":
        return tools.preview(args["spec_json"])[0]
    if name == "ask_user":
        if interactive:
            return input(f"\n{args['question']}\n> ")
        return ("No answer available (non-interactive run). If the request is ambiguous, choose the most likely "
                "reading and list it in your assumptions. If it cannot be served as asked, do not submit; explain.")
    return f"Error: unknown tool {name}"


def ask(request, interactive=False, train=True, log=print):
    client = anthropic.Anthropic()
    system = SYSTEM.format(max_h=MAX_HORIZON, schema=schema_text())
    messages = [{"role": "user", "content": request}]
    usage = {"model": MODEL, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0,
             "cache_read_tokens": 0, "est_cost_usd": 0.0}
    trace, t0, spec, assumptions, nudged = [], time.time(), None, [], False
    log(f"== agent ({MODEL}): {request}")

    for turn in range(MAX_TURNS):
        msg = client.messages.create(
            model=MODEL, max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools.TOOLS, messages=messages,
            thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},  # also cache the growing conversation between turns
        )
        add_usage(usage, msg)
        if msg.stop_reason == "refusal":
            return {"status": "refused", "message": "The model declined this request.", "usage": usage, "trace": trace}
        if msg.stop_reason == "max_tokens":
            return {"status": "error", "message": "Response hit max_tokens.", "usage": usage, "trace": trace}
        messages.append({"role": "assistant", "content": msg.content})
        calls = [b for b in msg.content if b.type == "tool_use"]
        if not calls:
            text = " ".join(b.text for b in msg.content if b.type == "text").strip()
            if not nudged and spec is None and "?" not in text[-200:] and len(text) < 200:
                # stopped without submitting or explaining; one reminder, then accept its answer
                nudged = True
                messages.append({"role": "user", "content": "If this request can be served, call submit_spec now; "
                                                            "otherwise explain in one short paragraph why not."})
                continue
            return {"status": "no_forecast", "message": text, "usage": usage, "trace": trace,
                    "seconds": round(time.time() - t0, 1)}

        results = []
        for call in calls:
            t1 = time.time()
            if call.name == "submit_spec":
                candidate, err = tools.parse_spec(call.input["spec_json"])
                out = err or "Accepted. The harness is running it."
                if not err:
                    spec, assumptions = candidate, call.input["assumptions"]
            else:
                out = call_tool(call.name, call.input, interactive)
            is_error = str(out).startswith("Error")
            trace.append({"turn": turn + 1, "tool": call.name, "input": short(json.dumps(call.input), 400),
                          "result": short(out), "seconds": round(time.time() - t1, 1), "error": is_error})
            log(f"  [{turn + 1}] {call.name}: {short(json.dumps(call.input), 160)}" + ("  -> ERROR" if is_error else ""))
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": str(out), "is_error": is_error})
        if spec is not None:
            break
        messages.append({"role": "user", "content": results})
    else:
        return {"status": "error", "message": f"No spec after {MAX_TURNS} turns.", "usage": usage, "trace": trace}

    usage["agent_seconds"] = round(time.time() - t0, 1)
    log(f"  spec submitted after {len(trace)} tool calls, {usage['agent_seconds']}s, about ${usage['est_cost_usd']:.3f}")
    agent = {"request": request, "assumptions": assumptions, "trace": trace, "usage": usage}
    if not train:  # spec only: the evals score the agent's decisions without training models
        return {"status": "ok", "spec": spec.model_dump(), "assumptions": assumptions, "usage": usage, "trace": trace}
    summary = run.run(spec, usage=usage, agent=agent, narrate=lambda facts: narrate(client, facts, usage), log=log)
    return {"status": "ok", "spec": spec.model_dump(), "summary": summary, "usage": usage, "trace": trace}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    result = ask(" ".join(args), interactive="--interactive" in sys.argv, train="--spec-only" not in sys.argv)
    if result["status"] == "ok" and "--spec-only" in sys.argv:
        print(json.dumps(result["spec"], indent=1))
        print("assumptions:", *result["assumptions"], sep="\n - ")
    if result["status"] != "ok":
        print(f"\n{result['status']}: {result['message']}")
