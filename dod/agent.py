"""The forecasting agent: one Claude agent with read-only tools that turns a plain-English request into SQL for the
order lines to forecast, plus a short description of the request. Fixed code does everything after that: adds the
lines up (dod/history.py), picks and tests the model (dod/model.py) and draws the dashboard (dod/forecast.py).

    python -m dod.agent "monthly forecast of Tito's minis in Des Moines for the next 5 months" [--interactive]
    python -m dod.agent "..." --sql-only      # the agent's part only: print its SQL and reading, run no models

How well its SQL matches an answer key of 34 requests: python evals/score_sql.py (evals/sql_report.md).
"""
import json
import os
import sys
import time

import anthropic

from . import db, history, panel, tools
from .plan import MAX_AHEAD, Plan

MODEL = os.environ.get("DOD_AGENT_MODEL", "claude-sonnet-5")
EFFORT = os.environ.get("DOD_AGENT_EFFORT", "medium")
PRICES = {  # $ per 1M tokens: input, output, cache write, cache read
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
}
MAX_TURNS = 12


def schema_rows():
    """The warehouse as the agent sees it: every table and column it may query, with the descriptions written by
    load_data.py (TABLE_NOTES, COLUMN_NOTES) and stored as Postgres comments. The data dictionary page uses this too."""
    cols = db.query("""
        SELECT c.table_schema || '.' || c.table_name AS tbl, c.column_name, c.data_type,
               col_description((c.table_schema || '.' || c.table_name)::regclass, c.ordinal_position) AS note
        FROM information_schema.columns c WHERE c.table_schema IN ('sales', 'ref')
        ORDER BY c.table_schema, c.table_name, c.ordinal_position""")
    tables = db.query("""
        SELECT n.nspname || '.' || c.relname AS tbl, obj_description(c.oid, 'pg_class') AS table_note
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('sales', 'ref') AND c.relkind = 'r'""")
    return cols.merge(tables, on="tbl", how="left")


def schema_text():
    """The schema part of the agent's instructions: one line per table, its description, then its columns."""
    out = []
    for tbl, g in schema_rows().groupby("tbl", sort=False):
        about = f" [{g.table_note.iloc[0]}]" if isinstance(g.table_note.iloc[0], str) else ""
        out.append(f"{tbl}{about}: " + "; ".join(f"{r.column_name} {r.data_type}" + (f" ({r.note})" if r.note else "")
                                                 for r in g.itertuples()))
    return "\n".join(out)


# Rules for the three warehouse traps the first test of AI-written SQL found (docs/differential.html).
RULES = """## Rules for this warehouse (follow them exactly)
1. Products: never filter order lines on item_no alone. Products were renumbered over the years; select the product's
   whole family: il.item_no IN (SELECT item_no FROM sales.item WHERE family_item_no IN (...)).
2. A brand (every size and flavor): match ALL the brand's words anywhere in the family's current name, not as a
   prefix (barrel picks are named e.g. 'BP CROWN ROYAL ...'): il.item_no IN (SELECT i.item_no FROM sales.item i JOIN
   sales.item h ON h.item_no = i.family_item_no WHERE h.item_desc ILIKE '%CROWN%' AND h.item_desc ILIKE '%ROYAL%').
3. Categories: never use invoice_line.category_code (codes were reassigned in 2016). Use today's category of the
   product: il.item_no IN (SELECT item_no FROM sales.item WHERE category_current IN (...)).

"""

GLOSSARY = """## Business definitions (the company's dictionary; follow them unless the user says otherwise)
- A brand (e.g. Hawkeye Vodka, Crown Royal) means every product of that brand: all sizes, flavors, packs and barrel
  picks.
- A spirit type (whiskey, vodka, American vodka, rum, ...) means its own categories, flavored ones included (American
  vodka includes American Flavored Vodka), but not liqueurs or ready-to-drink cocktails made from it: whiskey does not
  include Whiskey Liqueur (e.g. Fireball). Select the categories by name, never by a typed list of codes, e.g. whiskey:
  il.item_no IN (SELECT i.item_no FROM sales.item i JOIN sales.category c ON c.category_code = i.category_current
  WHERE c.category_name ILIKE '%WHISK%' AND c.category_name NOT ILIKE '%LIQUEUR%').
- Sizes go by bottle size, not by words in the product name: minis are 50 ml, pints 375 ml, fifths 750 ml, liters
  1000 ml, handles 1750 ml. Use the product family's size: h.bottle_volume_ml with h the family's current item.
- A vendor's products (e.g. all Diageo products) means the order lines that vendor sold (l.vendor_no), not the
  products it owns today: brands change hands.
- A period named by an event or season means through its end: "for the holidays" is through December 31.

"""

SYSTEM = """You are the forecasting analyst for a company that sells to Iowa liquor retailers. A business user asks for a
demand forecast in plain English, by week, month, quarter or year. Your job is to write ONE SQL query that picks the
order lines to forecast, and to say plainly how you read the request. Fixed code adds the lines up by week or month,
trains and backtests models, and draws the dashboard.

## Workflow
1. Resolve every business word to warehouse codes with find_values (products, places).
2. Test parts of your query with run_select (it returns at most 100 rows, so add things up when you test), then call
   submit_query. Aim for 3 to 6 tool calls. Test on a small slice (one recent month, one store or one product): a test
   only needs to show the logic works, and fixed code runs the full query. If a test is too slow, do not retry the same
   question written another way: test a smaller slice, or submit.
Ask the user (ask_user) only when a wrong guess would change the answer, and at most once.
If the request cannot be served as asked (a product or place not in the data, more than one year ahead), do not
submit; explain why in plain words. Never substitute a different place, product or horizon for the one asked.
Write plain text without em dashes.

## The query you submit
One SELECT over the sales and ref schemas (schema-qualified tables), one row per order line (no GROUP BY), returning
exactly these columns:
  day       the order date: l.ordered_on
  store_no  l.store_no
  item_no   l.item_no
  series    text: 'total' for one forecast; for a breakout, one readable name per series (e.g. the county name)
  value     the line's measure: l.sales_bottles unless dollars/revenue (l.sales_dollars) or liters/volume
            (l.sales_liters) are asked
Include all history from 2016-01-01. Fixed code never runs your query as is: it wraps it in its own sums, so the query
may select millions of lines.

## How you read the request (submit_query fields)
The warehouse has orders through {data_end}; the forecast starts with the first week or month after that, so count the
horizon from there (e.g. "through December" from data ending in August is 4 months).
grain: "week" | "month" | "quarter" | "year" (as asked; "month" if not stated). horizon: periods ahead in that grain
(weeks up to 52, months up to 12, quarters up to 4, years 1; 6 months if not stated). measure: bottles, dollars or
liters. product and place: short readable names. breakout: "none" for one total, else what each series is (county,
city, item, category, store, ...). title: a short title for the dashboard.

{rules}## Warehouse tables (read-only)
{schema}
"""

SUBMIT = {"name": "submit_query",
          "description": "Submit the SQL for the order lines and how you read the request. The query is checked (one "
                         "read-only SELECT returning day, store_no, item_no, series, value); you get an error back if "
                         "it fails, so you can fix it.",
          "input_schema": {"type": "object", "properties": {
              "sql": {"type": "string"}, "title": {"type": "string"},
              "measure": {"type": "string", "enum": ["bottles", "dollars", "liters"]},
              "product": {"type": "string"}, "place": {"type": "string"}, "breakout": {"type": "string"},
              "grain": {"type": "string", "enum": ["week", "month", "quarter", "year"]},
              "horizon": {"type": "integer"}, "assumptions": {"type": "array", "items": {"type": "string"}}},
              "required": ["sql", "title", "measure", "product", "place", "breakout", "grain", "horizon", "assumptions"],
              "additionalProperties": False},
          "strict": True}
TOOLS = tools.TOOLS + [SUBMIT]


def narrate(client, facts, usage):
    """Plain-English summary written only from the harness's numbers."""
    msg = client.messages.create(
        model=MODEL, max_tokens=2000,
        system="You write the first sentence of the summary at the top of a forecast dashboard, for a business reader who "
               "will give it a few seconds: one short sentence, at most 30 words, with the forecast total and its change "
               "from the same months last year. Do not discuss accuracy; a sentence about it is added after yours. "
               "Quote only numbers and percentages that appear in the facts JSON; never compute new ones (no ranges you "
               "derived yourself). Round large numbers to about three significant figures ($15.2 million, 53,000 "
               "bottles); a forecast is not precise to the unit. Speak of the facts' period if they name one (weeks or quarters), otherwise months. Mention unvalidated or skipped series only if there are any. Do not name the model. No em dashes.",
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
    if name == "ask_user":
        if interactive:
            return input(f"\n{args['question']}\n> ")
        return ("No answer available (non-interactive run). If the request is ambiguous, choose the most likely "
                "reading and list it in your assumptions. If it cannot be served as asked, do not submit; explain.")
    return f"Error: unknown tool {name}"


def submitted(request, a):
    """The agent's submission as a Plan, or an error message for the agent."""
    sql = a["sql"].strip().rstrip(";")
    err = history.check_query(sql)
    if not err and not 1 <= a["horizon"] <= MAX_AHEAD[a["grain"]]:
        err = f"Error: horizon must be 1 to {MAX_AHEAD[a['grain']]} for grain {a['grain']}."
    if err:
        return None, err
    plan = Plan(title=a["title"], sql=sql, target="sales_" + a["measure"], grain=a["grain"], horizon=a["horizon"],
                product=a["product"], place=a["place"], series_by=a["breakout"].strip().lower() or "none",
                request=request, assumptions=a["assumptions"])
    return plan, None


def ask(request, interactive=False, log=print):
    """The agent's part: a checked Plan (its SQL and its reading of the request), or the reason it declined."""
    client = anthropic.Anthropic()
    end, _ = panel.data_end()
    system = SYSTEM.format(schema=schema_text(), rules=RULES + GLOSSARY, data_end=f"{end:%B} {end.day}, {end.year}")
    messages = [{"role": "user", "content": request}]
    usage = {"model": MODEL, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0,
             "cache_read_tokens": 0, "est_cost_usd": 0.0}
    trace, t0, nudged = [], time.time(), False
    log(f"== agent ({MODEL}): {request}")
    for turn in range(MAX_TURNS):
        msg = client.messages.create(
            model=MODEL, max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS, messages=messages, thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"})   # also cache the growing conversation between turns
        add_usage(usage, msg)
        if msg.stop_reason == "refusal":
            return {"status": "refused", "message": "The model declined this request.", "usage": usage, "trace": trace}
        messages.append({"role": "assistant", "content": msg.content})
        calls = [b for b in msg.content if b.type == "tool_use"]
        if not calls:
            text = " ".join(b.text for b in msg.content if b.type == "text").strip()
            if not nudged and "?" not in text[-200:] and len(text) < 200:
                # stopped without submitting or explaining; one reminder, then accept its answer
                nudged = True
                messages.append({"role": "user", "content": "If this request can be served, call submit_query now; "
                                                            "otherwise explain in one short paragraph why not."})
                continue
            return {"status": "no_forecast", "message": text, "usage": usage, "trace": trace}
        results, plan = [], None
        for call in calls:
            t1 = time.time()
            if call.name == "submit_query":
                plan, err = submitted(request, call.input)
                out = err or "Accepted. Fixed code is adding up the order lines."
            else:
                out = call_tool(call.name, call.input, interactive)
            is_error = str(out).startswith("Error")
            trace.append({"turn": turn + 1, "tool": call.name, "input": short(json.dumps(call.input), 400),
                          "result": short(out), "seconds": round(time.time() - t1, 1), "error": is_error})
            log(f"  [{turn + 1}] {call.name}: {short(json.dumps(call.input), 160)}" + ("  -> ERROR" if is_error else ""))
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": str(out), "is_error": is_error})
        if plan is not None:
            usage["agent_seconds"] = round(time.time() - t0, 1)
            log(f"  query submitted after {len(trace)} tool calls, {usage['agent_seconds']}s, "
                f"about ${usage['est_cost_usd']:.3f}")
            return {"status": "ok", "plan": plan, "usage": usage, "trace": trace}
        messages.append({"role": "user", "content": results})
    return {"status": "error", "message": f"No query after {MAX_TURNS} turns.", "usage": usage, "trace": trace}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    request = " ".join(args)
    if "--sql-only" in sys.argv:
        r = ask(request, interactive="--interactive" in sys.argv)
        if r["status"] != "ok":
            print(f"\n{r['status']}: {r.get('message', '')}")
        else:
            print(r["plan"].model_dump_json(indent=1))
    else:
        from .forecast import forecast
        r = forecast(request, interactive="--interactive" in sys.argv)
        print(f"\n{r['status']}: {r.get('message', '')}" if r["status"] != "ok" else r["summary"]["dashboard"])
