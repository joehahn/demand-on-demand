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


def describe_config(cfg, unit, own, pooled):
    """One model configuration in plain words, e.g. 'ridge regression predicting monthly bottles directly ...'."""
    model = ("Ridge regression" if cfg["model"] == "ridge"
             else f"LightGBM (gradient-boosted trees, {cfg['num_leaves']} leaves)")
    target = {"level": f"predicting monthly {unit} directly",
              "diff": "predicting the change from the previous month",
              "yoy": "predicting the change from the same month last year"}[cfg["target"]]
    lags = cfg["lags"]
    lags = (f"from the last {lags} months" if isinstance(lags, int)
            else "from the values 1, 2, 3 and 12 months back" if list(lags) == [1, 2, 3, 12]
            else "from the values " + ", ".join(map(str, lags)) + " months back")
    history = "all history" if not cfg.get("train_years") else f"the last {cfg['train_years']} years"
    where = f"{own} plus {pooled}" if cfg.get("pool") else f"{own} only"
    alpha = f", regularization strength {cfg['alpha']:g}" if cfg["model"] == "ridge" else ""
    return f"{model} {target} {lags}{alpha}, trained on {where} ({history})"


def model_explanation(res, unit, spec, panel):
    """Plain-English account of how the final forecast was assembled, all from the harness's own results."""
    n_grid = len(res["grid"]) - 1
    uw = res["tune_window"]
    if res["best"]["model"] == "seasonal_naive":
        return (f"<p><strong>How this forecast is made.</strong> {n_grid} model configurations were scored on "
                f"{uw[0]:%b %Y} to {uw[1]:%b %Y}, before the test window. None beat simply repeating the same month "
                f"last year, so that is the forecast.</p>")
    ens, w = res["ensemble"], res["model_share"]
    own = "this series" if panel.series.shape[1] == 1 else f"these {panel.series.shape[1]} series"
    # companions are the product in its busiest counties, minus any county that is itself a requested series
    n_comp = 0 if panel.pool is None else panel.pool[0].shape[1]
    other = spec.series_by == "county" or spec.region.kind == "county"
    pooled = f"the same product in the {n_comp} busiest {'other ' if other else ''}counties"
    tuning = res["grid"][res["grid"].model != "seasonal_naive"].rel_mae.tolist()  # same order as the ranking
    items = "".join(f"<li>{esc(describe_config(c, unit, own, pooled))}. Selection error {tuning[i]:.3f} vs the "
                    f"baseline.</li>" for i, c in enumerate(ens))
    b = res["blend"]
    alone = lambda k: b[(b.models_averaged == k) & (b.model_share == 1.0)].tuning_rel_mae.iloc[0]
    chosen = b[(b.models_averaged == len(ens)) & (b.model_share == w)].tuning_rel_mae.iloc[0]
    what = ("the average of the top " + str(len(ens)) if len(ens) > 1 else "the single best")
    if w == 1.0:
        blend = (f"<p>The models alone scored better than any mix with last year's numbers, so the forecast is "
                 f"{what} with no blending (selection error {chosen:.3f}).</p>")
    else:
        sizes = " or ".join(str(k) for k in sorted(b.models_averaged.unique()))
        compare = f"{alone(1):.3f} for the best model alone" + (
            f" and {alone(len(ens)):.3f} for the {len(ens)}-model average alone" if len(ens) > 1 else "")
        blend = (f"<p>Each month's forecast is then {w:.0%} this model {'average' if len(ens) > 1 else 'forecast'} "
                 f"plus {1 - w:.0%} of what sold in the same month last year. That mix scored {chosen:.3f} on the "
                 f"model-selection window, the best of every combination tried ({sizes} models, 0% to 100% model), vs "
                 f"{compare}. The pieces make different mistakes, so the mix partly cancels them.</p>")
    return (f"<p><strong>How this forecast is made.</strong> {n_grid} model configurations were scored on "
            f"{uw[0]:%b %Y} to {uw[1]:%b %Y}, before the test window; a selection error below 1 beats repeating the same "
            f"month last year. The forecast uses {what}:</p><ol>{items}</ol>{blend}")


def stores_section(stores, spec, unit, last_month):
    """Which stores were added up: every store whose orders of this product in this region are in the series."""
    if stores is None or stores.empty:
        return ""
    recent = stores[stores.last_12_months > 0]
    t = stores.copy()
    t = t.rename(columns={"last_12_months": f"{unit}, last 12 months"})
    money = "$" if unit == "dollars" else ""
    return (f"<h3>Stores included</h3><p>The forecast adds up the orders of {len(stores):,} stores in "
            f"{esc(spec.region.label)} that bought {esc(spec.product.label)} since {spec.start[:7]}; "
            f"{len(recent):,} of them ordered it in the 12 months to {last_month:%b %Y}. Stores that closed still "
            f"count in the months they were open.</p>"
            f"<details><summary>Show the stores</summary>"
            f"{table(t, {f'{unit}, last 12 months': lambda v: f'{money}{v:,.0f}'})}</details>")


def read_as_html(spec, unit, months, wide, assumptions_html):
    """How the request was read, as one line of short phrases, with the agent's assumptions one click away."""
    n = wide.shape[1]
    series = "combined into one forecast" if spec.series_by == "none" else f"one forecast per {spec.series_by} ({n})"
    parts = [spec.product.label, spec.region.label, f"{unit} per month", months.replace(" ", "\u00a0"), series]
    why = (f'<details class="note"><summary>Why it was read this way</summary><ul>{assumptions_html}</ul></details>'
           if assumptions_html else "")
    return f'<p class="readas"><span>Read as</span> {" &middot; ".join(esc(x) for x in parts)}</p>{why}'


def fig_series(code, label, wide, bt, fc, windows, unit, train_start):
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
    # the three periods: model chosen (selection), model tested (rolling backtest), model applied (forecast)
    (tune_start, _), (test_start, _) = windows
    first_fc, end = f.month.min(), f.month.max() + pd.offsets.MonthBegin(1)
    for x0, x1, name, shade in [(max(tune_start, hist.index[0]), test_start, "Model selection", 0.05),
                                (test_start, first_fc, "Test", 0.10), (first_fc, end, "Forecast", 0.05)]:
        fig.add_vrect(x0=x0, x1=x1, fillcolor=f"rgba(137,135,129,{shade})", line_width=0, layer="below",
                      annotation_text=name, annotation_position="top left", annotation_font_size=11,
                      annotation_font_color="rgba(137,135,129,1)")
    # an arrow over the months the final model is trained on, ending where it is applied
    grey = "rgba(137,135,129,1)"
    top = max(hist.max(), f.hi.max())
    fig.update_yaxes(range=[0, top * 1.3])   # headroom above the data for the arrow
    fig.add_annotation(x=first_fc, y=top * 1.12, xref="x", yref="y", ax=hist.index[0], ay=0, axref="x", ayref="pixel",
                       text="", showarrow=True, arrowhead=2, arrowsize=1.2, arrowwidth=1.5, arrowcolor=grey)
    fig.add_annotation(x=hist.index[0] + (first_fc - hist.index[0]) / 2, y=top * 1.12, xref="x", yref="y",
                       yanchor="bottom", yshift=2, showarrow=False, font=dict(size=11, color=grey),
                       text=f"final model trained on {pd.Timestamp(train_start):%b %Y} to {wide.index[-1]:%b %Y}")
    fig.update_traces(hovertemplate="%{y:,.0f}", selector=dict(type="scatter"))
    fig = style(fig, label, f"{unit} per month", height=390, legend=True)
    return fig.update_layout(legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, xanchor="left"))  # clear of long titles


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


def build(spec, panel, res, usage=None, agent=None):
    plot = Plots(numbered=True)
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
    ens = res.get("ensemble") or []
    if best["model"] == "seasonal_naive":
        model_name = "seasonal naive (same month last year), since no model beat it in model selection"
    else:
        top = f"the average of the top {len(ens)}" if len(ens) > 1 else "the best"
        share = res.get("model_share", 1)
        model_name = (f"{top} of {len(res['grid']) - 1} configurations"
                      + (f", blended {share:.0%} with {1 - share:.0%} same month last year" if share < 1 else "")
                      + " (explained below)")
    money = "$" if unit == "dollars" else ""
    tiles = [
        (f"{money}{total:,.0f}", f"forecast {unit}, {months}"),
        (f"{yoy:+.1%}", "vs the same months last year"),
        (f"{bt.dropna(subset=['actual']).pipe(lambda d: (d.actual - d.pred).abs().sum() / d.actual.sum()):.0%}",
         f"typical monthly miss in the Test period ({res['test_window'][0]:%b %Y} to {res['test_window'][1]:%b %Y})"),
        (f"{round(abs(1 - rel) * 100)}%", ("more" if rel < 1 else "less") + " accurate than repeating the same month "
         "last year" if round(abs(1 - rel) * 100) else "as accurate as repeating the same month last year"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>'
                         for v, k in tiles)

    # forecast table: one row per series and month
    ft = fc.assign(series=fc.series.map(lambda c: labels.get(c, c)), month=fc.month.dt.strftime("%Y-%m"))
    ft = ft[["series", "month", "pred", "lo", "hi"]].rename(columns={"pred": "forecast", "lo": "low (10%)", "hi": "high (90%)"})
    num = lambda v: f"{v:,.0f}"

    charts = "".join(plot(fig_series(c, labels.get(c, c), wide, bt, fc, (res["tune_window"], res["test_window"]), unit,
                                    panel.start))
                     for c in [c for c in wide.columns if c in set(fc.series)][:MAX_PANELS])
    more = f'<p class="note">{len(wide.columns) - MAX_PANELS} more series are in the table only.</p>' \
        if len(wide.columns) > MAX_PANELS else ""

    ps_show = ps.assign(wape=ps.wape.map("{:.1%}".format), wape_naive=ps.wape_naive.map("{:.1%}".format),
                        skill_vs_naive=ps.skill_vs_naive.map("{:+.0%}".format))[
        ["step", "folds", "wape", "wape_naive", "skill_vs_naive", "reliability"]].rename(
        columns={"step": "months ahead", "wape": "model error", "wape_naive": "baseline error",
                 "skill_vs_naive": "improvement"})

    skipped_html = "".join(f'<p class="warn">Not forecast: {esc(labels.get(c, c))}, {esc(why)}.</p>'
                           for c, why in res.get("skipped", {}).items())
    skipped_html += "".join(f'<p class="warn">Unvalidated: {esc(labels.get(c, c))} was too new to backtest during the '
                            f'test window, so its forecast comes from the pooled model with no track record of its own. '
                            f'Treat it as indicative.</p>' for c in res.get("unvalidated", []))

    grid = res["grid"].head(10).dropna(axis=1, how="all").copy()   # hide parameters no shown model uses
    grid["rel_mae"] = grid.rel_mae.map("{:.3f}".format)
    grid = grid.rename(columns={"rel_mae": "selection error vs baseline"}).fillna("")
    abl = res["ablation"].assign(rel_mae=res["ablation"].rel_mae.map("{:.3f}".format))
    tw, uw = res["test_window"], res["tune_window"]
    cost = ""
    if usage:
        cost = (f"<p>Agent: {esc(usage.get('model'))}, {usage.get('calls', 0)} API calls, "
                f"{usage.get('input_tokens', 0) + usage.get('cache_read_tokens', 0) + usage.get('cache_write_tokens', 0):,} "
                f"input tokens ({usage.get('cache_read_tokens', 0):,} read from cache) and {usage.get('output_tokens', 0):,} "
                f"output tokens, about ${usage.get('est_cost_usd', 0):.2f}, {usage.get('agent_seconds', 0):.0f}s of agent "
                f"time.</p>")
    # a sleeve or pack of minis counts each bottle when its size is known; name the items where it is not
    units_note = ""
    if unit in ("bottles", "liters") and panel.unknown_packs:
        names = ", ".join(n.title() for n in panel.unknown_packs[:3])
        more = f" and {len(panel.unknown_packs) - 3} more" if len(panel.unknown_packs) > 3 else ""
        counts = "only one bottle's volume" if unit == "liters" else "as one bottle"
        units_note = (f" {len(panel.unknown_packs)} item(s) in this product ({esc(names)}{more}) are sold in sleeves or "
                      f"packs of unknown size, so each pack counts {counts}.")
    stores_html = stores_section(panel.stores, spec, unit, wide.index[-1])
    ask_html, trace_html = "", ""
    if agent:
        assumptions = "".join(f"<li>{esc(a)}</li>" for a in agent.get("assumptions", []))
        ask_html = (f'<p class="asked">&ldquo;{esc(agent["request"])}&rdquo;</p>' + read_as_html(spec, unit, months, wide, assumptions)
                    + (f'<p class="headline">{esc(agent["summary"])}</p>' if agent.get("summary") else ""))
        tr = pd.DataFrame(agent.get("trace", []))
        if not tr.empty:
            trace_html = ("<h2>What the agent did</h2><p>Every tool call, in order. All tools are read-only; the only "
                          "way the agent affects the result is the spec it submits, which the harness validates.</p>"
                          + table(tr[["turn", "tool", "input", "result"]]))

    body = f"""
<h1>{esc(spec.title)}</h1>
{ask_html or read_as_html(spec, unit, months, wide, "")}
<div class="tiles">{tiles_html}</div>
{skipped_html}
{charts}{more}
<ul class="note">
<li><strong>Model selection</strong> ({uw[0]:%b %Y} to {uw[1]:%b %Y}): the best of {len(res["grid"]) - 1} configurations is chosen.</li>
<li><strong>Test</strong> ({tw[0]:%b %Y} to {tw[1]:%b %Y}): retrained each month on earlier months only; dotted orange is its
1-month-ahead forecast.</li>
<li><strong>Forecast</strong> ({months}): retrained on {pd.Timestamp(panel.start):%b %Y} to {wide.index[-1]:%b %Y}, then applied.
Green band: 80% range.{units_note}</li>
</ul>
{table(ft, {"forecast": num, "low (10%)": num, "high (90%)": num})}

<h2>How far to trust it</h2>
<p>Every month in the test window was forecast by a model trained only on earlier months, then compared with what
actually happened and with the simplest serious baseline: the same month last year.</p>
{plot(fig_accuracy(ps))}
{table(ps_show)}

<h2>The data</h2>
<p>Monthly {unit} from {pd.Timestamp(panel.start):%b %Y} through {wide.index[-1]:%b %Y}, read from the clean warehouse: duplicate
export rows and zero lines removed, renumbered products joined, categories in today's taxonomy, one spelling per city.
See <a href="https://joehahn.github.io/demand-on-demand/data_fixes.html">what was fixed</a>. A series starts at its
first sale.</p>
{stores_html}

<h2>How the model was chosen</h2>
<p>Model: {esc(model_name)}; {verdict} over a {len(bt.origin.unique())}-origin backtest on {tw[0]:%b %Y} to
{tw[1]:%b %Y}, months the model never trained on.</p>
{model_explanation(res, unit, spec, panel)}
<p>Every configuration, with the baseline (a model had to beat it in model selection to be used). Feature groups were
then kept or dropped on the same months; the test window was not used for any choice.</p>
{table(grid)}
<p>Final choice, also in model selection: how many of the top configurations to average, and how much weight
to give them against "same month last year" (selection error vs baseline, lower is better):</p>
{table(res["blend"].rename(columns={"tuning_rel_mae": "selection_error"}), {"selection_error": lambda v: f"{v:.3f}", "model_share": lambda v: f"{v:.0%}"}) if len(res.get("blend", [])) else ""}
<p>Feature choice, scored on the test window for the record (below 1 beats the baseline):</p>
{table(abl)}

{trace_html}
<h2>Exactly what ran</h2>
{cost}
<p>Request spec:</p><pre>{esc(spec.model_dump_json(indent=2))}</pre>
<p>Aggregation SQL (generated by the harness, run under the read-only role):</p><pre>{esc(panel.sql)}</pre>

<footer>
Data: <a href="https://catalog.data.gov/dataset?q=iowa+liquor+sales">Iowa Liquor Sales</a>, State of Iowa, via the Iowa
Data Hub, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; modified (duplicates removed, aggregated).
Census population: U.S. Census Bureau. Not endorsed by the State of Iowa. Orders through {panel.data_end:%Y-%m-%d}.<br>
<a href="https://github.com/joehahn/demand-on-demand">demand-on-demand</a> by Joseph M. Hahn, Ph.D.,
<a href="https://jmh-datasciences.com">JMH DataSciences</a>.
</footer>"""
    return page(spec.title, body)
