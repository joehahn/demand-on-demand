"""
onthefly_report.py: run a few week / quarter / year requests through the on-the-fly path (dod/onthefly.py) and
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
from dod import onthefly  # noqa: E402
from dod.nl2sql import RULES  # noqa: E402
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
UNIT = {"week": "week", "month": "month", "quarter": "quarter", "year": "month"}


def run_all(only=None):
    saved = {r["request"]: r for r in json.loads(SAVED.read_text())} if only else {}
    out = []
    for req in REQUESTS:
        if only and req != only:
            out.append(saved[req])
            continue
        print(f"== {req}", flush=True)
        r = onthefly.forecast(req, log=lambda *a: None)
        if r["status"] != "ok":
            out.append({"request": req, "status": r["status"], "message": r.get("message", "")})
            continue
        res, wide = r["res"], r["wide"]
        out.append({"request": req, "status": "ok", "title": r["title"], "grain": r["grain"], "horizon": r["horizon"],
                    "model_grain": r["model_grain"], "sql": r["sql"], "scope": r["reference_scope"],
                    "assumptions": r["assumptions"], "check": r["check"], "rel_mae": res["test_rel_mae"],
                    "test_window": [str(d.date()) for d in res["test_window"]],
                    "history": {str(k.date()): (None if pd.isna(v) else float(v))
                                for k, v in wide.sum(axis=1, min_count=1).items()},
                    "forecast": [{"period": str(m.date()), "pred": float(p), "lo": float(lo), "hi": float(hi)}
                                 for m, p, lo, hi in res["forecast"].groupby("month")[["pred", "lo", "hi"]].sum()
                                 .itertuples()],
                    "cost": r["usage"]["est_cost_usd"], "seconds": r["usage"].get("agent_seconds", 0) + r["harness_seconds"]})
        print(f"   {out[-1].get('check', {}).get('status')}  rel {out[-1].get('rel_mae', float('nan')):.3f}", flush=True)
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


# What a failed cross-check meant, found by reading the AI's query and form fill (evals/onthefly.json).
NOTES = {
    "Weekly bottles of liquor ordered by all Hy-Vee stores in Iowa for the next 8 weeks":
        "Why it failed: the AI's query selects every store named Hy-Vee (207 of them), which is right. To fill in the "
        "form it used the store search, which showed only 40 stores, so its form listed 40. The check caught that the "
        "two disagree. Fixed since: the store search now says when more stores match, and the AI leaves the form empty "
        "when it can only list part of a group.",
}


# Requests with a full dashboard (built by dod/onthefly.forecast, copied into docs/examples/).
DASHBOARDS = {"show me weekly forecast of Cream liqueur bottles sold across all of iowa, twelve weeks out":
              "examples/cream_liqueur_by_week_next_12_weeks.html"}


def check_text(c):
    if c["status"] == "passed":
        return f"Passed: the AI's data, summed by month, equals the reference in all {c['months']} months."
    if c["status"] == "failed":
        return (f"Failed in {c['bad_months']} of {c['months']} months (AI total {c['ai_total']:,.0f} vs reference "
                f"{c['reference_total']:,.0f}): the AI's query and its own form fill describe different data, so a "
                f"person should look before trusting it.")
    return f"Not available: {c['why']}. The forecast still has its own backtest."


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
        what = (f"by {r['grain']}, {r['horizon']} {r['grain']}{'s' if r['horizon'] > 1 else ''} ahead" if r["grain"] != "year"
                else "next year: forecast by month, 12 months ahead, reported as the year's total")
        badge = {"passed": "&#10003; cross-check passed", "failed": "&#10007; cross-check failed",
                 "not available": "cross-check not available"}[r["check"]["status"]]
        tbl = table(fc.assign(period=fc.period.str[:10]).rename(columns={"pred": "forecast", "lo": "low (10%)",
                                                                         "hi": "high (90%)"}),
                    {c: (lambda v: f"{v:,.0f}") for c in ("forecast", "low (10%)", "high (90%)")})
        detail = (f"<details><summary>the AI's query, form fill and assumptions</summary><pre>{html.escape(r['sql'])}</pre>"
                  f"<p>Form fill for the cross-check: <code>{html.escape(r['scope'] or '(none: the form cannot express this)')}</code></p>"
                  f"<ul>{''.join(f'<li>{html.escape(a)}</li>' for a in r['assumptions'])}</ul></details>")
        sections.append(
            f"<h2>&ldquo;{html.escape(r['request'])}&rdquo;</h2>"
            f"<p class=\"readas\"><span>Read as</span> {html.escape(r['title'])} &middot; {html.escape(what)}</p>"
            + (f"<p><strong><a href=\"{DASHBOARDS[r['request']]}\">Full dashboard for this forecast</a></strong> "
               f"(the same layout as the monthly examples)</p>" if r["request"] in DASHBOARDS else "")
            + f"<div class=\"tiles\"><div class=\"tile\"><div class=\"v\">{total:,.0f}</div><div class=\"k\">forecast total"
            f"</div></div><div class=\"tile\"><div class=\"v\">{round(abs(1 - r['rel_mae']) * 100)}%</div><div class=\"k\">"
            f"{html.escape(accuracy(r['rel_mae'], r['model_grain']).split('% ', 1)[-1])} (Test period)</div></div>"
            f"<div class=\"tile\"><div class=\"v\">{badge}</div><div class=\"k\">{html.escape(check_text(r['check']))}"
            f"</div></div><div class=\"tile\"><div class=\"v\">{r['seconds']:.0f} s &middot; ${r['cost']:.2f}</div>"
            f"<div class=\"k\">to build from scratch</div></div></div>"
            + (f"<p class=\"note\">{html.escape(NOTES[r['request']])}</p>" if r["request"] in NOTES else "")
            + f"{plot(figure(r))}{tbl}{detail}")
    body = f"""
<p class="note"><a href="index.html">demand-on-demand</a> &middot; <a href="differential.html">AI-written SQL vs a
reference</a> &middot; <a href="https://github.com/joehahn/demand-on-demand">GitHub</a></p>
<h1>Forecasts by week, quarter or year, from AI-written SQL</h1>
<p>The main forecasts on this site are monthly, built by slot filling: the AI fills in a request form and fixed code
does everything else. This prototype lets the AI write the SQL instead, so it can serve requests the form does not
cover, such as weekly or quarterly forecasts or a group of stores. The split of work stays the same idea:</p>
<ul>
<li><strong>The AI decides what to forecast:</strong> it writes SQL that returns daily totals (which order lines, which
measure), and names the grain (week, month, quarter or year) and how far ahead.</li>
<li><strong>Fixed code decides how:</strong> it buckets the days into the grain, keeps complete periods only, fills
empty periods with 0, picks and tests the model (the baseline is the same period last year; weekly models refit every
4 weeks), and draws the results. A yearly request is forecast by month and summed.</li>
<li><strong>Fixed code also checks the AI's data:</strong> wherever the request form can describe the same data, the AI
fills it in too, and its daily totals summed by month must equal the monthly series the tested slot-filling path builds
independently. When the form cannot describe the request, the page says so.</li>
</ul>
<p>The AI writes its SQL with three rules for this warehouse's traps, found by <a href="differential.html">testing
AI-written SQL against the reference</a>. Same Claude agent, lookup tools and read-only login as the main path.</p>
<details><summary>The three rules</summary><pre>{html.escape(RULES)}</pre></details>
{"".join(sections)}
<p class="note">Code: <a href="{REPO}/dod/onthefly.py">the on-the-fly path</a>, <a href="{REPO}/dod/model.py">the
grain-aware harness</a> (use_grain), <a href="{REPO}/evals/onthefly_report.py">this page</a>.</p>
<footer>Data: Iowa Liquor Sales, State of Iowa, via the Iowa Data Hub, CC BY 4.0; modified (see the data fixes page).</footer>"""
    return page("Forecasts by Any Grain", body)


if __name__ == "__main__":
    if "--page" not in sys.argv:
        run_all(sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None)
    OUT.write_text(build())
    print(f"wrote {OUT}")
