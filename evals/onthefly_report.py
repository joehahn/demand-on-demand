"""
onthefly_report.py: run a few week / quarter / year requests through the forecast path (dod/forecast.py) and
publish docs/onthefly.html, explained for a general audience.

    python evals/onthefly_report.py            # run the requests (about $0.15 of API calls), then build the page
    python evals/onthefly_report.py --page     # rebuild the page from the saved results only
    python evals/onthefly_report.py --only "<request>"   # rerun one saved request, keep the others
"""
import html
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import agent, forecast  # noqa: E402
from dod.agent import RULES  # noqa: E402
from dod.viz import AQUA, BLUE, Plots, line, page, style, table  # noqa: E402

HERE = Path(__file__).parent
SAVED = HERE / "onthefly.json"
OUT = HERE.parent / "docs" / "onthefly.html"
REPO = "https://github.com/joehahn/demand-on-demand/blob/main"
REQUESTS = [
    "Weekly forecast of Tito's minis in Des Moines for the next 8 weeks",
    "Quarterly forecast of Fireball revenue in Linn County for the next 2 quarters",
    "show me weekly forecast of Cream liqueur bottles sold across all of iowa, twelve weeks out",
    "Total Iowa vodka sales dollars for the next year",
    "Weekly bottles of liquor ordered by all Hy-Vee stores in Iowa for the next 8 weeks",
]
UNIT = {"week": "week", "month": "month", "quarter": "month", "year": "month"}


def run_all(only=None):
    saved = {r["request"]: r for r in json.loads(SAVED.read_text())} if only else {}
    out = []
    for req in REQUESTS:
        if only and req != only:
            out.append(saved[req])
            continue
        print(f"== {req}", flush=True)
        r = forecast.forecast(req, log=lambda *a: None)
        if r["status"] != "ok":
            out.append({"request": req, "status": r["status"], "message": r.get("message", "")})
            continue
        s, plan = r["summary"], r["plan"]
        res, wide = s["res"], s["panel"].series
        out.append({"request": req, "status": "ok", "title": plan.title, "grain": plan.grain, "horizon": plan.horizon,
                    "model_grain": s["grain"], "sql": plan.sql, "assumptions": plan.assumptions,
                    "rel_mae": res["test_rel_mae"], "test_window": [str(d.date()) for d in res["test_window"]],
                    "history": {str(k.date()): (None if pd.isna(v) else float(v))
                                for k, v in wide.sum(axis=1, min_count=1).items()},
                    "forecast": [{"period": str(m.date()), "pred": float(p), "lo": float(lo), "hi": float(hi)}
                                 for m, p, lo, hi in res["forecast"].groupby("month")[["pred", "lo", "hi"]].sum()
                                 .itertuples()],
                    "dashboard": s["dashboard"], "cost": r["usage"]["est_cost_usd"],
                    "seconds": r["usage"].get("agent_seconds", 0) + s["seconds"]})
        print(f"   rel {out[-1]['rel_mae']:.3f}", flush=True)
    SAVED.write_text(json.dumps(out, indent=1))


def accuracy(rel, grain):
    pct = round(abs(1 - rel) * 100)
    period = {"week": "week", "quarter": "quarter"}.get(grain, "month")
    word = "more" if rel < 1 else "less"
    return f"{pct}% {word} accurate than the same {period} last year" if pct else f"as accurate as the same {period} last year"


def figure(r):
    hist = pd.Series(r["history"]).dropna()
    hist.index = pd.to_datetime(hist.index)
    keep = {"week": 156, "quarter": 20}.get(r["model_grain"], 48)
    hist = hist.iloc[-keep:]
    fc = pd.DataFrame(r["forecast"])
    fc["period"] = pd.to_datetime(fc.period)
    f = go.Figure([go.Scatter(x=list(fc.period) + list(fc.period[::-1]), y=list(fc.hi) + list(fc.lo[::-1]),
                              fill="toself", fillcolor="rgba(27,175,122,0.18)", line=dict(width=0), mode="lines",
                              hoverinfo="skip", name="80% range"),
                   line(hist.index, hist.values, "Actual", BLUE), line(fc.period, fc.pred, "Forecast", AQUA)])
    f.update_traces(selector=dict(name="Forecast"), mode="lines+markers", marker=dict(size=7))
    f.update_traces(hovertemplate="%{y:,.0f}", selector=dict(type="scatter"))
    f = style(f, r["title"], f"per {UNIT[r['grain']]}", height=330, legend=True)
    return f.update_layout(legend=dict(orientation="h", y=-0.15, yanchor="top", x=0, xanchor="left"))


# Requests whose full dashboard is published (copied into docs/examples/ by make_examples.py).
DASHBOARDS = {"show me weekly forecast of Cream liqueur bottles sold across all of iowa, twelve weeks out":
              "examples/cream_liqueur_by_week_next_12_weeks.html"}


def build():
    rows = json.loads(SAVED.read_text())
    plot = Plots(numbered=True, toolbar=False)
    sections = []
    for r in rows:
        if r["status"] != "ok":
            sections.append(f"<h2>{html.escape(r['request'])}</h2><p>No forecast: {html.escape(r['message'])}</p>")
            continue
        fc = pd.DataFrame(r["forecast"])
        total = fc.pred.sum()
        what = {"year": "next year: forecast by month, 12 months ahead",
                "quarter": f"next {r['horizon']} quarter{'s' if r['horizon'] > 1 else ''}: forecast by month, "
                           f"{3 * r['horizon']} months ahead"}.get(
            r["grain"], f"by {r['grain']}, {r['horizon']} {r['grain']}{'s' if r['horizon'] > 1 else ''} ahead")
        tbl = table(fc.assign(period=fc.period.str[:10]).rename(columns={"pred": "forecast", "lo": "low (10%)",
                                                                         "hi": "high (90%)"}),
                    {c: (lambda v: f"{v:,.0f}") for c in ("forecast", "low (10%)", "high (90%)")})
        detail = (f"<details><summary>the AI's query and assumptions</summary><pre>{html.escape(r['sql'])}</pre>"
                  f"<ul>{''.join(f'<li>{html.escape(a)}</li>' for a in r['assumptions'])}</ul></details>")
        sections.append(
            f"<h2>&ldquo;{html.escape(r['request'])}&rdquo;</h2>"
            f"<p class=\"readas\"><span>Read as</span> {html.escape(r['title'])} &middot; {html.escape(what)}</p>"
            + (f"<p><strong><a href=\"{DASHBOARDS[r['request']]}\">Full dashboard for this forecast</a></strong> "
               f"(the same layout as the monthly examples)</p>" if r["request"] in DASHBOARDS else "")
            + f"<div class=\"tiles\"><div class=\"tile\"><div class=\"v\">{total:,.0f}</div><div class=\"k\">forecast total"
            f"</div></div><div class=\"tile\"><div class=\"v\">{round(abs(1 - r['rel_mae']) * 100)}%</div><div class=\"k\">"
            f"{html.escape(accuracy(r['rel_mae'], r['model_grain']).split('% ', 1)[-1])} (Test period)</div></div>"
            f"<div class=\"tile\"><div class=\"v\">{r['seconds']:.0f} s &middot; ${r['cost']:.2f}</div>"
            f"<div class=\"k\">to build from scratch</div></div></div>"
            + f"{plot(figure(r))}{tbl}{detail}")
    body = f"""
<p class="note"><a href="index.html">demand-on-demand</a> &middot; <a href="differential.html">AI-written SQL vs a
reference</a> &middot; <a href="https://github.com/joehahn/demand-on-demand">GitHub</a></p>
<h1>Forecasts by week, quarter or year</h1>
<p>Every forecast on this site starts the same way: the AI agent writes one SQL query that picks the order lines for
the request, and names the time grain (week, month, quarter or year) and how far ahead. Fixed code does the rest:</p>
<ul>
<li><strong>The AI decides what to forecast:</strong> which order lines, which measure, and how to label each series.</li>
<li><strong>Fixed code decides how:</strong> it adds the lines up by week or month, keeps complete periods only, fills
empty periods with 0, picks and tests the model (the baseline is the same period last year; weekly models refit every
4 weeks), and draws the results. Quarters and years are forecast by month: "next quarter" is the next three months (the
data rarely ends on a quarter's last day, so a calendar quarter ahead would include months already known).</li>
<li><strong>The AI's SQL is tested:</strong> on <a href="{REPO}/evals/sql_report.md">34 test requests, 3 runs each</a>,
its order lines are added up and compared with an answer key built by hand-checked fixed code.</li>
</ul>
<p>The AI writes its SQL following three rules for this warehouse's traps, found by <a href="differential.html">testing
AI-written SQL against a reference</a>, and the company's business definitions (what "minis" or "whiskey" means).</p>
<details><summary>The three rules</summary><pre>{html.escape(RULES)}</pre></details>
{"".join(sections)}
<p class="note">Code: <a href="{REPO}/dod/agent.py">the agent</a>, <a href="{REPO}/dod/history.py">adding up its order
lines</a>, <a href="{REPO}/dod/model.py">the grain-aware models</a> (use_grain), <a
href="{REPO}/evals/onthefly_report.py">this page</a>.</p>
<footer>Data: Iowa Liquor Sales, State of Iowa, via the Iowa Data Hub, CC BY 4.0; modified (see the data fixes page).</footer>"""
    return page("Forecasts by Any Grain", body)


if __name__ == "__main__":
    if "--page" not in sys.argv:
        run_all(sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None)
    OUT.write_text(build())
    print(f"wrote {OUT}")
