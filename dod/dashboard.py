"""One self-contained HTML page per forecast: the answer, how much to trust it, what was done to the data,
and exactly what ran."""
import html
import json

import pandas as pd
import plotly.graph_objects as go

from .viz import AQUA, BLUE, ORANGE, Plots, line, page, style, table

MAX_PANELS = 8   # small multiples beyond this fold into the table only
HISTORY_MONTHS = 48


def esc(s):
    return html.escape(str(s))


def fig_series(code, label, wide, bt, fc, test_start):
    """Actuals, what the model would have said one month ahead during the test, and the forecast."""
    hist = wide[code].dropna().iloc[-HISTORY_MONTHS:]
    one = bt[(bt.series == code) & (bt.step == 1)].sort_values("month")
    f = fc[fc.series == code].sort_values("month")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(f.month) + list(f.month[::-1]), y=list(f.hi) + list(f.lo[::-1]),
                             fill="toself", fillcolor="rgba(27,175,122,0.18)", line=dict(width=0), mode="lines",
                             hoverinfo="skip", name="80% range"))
    fig.add_trace(line(hist.index, hist.values, "Actual", BLUE))
    fig.add_trace(line(one.month, one.pred, "Backtest, 1 month ahead", ORANGE, dash="dot"))
    fig.add_trace(line(f.month, f.pred, "Forecast", AQUA))
    fig.update_traces(selector=dict(name="Forecast"), mode="lines+markers", marker=dict(size=8))
    if len(one) == 0:
        fig.update_layout(title_text=f"{label} (not backtested)")
    fig.add_vline(x=test_start, line=dict(color="rgba(137,135,129,0.6)", width=1, dash="dash"))
    fig.update_traces(hovertemplate="%{y:,.0f}", selector=dict(type="scatter"))
    return style(fig, label, height=360, legend=True)


def fig_accuracy(per_step):
    fig = go.Figure([
        go.Bar(x=per_step.step, y=per_step.wape * 100, name="Model", marker_color=BLUE),
        go.Bar(x=per_step.step, y=per_step.wape_naive * 100, name="Same month last year", marker_color=ORANGE),
    ])
    fig.update_traces(hovertemplate="%{y:.1f}% error<extra>%{fullData.name}</extra>")
    fig.update_xaxes(title="months ahead", dtick=1)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    return style(fig, "Backtest error by months ahead (lower is better)", "% error (WAPE)", height=300,
                 legend=True).update_layout(hovermode="x unified")


def fig_change(change, labels):
    """Before/after for one data fix: dotted orange is the data before the fix, blue after."""
    p, code = change["params"], change.get("series")
    fig = go.Figure()
    if change["rule"] == "stitch_successor":
        old, new = str(p["from"]), str(p["to"])
        before, after = change["before"], change["after"]
        if old in before:
            fig.add_trace(line(before.index, before[old], f"before: item {old}", ORANGE, dash="dot"))
        if new in before:
            fig.add_trace(line(before.index, before[new], f"before: item {new}", AQUA, dash="dot"))
        if new in after:
            fig.add_trace(line(after.index, after[new], f"after: item {new} (joined)", BLUE))
        title = f"Joining item {old} into {new}"
    elif change["rule"] == "normalize_values":
        before, after = change["before"], change["after"]
        for src, dst in list(p.get("mapping", {}).items())[:3]:
            if src in before:
                fig.add_trace(line(before.index, before[src], f"before: {src}", ORANGE, dash="dot"))
            if dst in after:
                fig.add_trace(line(after.index, after[dst], f"after: {dst}", BLUE))
        title = "Normalizing spellings"
    else:
        fig.add_trace(line(change["before"].index, change["before"].values, "before", ORANGE, dash="dot"))
        fig.add_trace(line(change["after"].index, change["after"].values, "after", BLUE))
        title = f"{change['rule']}: {labels.get(code, code)}"
    fig = style(fig, title, height=280, legend=True)
    return fig.update_layout(legend=dict(orientation="h", y=-0.18, x=0, xanchor="left", yanchor="top"),
                             margin=dict(b=70))


def build(spec, panel, decisions, findings, res, usage=None, agent=None):
    plot = Plots()
    wide, fc, bt, ps = panel.series, res["forecast"], res["backtest"], res["per_step"]
    labels = panel.labels
    months = f"{fc.month.min():%b %Y} to {fc.month.max():%b %Y}"
    unit = {"sales_bottles": "bottles", "sales_dollars": "dollars", "sales_liters": "liters"}[spec.target]
    total = fc.pred.sum()
    last_year = sum(wide.at[m - pd.DateOffset(years=1), c] for m, c in zip(fc.month, fc.series)
                    if (m - pd.DateOffset(years=1)) in wide.index)
    yoy = total / last_year - 1 if last_year else float("nan")
    rel = res["test_rel_mae"]
    verdict = (f"{(1 - rel):.0%} more accurate than repeating last year" if rel < 0.95 else
               "about as accurate as repeating last year" if rel <= 1.05 else
               f"{(rel - 1):.0%} less accurate than repeating last year")
    best = res["best"]
    model_name = "seasonal naive (same month last year)" if best["model"] == "seasonal_naive" else \
        f"{best['model']}, {best['target']} target"
    money = "$" if unit == "dollars" else ""
    tiles = [
        (f"{money}{total:,.0f}", f"forecast {unit}, {months}"),
        (f"{yoy:+.1%}", "vs the same months last year"),
        (f"{bt.dropna(subset=['actual']).pipe(lambda d: (d.actual - d.pred).abs().sum() / d.actual.sum()):.1%}",
         "average backtest error"),
        (f"{rel:.2f}", "error relative to baseline (below 1 is better)"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>'
                         for v, k in tiles)

    # forecast table: one row per series and month
    ft = fc.assign(series=fc.series.map(lambda c: labels.get(c, c)), month=fc.month.dt.strftime("%Y-%m"))
    ft = ft[["series", "month", "pred", "lo", "hi"]].rename(columns={"pred": "forecast", "lo": "low (10%)", "hi": "high (90%)"})
    num = lambda v: f"{v:,.0f}"

    charts = "".join(plot(fig_series(c, labels.get(c, c), wide, bt, fc, res["test_window"][0]))
                     for c in [c for c in wide.columns if c in set(fc.series)][:MAX_PANELS])
    more = f'<p class="note">{len(wide.columns) - MAX_PANELS} more series are in the table only.</p>' \
        if len(wide.columns) > MAX_PANELS else ""

    ps_show = ps.assign(wape=ps.wape.map("{:.1%}".format), wape_naive=ps.wape_naive.map("{:.1%}".format),
                        skill_vs_naive=ps.skill_vs_naive.map("{:+.0%}".format))[
        ["step", "folds", "wape", "wape_naive", "skill_vs_naive", "reliability"]].rename(
        columns={"step": "months ahead", "wape": "model error", "wape_naive": "baseline error",
                 "skill_vs_naive": "improvement"})

    # data issues
    reg = pd.DataFrame(decisions)
    reg_used = reg[reg.action != "not_relevant"][["issue_id", "action", "note"]]
    reg_skip = reg[reg.action == "not_relevant"][["issue_id", "note"]]
    if findings:
        fnd = pd.DataFrame(findings)
        fnd["fix"] = fnd.suggested_rule.fillna("none") + fnd.suggested_params.map(lambda p: f" {json.dumps(p)}" if p else "")
        fnd["status"] = fnd.resolution.map({"fixed": "fixed in this run", "reviewed": "reviewed, left as is",
                                            "no_effect": "no effect here", "open": "reported, not fixed"})
        fnd["message"] = fnd.message + fnd.review_note.map(lambda n: f" Agent: {n}" if n else "")
        fnd_html = table(fnd[["check", "severity", "message", "fix", "status"]])
    else:
        fnd_html = '<p class="note">No slice-level problems found.</p>'
    mit = [m for m in spec.mitigations]
    mit_html = table(pd.DataFrame([{"rule": m.rule, "params": json.dumps(m.params), "source": m.source, "reason": m.reason}
                                   for m in mit])) if mit else '<p class="note">No request-level fixes applied.</p>'
    change_charts = "".join(f'<p class="note">{esc(ch.get("note") or "")}</p>' + plot(fig_change(ch, labels))
                            for ch in panel.changes if "before" in ch)
    skipped = res.get("skipped", {})
    skipped_html = "".join(f'<p class="warn">Not forecast: {esc(labels.get(c, c))}, {esc(why)}.</p>'
                           for c, why in skipped.items())
    skipped_html += "".join(f'<p class="warn">Unvalidated: {esc(labels.get(c, c))} was too new to backtest during the '
                            f'test window, so its forecast comes from the pooled model with no track record of its own. '
                            f'Treat it as indicative.</p>' for c in res.get("unvalidated", []))

    grid = res["grid"].head(10).dropna(axis=1, how="all").copy()   # hide parameters no shown model uses
    grid["rel_mae"] = grid.rel_mae.map("{:.3f}".format)
    grid = grid.rename(columns={"rel_mae": "tuning error vs baseline"}).fillna("")
    abl = res["ablation"].assign(rel_mae=res["ablation"].rel_mae.map("{:.3f}".format))
    tw, uw = res["test_window"], res["tune_window"]
    cost = ""
    if usage:
        cost = (f"<p>Agent: {esc(usage.get('model'))}, {usage.get('calls', 0)} API calls, "
                f"{usage.get('input_tokens', 0) + usage.get('cache_read_tokens', 0) + usage.get('cache_write_tokens', 0):,} "
                f"input tokens ({usage.get('cache_read_tokens', 0):,} read from cache) and {usage.get('output_tokens', 0):,} "
                f"output tokens, about ${usage.get('est_cost_usd', 0):.2f}, {usage.get('agent_seconds', 0):.0f}s of agent "
                f"time.</p>")
    ask_html, trace_html = "", ""
    if agent:
        assumptions = "".join(f"<li>{esc(a)}</li>" for a in agent.get("assumptions", []))
        ask_html = (f'<p class="asked">Asked: &ldquo;{esc(agent["request"])}&rdquo;</p>'
                    + (f'<p>{esc(agent["summary"])}</p>' if agent.get("summary") else "")
                    + (f'<p class="note">Assumptions the agent made:</p><ul class="note">{assumptions}</ul>'
                       if assumptions else ""))
        tr = pd.DataFrame(agent.get("trace", []))
        if not tr.empty:
            trace_html = ("<h2>What the agent did</h2><p>Every tool call, in order. All tools are read-only; the only "
                          "way the agent affects the result is the spec it submits, which the harness validates.</p>"
                          + table(tr[["turn", "tool", "input", "result"]]))

    body = f"""
<h1>{esc(spec.title)}</h1>
{ask_html}
<p>{esc(spec.product.label)} in {esc(spec.region.label)}: monthly {unit}, {months}. Model: {esc(model_name)},
{verdict} over a {len(bt.origin.unique())}-origin backtest on {tw[0]:%b %Y} to {tw[1]:%b %Y}, months the model never
trained on.</p>
<div class="tiles">{tiles_html}</div>
{skipped_html}
{charts}{more}
<p class="note">Dashed vertical line: start of the test window. Dotted orange: what the model would have forecast one
month ahead at each point in the test. Green band: 80% range from the backtest's own errors.</p>
{table(ft, {"forecast": num, "low (10%)": num, "high (90%)": num})}

<h2>How far to trust it</h2>
<p>Every month in the test window was forecast by a model trained only on earlier months, then compared with what
actually happened and with the simplest serious baseline: the same month last year.</p>
{plot(fig_accuracy(ps))}
{table(ps_show)}

<h2>What was done to the data</h2>
<h3>Known in advance (the approved register)</h3>
{table(reg_used)}
<details><summary class="note">{len(reg_skip)} register issues not relevant to this request</summary>{table(reg_skip)}</details>
<h3>Found in this run (slice checks)</h3>
{fnd_html}
<h3>Request-level fixes applied</h3>
{mit_html}
{change_charts}

<h2>How the model was chosen</h2>
<p>{len(res["grid"]) - 1} model configurations were compared on {uw[0]:%b %Y} to {uw[1]:%b %Y}, before the test window,
together with the baseline; a model had to beat the baseline there to be used. Feature groups were then kept or dropped on
the same tuning window. The test window below was not used for any choice.</p>
{table(grid)}
<p>Feature choice, scored on the test window for the record (below 1 beats the baseline):</p>
{table(abl)}

{trace_html}
<h2>Exactly what ran</h2>
{cost}
<p>Request spec:</p><pre>{esc(spec.model_dump_json(indent=2))}</pre>
<p>Aggregation SQL (generated by the harness, run under the read-only role):</p><pre>{esc(panel.sql)}</pre>

<footer>
Data: <a href="https://catalog.data.gov/dataset/iowa-liquor-sales">Iowa Liquor Sales</a>, State of Iowa, via the Iowa
Data Hub, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; modified (duplicates removed, aggregated).
Census population: U.S. Census Bureau. Not endorsed by the State of Iowa. Orders through {panel.data_end:%Y-%m-%d}.<br>
<a href="https://github.com/joehahn/demand-on-demand">demand-on-demand</a> by Joseph M. Hahn, Ph.D.,
<a href="https://jmh-datasciences.com">JMH DataSciences</a>.
</footer>"""
    return page(spec.title, body)
