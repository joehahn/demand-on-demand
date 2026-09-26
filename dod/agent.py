"""The forecasting agent: one Claude agent with read-only tools that turns a plain-English request into a
validated spec, then hands it to the fixed harness.

    python -m dod.agent "monthly forecast of Tito's minis in Des Moines for the next 5 months" [--interactive]
"""
import json
import os
import sys
import time

import anthropic

from . import db, run, tools
from .spec import MAX_HORIZON

MODEL = os.environ.get("DOD_AGENT_MODEL", "claude-sonnet-5")
PRICES = {  # $ per 1M tokens: input, output, cache write, cache read
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
}
MAX_TURNS = 20


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


def register_text():
    df = db.query("SELECT issue_id, title, description, mitigation_rule, mitigation_params FROM meta.known_issues "
                  "WHERE status = 'approved' ORDER BY issue_id")
    return "\n".join(f"- {r.issue_id}: {r.title}. {r.description} Harness rule: {r.mitigation_rule} "
                     f"{json.dumps(r.mitigation_params or {})}" for r in df.itertuples())


SYSTEM = """You are the forecasting analyst for a small company that sells to Iowa liquor retailers. A business user asks
for a demand forecast in plain English. Your job is to turn the request into a precise, validated spec for the
forecasting harness, handling the data problems a careful analyst would handle. The harness, not you, builds the
monthly series, trains and backtests models against a seasonal-naive baseline, and draws the dashboard.

## Workflow
1. Resolve every business word to warehouse codes with find_values (products, places). Check sizes, dates and
   volumes in the results. Use run_select only to check a fact you cannot get otherwise.
2. Draft the spec and call preview_spec. Read the register decisions and the slice findings.
3. Decide each finding. A finding is either a data artifact (a renumbered item, a temporary code, a recoding, spelling
   variants, a series whose zeros predate the product's launch) or real demand (growth, a launch ramp, promotions, bulk
   or holiday orders, store openings and closings). Fix artifacts with a mitigation and a one-line reason. Leave real
   demand alone, even when it is spiky: the forecast is for real orders, spikes included, and the harness already
   tunes how much history to use. Findings marked "no effect" need no fix. When unsure, use flag_only and say why.
4. If you added mitigations, preview again to confirm they worked, then call submit_spec with your assumptions.
Default decision for each slice finding (override only with evidence, and say what the evidence was):
- late_start: zeros before a product's first sale are not demand; apply the suggested min_date.
- item_renumbered: with series_by "item", apply the suggested stitch_successor; otherwise it has no effect.
- stopped: exclude_series, unless the user asked about that item specifically (then flag_only and say it stopped).
- empty_series: exclude_series.
- level_shift: check the monthly totals around the date. An abrupt jump that coincides with a recoding, renumbering or
  first sale is an artifact (min_date after it); a gradual ramp is real demand (flag_only with the check name).
- outlier_months: check line counts and the largest single line in those months. Cap only a clear data error.
- zero_months, store_churn, item_discontinued: usually real; flag_only with the check name.
Aim for about 10 tool calls. Ask the user (ask_user) only when a wrong guess would change the answer, and at most once.
If the request cannot be served as asked (a product or place not in the data, a horizon over {max_h} months), do not
submit; explain why in plain words and suggest what you could do instead. Never substitute a different place, product
or horizon for the one the user asked for. Write plain text without em dashes.

## Spec (JSON string passed to preview_spec and submit_spec)
{{
  "title": "short title, e.g. Tito's minis, Polk County, next 5 months",
  "target": "sales_bottles" | "sales_dollars" | "sales_liters",   // bottles unless dollars/revenue or liters/volume asked
  "horizon": 1-{max_h},                                             // months ahead
  "product": {{"kind": "all" | "item" | "category" | "vendor", "codes": [...], "label": "readable name"}},
  "region":  {{"kind": "statewide" | "county" | "city" | "store", "codes": [...], "label": "readable name"}},
  "series_by": "none" | "county" | "city" | "item" | "category",   // one series per value; "none" = one total
  "features": ["calendar", "population"],                           // keep the default unless told otherwise
  "mitigations": [{{"rule": ..., "params": {{...}}, "reason": "...", "source": "agent"}}]
}}
Codes: item -> item_no values; category -> category_code; vendor -> vendor_no; county -> 5-digit county_fips;
city -> city names exactly as stored (sales.store.city); store -> store_no.
Products: a brand means all its sizes unless a size is named ("minis" = 50 ml). Include every item number of the same
product, including discontinued, renumbered and temporary ones, so the history is complete.
Places: a county name -> that county; a city name -> the city, or ask if the user might mean the metro or county.
"Iowa" or no place -> statewide. Include every stored spelling of a city.
series_by: use it when the user asks for each / by / per / broken out; otherwise "none".

## Request-level mitigations (the only fixes the harness accepts)
- stitch_successor {{"column": "item_no", "from": old, "to": new}}: an item renumbered; merges old into new. Only matters
  when series_by is "item" (summed series already include both).
- normalize_values {{"column": "city", "mapping": {{variant: canonical}}}}: spelling variants of one city.
- min_date {{"date": "YYYY-MM-DD", "series": [codes]}}: a series whose earlier values are not comparable (launched
  mid-history, or recoded). Omit "series" to move the start of every series.
- exclude_series {{"series": [codes]}}: drop a series that stopped selling or is not part of the question.
- cap_outliers {{"k": 5}}: only for spikes you have evidence are data errors (e.g. a single implausible line), never
  for promotions or bulk orders. Capping changes model inputs only; forecasts are still scored on the real values.
- flag_only {{"check": finding check name, "series": [codes]}}: you reviewed a finding and are deliberately leaving the
  data as is; the reason says why (e.g. real demand). Name the check so the dashboard marks the finding as reviewed.

## Approved known-issues register (the harness applies these automatically; know them, do not re-fix them)
{register}

## Warehouse tables (read-only)
{schema}
"""


def narrate(client, facts, usage):
    """Plain-English summary written only from the harness's numbers."""
    msg = client.messages.create(
        model=MODEL, max_tokens=2000,
        system="You write the two-to-four sentence summary at the top of a forecast dashboard for a business reader. "
               "Quote only numbers and percentages that appear in the facts JSON; never compute new ones (no ranges you "
               "derived yourself). Round sensibly. Say how the forecast compares with the "
               "same months last year and how far to trust it (the backtest against the seasonal-naive baseline). "
               "Mention any unvalidated or skipped series. No em dashes.",
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


def ask(request, interactive=False, train=True, log=print):
    client = anthropic.Anthropic()
    system = SYSTEM.format(max_h=MAX_HORIZON, register=register_text(), schema=schema_text())
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
            thinking={"type": "adaptive"}, output_config={"effort": "high"},
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
            if not nudged and spec is None and "?" not in text[-200:]:
                # the model stopped without submitting or explaining; one reminder, then accept its answer
                nudged = True
                messages.append({"role": "user", "content": "If this request can be served, call submit_spec now; "
                                                            "otherwise explain in one short paragraph why not."})
                continue
            return {"status": "no_forecast", "message": text, "usage": usage, "trace": trace,
                    "seconds": round(time.time() - t0, 1)}

        results = []
        for call in calls:
            t1 = time.time()
            args = call.input
            if call.name == "find_values":
                out = tools.find_values(args["kind"], args["text"])
            elif call.name == "run_select":
                out = tools.run_select(args["sql"])
            elif call.name == "preview_spec":
                out, _ = tools.preview(args["spec_json"])
            elif call.name == "ask_user":
                out = (input(f"\n{args['question']}\n> ") if interactive else
                       "No answer available (non-interactive run). If the request is ambiguous, choose the most "
                       "likely reading and list it in your assumptions. If it cannot be served as asked, do not "
                       "submit; explain instead.")
            elif call.name == "propose_register_issue":
                out = tools.propose_issue({**args, "request": request})
            elif call.name == "submit_spec":
                candidate, err = tools.parse_spec(args["spec_json"])
                if err:
                    out = err
                else:
                    spec, assumptions, out = candidate, args["assumptions"], "Accepted. The harness is running it."
            else:
                out = f"Error: unknown tool {call.name}"
            is_error = str(out).startswith("Error")
            trace.append({"turn": turn + 1, "tool": call.name, "input": short(json.dumps(args), 400),
                          "result": short(out), "seconds": round(time.time() - t1, 1), "error": is_error})
            log(f"  [{turn + 1}] {call.name}: {short(json.dumps(args), 160)}" + ("  -> ERROR" if is_error else ""))
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": str(out), "is_error": is_error})
        if spec is not None:
            break
        messages.append({"role": "user", "content": results})
    else:
        return {"status": "error", "message": f"No spec after {MAX_TURNS} turns.", "usage": usage, "trace": trace}

    usage["agent_seconds"] = round(time.time() - t0, 1)
    log(f"  spec submitted after {len(trace)} tool calls, {usage['agent_seconds']}s, about ${usage['est_cost_usd']:.3f}")
    agent = {"request": request, "assumptions": assumptions, "trace": trace, "usage": usage}
    if not train:  # spec only: used by the evals to score the agent's decisions without training models
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
