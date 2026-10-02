"""One self-contained HTML page per forecast: the answer, how much to trust it, what was done to the data,
and exactly what ran."""
import ast
import html
import json


import numpy as np
import pandas as pd
import plotly.graph_objects as go

from . import model
from .viz import AQUA, BLUE, ORANGE, Plots, line, page, style, table

MAX_PANELS = 8   # small multiples beyond this fold into the table only

# Time grain: the page reads in the forecast's own periods. Months by default; weeks or quarters for the on-the-fly
# path (dod/onthefly.py). build() sets it from the request.
GRAIN_WORDS = {"month": dict(unit="month", adj="monthly", season=12, history=48),
               "week": dict(unit="week", adj="weekly", season=52, history=156),
               "quarter": dict(unit="quarter", adj="quarterly", season=4, history=20)}
W = {"grain": "month", **GRAIN_WORDS["month"]}


def set_grain(grain):
    W.clear()
    W.update(grain=grain, **GRAIN_WORDS[grain])


def units(n=2):
    """'month' or 'months' (or week, quarter)."""
    return W["unit"] + ("" if n == 1 else "s")


def when(d):
    """A period for reading: 'Sep 2026', 'Sep 7, 2026' (a week, by its Monday) or 'Q3 2026'."""
    d = pd.Timestamp(d)
    return {"week": f"{d:%b} {d.day}, {d.year}", "quarter": f"Q{d.quarter} {d.year}"}.get(W["grain"], f"{d:%b %Y}")


def stamp(d):
    """A period for tables: '2026-09', '2026-09-07' or '2026-Q3'."""
    d = pd.Timestamp(d)
    return {"week": f"{d:%Y-%m-%d}", "quarter": f"{d.year}-Q{d.quarter}"}.get(W["grain"], f"{d:%Y-%m}")


def back(d, k):
    """The period k periods before d (k < 0: after)."""
    return pd.Timestamp(d) - k * pd.tseries.frequencies.to_offset(model.GRAINS[W["grain"]]["freq"])


def base():
    """The baseline's name: 'same month last year' (or week, quarter)."""
    return f"same {W['unit']} last year"


def esc(s):
    return html.escape(str(s))


ERR_LABEL = "error vs last year\n(smaller is better)"   # the newline breaks the column header in two
def predicts(target):
    return {"level": f"the {W['adj']} value", "diff": f"change from last {W['unit']}",
            "yoy": f"change from the {base()}"}[target]


def lags_words(v):
    v = ast.literal_eval(v) if isinstance(v, str) else v   # grid values are stored as text, e.g. "[1, 2, 3, 12]"
    return f"the last {v} {units()}" if isinstance(v, int) else ", ".join(map(str, v[:-1])) + f" and {v[-1]} {units()} back"


def search_space(res, n_counties=15):
    """What model selection chose among, read from the harness's own settings so it cannot drift from the code."""
    pooled = "True" in set(res["grid"].get("pool", pd.Series(dtype=str)).astype(str))
    rows = [("Algorithm", "ridge regression; LightGBM (gradient-boosted trees)", len(model.FAMILY)),
            ("Model size", "ridge: regularization " + " or ".join(f"{a:g}" for a in model.FAMILY["ridge"]["alpha"])
             + "; LightGBM: " + " or ".join(map(str, model.FAMILY["lightgbm"]["num_leaves"])) + " leaves per tree", 2),
            ("Predicts", "; ".join(predicts(t) for t in model.COMMON["target"]), len(model.COMMON["target"])),
            ("Inputs", "; ".join(lags_words(l) for l in model.COMMON["lags"]), len(model.COMMON["lags"])),
            ("History used", "; ".join("all years" if y is None else f"the last {y} years" for y in model.COMMON["train_years"]),
             len(model.COMMON["train_years"])),
            ("Other counties", "learn from this forecast's own history only; or also from the same product's history in "
             f"the {n_counties} busiest counties (more examples of its seasonality and trend)" if pooled
             else "this series only (no other counties to learn from)", 2 if pooled else 1)]
    t = pd.DataFrame(rows, columns=["setting", "options", "choices"])
    count = " \u00d7 ".join(map(str, t.choices)) + f" = {int(t.choices.prod())}"
    return table(t, {"choices": lambda v: f"{v}"}), count


def grid_words(grid):
    """The top configurations in plain words, with their selection error."""
    def size(r):
        if r.model == "ridge":
            return f"regularization {float(r.alpha):g}"
        return f"{int(float(r.num_leaves))} leaves" if r.model == "lightgbm" else ""
    rows = []
    for r in grid.itertuples():
        if r.model == "seasonal_naive":
            rows.append((f"{base()} (baseline)", "", "", "", "", "", f"{r.rel_mae:.3f}"))
            continue
        rows.append(({"ridge": "ridge regression", "lightgbm": "LightGBM"}[r.model], size(r), predicts(r.target),
                      lags_words(r.lags), "all years" if r.train_years in (None, "None") else f"last {r.train_years} years",
                      "yes" if str(r.pool) == "True" else "no", f"{r.rel_mae:.3f}"))
    return pd.DataFrame(rows, columns=["algorithm", "size", "predicts", "inputs", "history", "other counties",
                                       ERR_LABEL])


def blend_details(res):
    """The last step of model selection, collapsed: every way of combining the top configurations with last year,
    and the one chosen (lowest error)."""
    b = res.get("blend")
    if b is None or not len(b):
        return ""
    # the row the harness used (ties go to fewer models, then more weight on them; see model.run)
    hit = b[(b.models_averaged == len(res.get("ensemble") or [])) & (b.model_share == res.get("model_share"))]
    chosen = hit.index[0] if len(hit) else None
    t = pd.DataFrame({"models averaged": b.models_averaged.astype(int),
                      "weight on the models": b.model_share.map(lambda v: f"{v:.0%}"),
                      "weight on last year": (1 - b.model_share).map(lambda v: f"{v:.0%}"),
                      ERR_LABEL: b.tuning_rel_mae.map(lambda v: f"{v:.3f}"),
                      "": ["\u2190 chosen" if i == chosen else "" for i in b.index]})
    return ("<details><summary>How the weights were chosen</summary><p>Every way of combining the best configuration, "
            f"or the average of the best few, with {base()}, scored in model selection. The lowest error "
            "wins; it sets the weights in the table above.</p>" + table(t) + "</details>")


def forecast_parts(res):
    """The forecast as a weighted mix: last year's same month (the baseline) plus each averaged model.
    Returns (name, weight, settings, selection error) rows, from the harness's own results."""
    if res["best"]["model"] == "seasonal_naive":
        return [(base(), 1.0, "", 1.0)]
    ens, w = res["ensemble"], res.get("model_share", 1)
    errs = res["grid"][res["grid"].model != "seasonal_naive"].rel_mae.tolist()  # same order as the ranking
    rows = [(base(), 1 - w, "", 1.0)] if w < 1 else []
    for i, c in enumerate(ens):
        size = f"regularization {c['alpha']:g}" if c["model"] == "ridge" else f"{c['num_leaves']} leaves"
        settings = "; ".join([predicts(c["target"]), lags_words(c["lags"]), size,
                              "all years" if not c.get("train_years") else f"last {c['train_years']} years",
                              "also other counties" if c.get("pool") else "this series only"])
        rows.append(({"ridge": "ridge regression", "lightgbm": "LightGBM"}[c["model"]], w / len(ens), settings, errs[i]))
    return rows


def model_explanation(res, unit, spec, panel):
    """How the forecast is made, in a few sentences and one small table."""
    uw, tw = res["tune_window"], res["test_window"]
    parts = forecast_parts(res)
    t = pd.DataFrame(parts, columns=["part", "weight", "settings", ERR_LABEL])
    tbl = table(t, {"weight": lambda v: f"{v:.0%}", ERR_LABEL: lambda v: f"{v:.2f}"}, bold=("part", "weight"))
    rel = res["test_rel_mae"]
    pct = round(abs(1 - rel) * 100)
    test = (f"{pct}% {'more' if rel < 1 else 'less'} accurate than last year alone" if pct
            else "about as accurate as last year alone")
    if [p[0] for p in parts] == [base()]:
        return (f"<p><strong>How this forecast is made.</strong> No model beat simply repeating the {base()} "
                f"in model selection ({when(uw[0])} to {when(uw[1])}), so that is the forecast.</p>")
    b = res["blend"]
    best_alone = b[(b.models_averaged == 1) & (b.model_share == 1.0)].tuning_rel_mae.iloc[0]
    chosen = b[(b.models_averaged == len(res["ensemble"])) & (b.model_share == res["model_share"])].tuning_rel_mae.iloc[0]
    lead = (f"Each {W['unit']}'s forecast is this weighted mix." if len(parts) > 1
            else f"Each {W['unit']}'s forecast comes from this model.")
    return (f"<p><strong>How this forecast is made.</strong> {lead} The weights won "
            f"model selection ({when(uw[0])} to {when(uw[1])}): their total misses were {chosen:.2f} times those of last "
            f"year alone, against {best_alone:.2f} for the best single model (smaller is better; 1.00 = as good as last year). In the Test period ({when(tw[0])} "
            f"to {when(tw[1])}) the mix was {test}.</p>{tbl}")


FEATURE_NAMES = {"calendar": "calendar (month of year, business days, holidays)", "population": "county population"}
FEATURE_COLUMNS = {"calendar": ["month_of_year", "business_days", "holidays"], "population": ["population"]}


def features_section(spec, panel, res, unit, fc):
    """The table the model learns from, for the first series: the target and the inputs it sees in each row,
    ending with the first period to forecast (inputs known, target not)."""
    ens = res.get("ensemble") or []
    if not ens:
        return ""
    code = panel.series.iloc[-W["season"]:].sum().idxmax()  # a breakout shows its largest series
    y = panel.series[code].dropna()
    lag_sets = [c["lags"] if isinstance(c["lags"], list) else list(range(1, c["lags"] + 1)) for c in ens]
    all_lags = sorted(set().union(*lag_sets))
    season = W["season"]
    shown = [k for k in all_lags if k in (1, 2, 3, season)] or all_lags[:4]
    first_fc = fc.month.min()
    months = list(y.index[-5:]) + [first_fc]
    t = pd.DataFrame(index=months)
    t[f"{unit} (target)"] = [y.get(m, "to forecast") for m in months]
    for k in shown:
        t[f"{k} {units(k)} back"] = [y.get(back(m, k)) for m in months]
    targets = {c["target"] for c in ens}
    yoy_col = f"change vs {season} {units()} back"
    if "yoy" in targets and season in shown:  # a model predicting the change from last year sees this as its target
        t[yoy_col] = [y[m] / y[back(m, season)] - 1 if m in y.index else None for m in months]
    chosen = res.get("feature_groups", [])
    ex = panel.exog[code]
    for col in [c for g in chosen for c in FEATURE_COLUMNS[g] if c in ex.columns]:
        t[col.replace("_", " ")] = [ex[col].get(m) for m in months]
    # column roles: the row label, the target(s) the models predict, and the inputs they predict from
    targets_cols = [f"{unit} (target)"] + ([yoy_col] if yoy_col in t.columns else [])
    input_cols = [c for c in t.columns if c not in targets_cols]
    t = t[targets_cols + input_cols]
    t.index = [stamp(m) for m in months]
    label_col = f"{W['unit']} of"
    t = t.rename_axis(label_col).reset_index()
    money = "$" if unit == "dollars" else ""
    num = lambda v: v if isinstance(v, str) else f"{money}{v:,.0f}"
    plain = lambda v: f"{v:,.0f}"
    measured = [f"{unit} (target)"] + [c for c in t.columns if c.endswith(" back")]  # in the forecast's unit
    fmt = {c: num if c in measured else plain for c in t.columns if c not in (label_col, yoy_col)}
    fmt[yoy_col] = lambda v: f"{v:+.0%}"
    rows = table(t, fmt)  # the "to forecast" cell makes the target a text column; align it with the numbers
    target = esc(f"{unit} (target)")
    rows = rows.replace(f'<th class="">{target}</th>', f'<th class="num">{target}</th>').replace(
        '<td class="">to forecast</td>', '<td class="num">to forecast</td>')
    group = lambda text, n, edge: (f'<th colspan="{n}" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;'
                                   f'border-bottom:2px solid var(--line);{edge}">{text}</th>')
    roles = ("<tr>" + group("row label", 1, "") + group("target: what the model predicts", len(targets_cols), "")
             + group("inputs: what the model predicts from", len(input_cols), "") + "</tr>")
    rows = rows.replace("<thead><tr>", "<thead>" + roles + "<tr>", 1)
    # name the models that see more lags than the table shows (whichever algorithm that is)
    wider = sorted({{"ridge": "ridge regression", "lightgbm": "LightGBM"}[c["model"]] for c, lags in zip(ens, lag_sets)
                    if len(lags) > len(shown)})
    notes = []
    if wider:
        notes.append(f"The {' and '.join(wider)} model{'s' if len(wider) > 1 else ''} use{'' if len(wider) > 1 else 's'} "
                     f"all {max(all_lags)} {units()} back, not only the ones shown.")
    dropped = [g for g in spec.features if g not in chosen]
    if dropped:
        notes.append("Tried in model selection and left out, because the model did better without them: "
                     + " and ".join(FEATURE_NAMES.get(g, g) for g in dropped) + ".")
    if any(c.get("pool") for c in ens) and panel.pool is not None:
        n = sum(bool(c.get("pool")) for c in ens)
        who = "The model also learns" if len(ens) == 1 else f"{n} of the {len(ens)} averaged models also learn{'s' if n == 1 else ''}"
        notes.append(f"Pooled: {who} from the same table for this product in the {panel.pool[0].shape[1]} busiest counties.")
    label = panel.labels.get(code, code) if panel.series.shape[1] > 1 else ""
    return (f"<h3>What the model sees</h3><p>One row per {W['unit']}{', for ' + esc(label) if label else ''}. The first "
            f"column only labels the row; the model learns to predict the target from the inputs. The last row is the "
            f"first {W['unit']} to forecast.</p>{rows}" + (f"<p class=\"note\">{' '.join(esc(n) for n in notes)}</p>" if notes else ""))


BIG_BUYER_SHARE = 0.25  # name a store on the dashboard when it has more than this share of the last 12 months


KIND_WORDS = {"item": "products", "category": "categories", "vendor": "vendors", "city": "cities", "county": "counties",
              "store": "stores"}
NAME_COLUMN = {"item": "item_desc", "category": "category_name", "vendor": "vendor_name", "city": "city",
               "county": "county_name", "store": "store_name"}


def text_table(text):
    """Rows of a tool's fixed-width table (pandas to_string: right-aligned columns), split at the header's column ends,
    so values with spaces in them stay whole."""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    head = lines[0]
    ends = [i + 1 for i in range(len(head)) if head[i] != " " and (i + 1 == len(head) or head[i + 1] == " ")]
    names = head.split()
    if len(ends) != len(names):
        return []
    rows = []
    for l in lines[1:]:
        if l.lstrip().startswith("("):   # e.g. "(12 more)"
            continue
        starts = [0] + ends[:-1]
        rows.append({n: l[a:b].strip() for n, a, b in zip(names, starts, ends[:-1] + [len(l)])})
    return rows


def agent_step(t):
    """One tool call as a plain sentence."""
    try:
        args = json.loads(t["input"])
    except (ValueError, TypeError):
        args = {}
    out = str(t.get("result", ""))
    if t.get("error"):
        return f"Tried {t['tool'].replace('_', ' ')}, which was rejected: {out[:160]}"
    if t["tool"] == "find_values":
        kind = args.get("kind", "")
        rows = text_table(out)
        def name(r):
            n = r.get(NAME_COLUMN.get(kind, ""), "").title()
            if kind == "item" and r.get("ml"):
                n += f" ({r['ml']} ml)"
            if kind == "county":
                n += " County"
            if kind == "city" and r.get("county_name"):
                n += f" ({r['county_name'].title()} County, {r.get('stores', '?')} stores)"
            return n
        found = [name(r) for r in rows if name(r)]
        shown = ", ".join(found[:3]) + (f" and {len(found) - 3} more" if len(found) > 3 else "")
        return f"Searched {KIND_WORDS.get(kind, kind)} for \u201c{args.get('text', '')}\u201d: found {shown or 'nothing'}."
    if t["tool"] == "preview_spec":
        detail = next((l.split("): ", 1)[-1] for l in out.splitlines() if l.startswith("- ")), "")
        first = out.splitlines()[0] if out else ""
        n = first.split(";", 1)[1].strip().rstrip(".") if ";" in first else ""
        return f"Previewed the request, without models: {n}{'; ' + detail if detail else ''}."
    if t["tool"] == "run_select":
        return f"Ran a read-only query: {args.get('sql', '')[:120]}"
    if t["tool"] == "ask_user":
        return f"Asked: \u201c{args.get('question', '')}\u201d Answer: \u201c{out}\u201d"
    if t["tool"] == "submit_spec":
        return "Submitted the request; the harness checked and accepted it."
    if t["tool"] == "submit_daily":   # on-the-fly path: its own SQL, the grain and the horizon
        import re   # the stored input is shortened (the SQL is long), so read grain and horizon from the text
        days = out.split("Accepted: ")[-1].split(" daily")[0] if "Accepted" in out else ""
        grain = re.search(r'"grain": "(\w+)"', t["input"])
        horizon = re.search(r'"horizon": (\d+)', t["input"])
        ahead = (f", {horizon.group(1)} {grain.group(1)}{'s' if horizon.group(1) != '1' else ''} ahead"
                 if grain and horizon else "")
        return (f"Submitted its SQL for the daily history ({int(days):,} days){ahead}; it was checked to be one "
                f"read-only SELECT and run." if days.isdigit() else f"Submitted its SQL{ahead}.")
    return f"{t['tool']}: {out[:120]}"


MEASURE_WORDS = {"sales_bottles": "bottles", "sales_dollars": "dollars", "sales_liters": "liters"}


def spec_table(spec, res):
    """The request the harness ran, in plain words: one row per field of the spec."""
    kept = set(res.get("feature_groups", []))
    tried = ", ".join(f"{FEATURE_NAMES.get(f, f)} ({'kept' if f in kept else 'dropped'})" for f in spec.features)
    codes = lambda x: ", ".join(x.codes) if x.codes else "all"
    rows = [("measure", MEASURE_WORDS.get(spec.target, spec.target), "what is forecast"),
            (f"{units()} ahead", str(spec.horizon), "how far ahead"),
            ("product", f"{spec.product.label} ({spec.product.kind} {codes(spec.product)})", "which products, by code"),
            ("place", f"{spec.region.label} ({spec.region.kind} {codes(spec.region)})", "where"),
            ("breakout", "combined into one forecast" if spec.series_by == "none" else f"one forecast per {spec.series_by}",
             "one total or several"),
            ("history from", spec.start[:7], "the earliest month used"),
            ("extra inputs tried", tried or "none", "kept or dropped in model selection")]
    return table(pd.DataFrame(rows, columns=["field", "value", "meaning"]), bold=("field",))


def sql_words(spec, panel):
    """What the aggregation SQL does, in one sentence."""
    from .panel import member_items, older_numbers   # the same item list the SQL was built from
    unit = MEASURE_WORDS.get(spec.target, spec.target)
    extra = ""
    if spec.product.kind in ("item", "name"):   # renumbered items: the SQL also reads the products' older numbers
        older = older_numbers(member_items(spec))
        if older:
            which = ", ".join(older) if len(older) <= 3 else f"{len(older)} older item numbers"
            extra = (f" (with {which}{', older item numbers of the same products' if len(older) <= 3 else ' of the same products'},"
                     " so their history is complete)")
    return (f"Adds up {unit} per month and store for {spec.product.label}{extra} in {spec.region.label}, "
            f"from {spec.start[:7]} on.")


SITE = "https://joehahn.github.io/demand-on-demand"
# the harness's SQL always reads these three tables; what each one decides in this forecast
TABLES_USED = [("sales.invoice_line", "summed by month: the series being forecast"),
               ("sales.item", "which order lines belong to the product"),
               ("sales.store", "which stores are in the place")]


def agent_knowledge(ai_sql=None):
    """How the agent knows the tables and columns: the dictionary it reads, and the tables this forecast used (the
    harness's three, or for AI-written SQL, the tables that query reads)."""
    from .agent import schema_rows   # imported here: the agent module imports the harness, which imports this one
    rows = schema_rows()
    notes = rows.groupby("tbl").table_note.first()
    if ai_sql:
        import sqlglot
        from sqlglot import exp
        read = sorted({f"{t.db}.{t.name}" for t in sqlglot.parse_one(ai_sql, read="postgres").find_all(exp.Table) if t.db})
        used = [(tbl, "read by the AI's query") for tbl in read]
    else:
        used = [(tbl, role.replace("summed by month", f"summed by {W['unit']}")) for tbl, role in TABLES_USED]
    t = pd.DataFrame([(tbl, role, notes.get(tbl, "")) for tbl, role in used],
                     columns=["table", "used for", "what the agent is told about it"])
    return (f"<p><strong>How it knows the tables and columns.</strong> At the start of every request the agent reads the "
            f"warehouse's <a href=\"{SITE}/data_dictionary.html\">data dictionary</a> from the database: "
            f"{rows.tbl.nunique()} tables and {len(rows)} columns, each described in a sentence. Its search tools then "
            f"find the actual names below. This forecast's data came from "
            f"{({1: 'one', 2: 'two', 3: 'three', 4: 'four'}).get(len(used), len(used))} of the tables:</p>"
            + table(t, bold=("table",), nowrap=("table",)))


GITHUB = "https://github.com/joehahn/demand-on-demand/blob/main"


def check_words(c):
    """The cross-check of the AI's data against the slot-filling reference, in one sentence."""
    if c["status"] == "passed":
        return (f"Cross-check passed: the AI's daily totals, summed by month, equal the series the tested slot-filling "
                f"path builds independently from the request form, in all {c['months']} months.")
    if c["status"] == "failed":
        return (f"Cross-check FAILED in {c['bad_months']} of {c['months']} months: the AI's data and the request form it "
                f"filled in describe different things, so check before trusting this forecast.")
    return f"Cross-check not available: {c['why']}."


def ai_prep_rows(ai, unit, panel, wide):
    """The on-the-fly path's own steps for this forecast."""
    shape = {"week": "weeks (Monday to Sunday)", "quarter": "calendar quarters"}.get(W["grain"], "calendar months")
    otf = f'<a href="{GITHUB}/dod/onthefly.py">dod/onthefly.py</a>'
    return [("This forecast", f"The AI wrote one SQL query returning daily {unit} totals for this request (see The SQL as "
             f"run); it was checked to be a single read-only SELECT before it ran.",
             f'the AI (Claude), checked by <a href="{GITHUB}/dod/sqlcheck.py">dod/sqlcheck.py</a>'),
            ("This forecast", f"Bucketed the days into {shape}, complete {units()} only. A {W['unit']} with no orders "
             f"counts as 0, since the warehouse was checked to have orders in every month from {when(panel.start)} to "
             f"{when(wide.index[-1])}; {units()} before the first sale are left blank.", otf + " (Python)"),
            ("This forecast", esc(check_words(ai["check"])), otf + " (SQL + Python)")]


def prep_section(spec, panel, res, unit, wide, ai=None):
    """How this forecast's data was prepared: what was done once in the warehouse (SQL run by load_data.py) and what
    the harness did for this request (SQL + Python), with the details that touched this forecast's own numbers."""
    from . import db
    from .panel import member_items
    fixes = dict(db.query("SELECT fix_id, rows_affected FROM meta.data_fixes").itertuples(index=False, name=None))
    n = lambda k: f"{int(fixes.get(k, 0)):,}"
    fixed = lambda anchor: f'<a href="{SITE}/data_fixes.html#{anchor}">details</a>'
    code = lambda f, what: f'<a href="{GITHUB}/{f}">{what}</a>'
    items = member_items(spec) if spec.product.kind in ("item", "category", "name") else []
    rows = []

    # once, in the warehouse
    w = code("load_data.py", "load_data.py")
    rows.append(("Warehouse, once", "Loaded every order line the state published since 2016 into Postgres: text turned into real dates "
                 "and numbers, each line given its own id, and each store, product and vendor kept once in its own table (order "
                 "lines refer to them by number), so a correction made there applies to every line.",
                 f"SQL run by {w} (raw, curate)"))
    rows.append(("Warehouse, once", f"Removed {n('export_duplicates')} rows the state's export repeats verbatim, and "
                 f"{n('zero_value_lines')} zero lines (likely cancelled). {fixed('duplicates')}", f"SQL in {w} (clean)"))
    if spec.product.kind in ("item", "name"):
        from .panel import older_numbers
        older = older_numbers(items)
        if older:
            which = ", ".join(older[:4]) + (f" and {len(older) - 4} more" if len(older) > 4 else "")
            verb = "is an older number" if len(older) == 1 else "are older numbers"
            rows.append(("Warehouse, once", f"Joined renumbered items: {which} {verb} of this product, so its history is "
                         f"continuous. {fixed('renumbering')}",
                         f"Python + SQL in {w} (clean)"))
    if spec.product.kind == "category" or spec.series_by == "category":
        rows.append(("Warehouse, once", "Restated every order in today's category taxonomy (codes were reassigned in 2016 "
                     f"and Cocktails/RTD recoded in 2022). {fixed('categories')}", f"SQL in {w} (clean)"))
    if unit in ("bottles", "liters") and items:
        u = db.query("SELECT u.item_no, i.item_desc, u.units_per_sale FROM sales.item_units u JOIN sales.item i "
                     "USING (item_no) WHERE u.item_no = ANY(%s)", (items,))
        known, unknown = u[u.units_per_sale.notna()], u[u.units_per_sale.isna()]
        known = known.drop_duplicates("item_desc")   # a renumbered item and its successor share a description
        if len(known):
            eg = "; ".join(f"{r.item_desc.title()}: {int(r.units_per_sale)} per unit" for r in known.head(3).itertuples())
            rows.append(("Warehouse, once", f"Counted real bottles where the state counts a sleeve or pack of minis as one: "
                         f"{eg}" + (f" and {len(known) - 3} more" if len(known) > 3 else "") + f". {fixed('units')}",
                         f"SQL in {w} (clean)"))
        if len(unknown):
            rows.append(("Warehouse, once", f"Left {len(unknown)} item(s) priced like packs of unknown size in selling "
                         f"units, flagged rather than guessed. {fixed('units')}", f"SQL in {w} (clean)"))
    if unit == "liters":
        rows.append(("Warehouse, once", f"Recomputed liters as bottles x volume ({n('liters_truncated')} lines from Nov "
                     f"2025 to Jan 2026 had been rounded down to whole liters). {fixed('liters')}", f"SQL in {w} (clean)"))
    variants = db.query("SELECT city_recorded, city FROM sales.city_crosswalk WHERE city = ANY(%s)",
                        (spec.region.codes or [],)) if spec.region.kind == "city" else pd.DataFrame()
    if len(variants) or spec.series_by == "city":   # only when this forecast's city was spelled more than one way
        eg = (f"{variants.city_recorded.iloc[0]} counted as {variants.city.iloc[0]}" if len(variants)
              else "e.g. MT PLEASANT and MOUNT PLEASANT")
        rows.append(("Warehouse, once", f"Gave each city one spelling ({eg}). {fixed('cities')}",
                     f"Python + SQL in {w} (clean)"))
    if "population" in res.get("feature_groups", []):
        rows.append(("Warehouse, once", "Carried the latest Census population forward to months Census has not published "
                     f"yet, flagged. {fixed('census')}", f"SQL in {w} (clean)"))

    if spec.region.kind in ("city", "county") or spec.series_by in ("city", "county"):
        rows.append(("Warehouse, once", "Counted each store in its current city and county for its whole history (a few "
                     "stores moved or were re-recorded over the years).", f"SQL in {w} (curate)"))

    # for this forecast, in the harness
    panel_py = code("dod/panel.py", "dod/panel.py")
    if ai:   # on-the-fly: the AI wrote the SQL; fixed code bucketed its daily totals and checked them
        rows += ai_prep_rows(ai, unit, panel, wide)
    else:
        rows.append(("This forecast", f"Summed {unit} per month for this product and place, complete months only (see The "
                     f"SQL as run). A month with no orders counts as 0, since the warehouse was checked to have orders in every "
                     f"month from {pd.Timestamp(panel.start):%b %Y} to {wide.index[-1]:%b %Y}, so it is a real zero, not missing "
                     f"data. Months before the first sale are left blank.", panel_py + " (SQL + Python)"))
    if any(c.get("pool") for c in res.get("ensemble") or []) and panel.pool is not None:
        rows.append(("This forecast", f"Also summed the same product per month in the {panel.pool[0].shape[1]} busiest "
                     "counties, for the pooled model to learn from (it still forecasts only this place).",
                     panel_py + " (SQL + Python)"))
    if "calendar" in res.get("feature_groups", []):
        rows.append(("This forecast", "Built calendar inputs for every month, including the months ahead: month of year, "
                     "business days and federal holidays, from the warehouse's calendar table.", panel_py + " (Python)"))
    targets = {c["target"] for c in res.get("ensemble") or []}
    scaled = "each series and input scaled to mean 0, spread 1 before fitting, and predictions scaled back"
    if targets == {"yoy"}:
        scaled = "the change from last year used as is (it has no units); inputs scaled to mean 0, spread 1"
    elif "yoy" in targets:
        scaled += " (a model predicting the change from last year uses that change as is: it has no units)"
    rows.append(("This forecast", f"Standardized for the models: {scaled}.", code("dod/model.py", "dod/model.py") + " (Python)"))
    t = pd.DataFrame(rows, columns=["where", "what was done", "done by"])
    head = "".join(f"<th>{c}</th>" for c in t.columns)
    body = "".join(f"<tr><td style=\"white-space:nowrap\"><strong>{esc(a)}</strong></td><td>{b}</td><td>{c}</td></tr>"
                   for a, b, c in t.itertuples(index=False))
    return (f"<p>{W['adj'].capitalize()} {unit} from {when(panel.start)} through {when(wide.index[-1])}. How the data was "
            f"prepared: fixed once in the warehouse, before any forecast, then shaped for this request by the harness. "
            + (f"On this prototype path the AI wrote the query for the daily history (the first \u201cThis forecast\u201d "
               f"step); every other step is fixed code that runs the same way for every request. " if ai else
               f"The AI agent takes no part in these steps: they are fixed code that runs the same way for every request. ")
            + f"The code itself was written in advance with Claude Code, with a person reviewing and approving every data fix.</p><div class=\"tbl\"><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


REPO = "https://github.com/joehahn/demand-on-demand"


def updated_html(panel):
    """When this page was built, and how far its data goes."""
    import datetime
    d = datetime.datetime.now().astimezone()
    end = pd.Timestamp(panel.data_end)
    return (f'<p class="note">Updated {d:%b} {d.day}, {d.year} at {d.hour % 12 or 12}:{d:%M %p %Z} &middot; '
            f"orders through {end:%b} {end.day}, {end.year}</p>")


def nav_html():
    return (f'<p class="note"><a href="{SITE}/">demand-on-demand</a> &middot; <a href="{SITE}/#how">how it works</a> '
            f'&middot; <a href="{SITE}/#examples">examples</a> &middot; <a href="{SITE}/data_dictionary.html">data '
            f'dictionary</a> &middot; <a href="{REPO}">GitHub</a></p>')


def model_label(usage):
    """'claude-sonnet-5' -> 'Claude Sonnet 5' for readers; the exact id stays in Exactly what ran."""
    m = (usage or {}).get("model") or "Claude"
    return " ".join(w.capitalize() for w in m.replace("-", " ").split())


def toolbox_html(usage):
    """What the agent does, in two sentences, with links to its instructions and tools."""
    from .tools import TOOLS
    return (f"<p><strong>The agent's toolbox.</strong> The AI agent ({esc(model_label(usage))}) does slot filling: it fills "
            f"in a short request form (product, place, measure, months) using {len(TOOLS)} read-only lookup tools, and "
            f"fixed code turns that form into SQL. Unlike text-to-SQL, it never writes the query that feeds the forecast "
            f"(<a href=\"{REPO}/blob/main/dod/agent.py\">instructions</a>, "
            f"<a href=\"{REPO}/blob/main/dod/tools.py\">tools</a>).</p>")


def exact_html(spec, res, panel, ai=None):
    """Exactly what ran: the request form and the harness's SQL, or for the on-the-fly path the AI's SQL and the form
    it filled in for the cross-check."""
    if not ai:
        return (f"<p>The exact request the harness ran. It is the agent's only input to the result: everything after it "
                f"(the SQL, the models, the scoring and this page) is fixed code.</p>{spec_table(spec, res)}"
                f"<details><summary>The request as run</summary><p>Save it as spec.json and run "
                f"<code>python -m dod.run spec.json</code> to reproduce this forecast.</p>"
                f"<pre>{esc(spec.model_dump_json(indent=2))}</pre></details>"
                f"<details><summary>The SQL as run</summary><p>{esc(sql_words(spec, panel))} Generated by the harness from "
                f"the request, never written by the AI, and run under a read-only database login.</p>"
                f"<pre>{esc(panel.sql)}</pre></details>")
    return (f"<p>What ran: the AI's SQL for the daily history, then fixed code for everything after it. The table is the "
            f"request form the AI also filled in; fixed code used it to rebuild the history independently for the "
            f"cross-check. {esc(check_words(ai['check']))}</p>{spec_table(spec, res)}"
            f"<details><summary>The SQL as run</summary><p>Written by the AI, checked to be one read-only SELECT, and run "
            f"under a read-only database login. It returns daily totals; fixed code bucketed them into {units()}.</p>"
            f"<pre>{esc(ai['sql'])}</pre></details>"
            f"<details><summary>The request form as filled in</summary><pre>{esc(spec.model_dump_json(indent=2))}</pre>"
            f"</details>")


def big_buyer_note(stores, unit, n_series):
    """One store with a large share of recent volume, ordering on and off, makes the monthly total hard to predict:
    say so next to the forecast range. Single-series forecasts only (a breakout would need a share per series)."""
    if stores is None or stores.empty or n_series != 1 or stores.last_12_months.sum() <= 0:
        return ""
    top = stores.sort_values("last_12_months", ascending=False).iloc[0]
    share = top.last_12_months / stores.last_12_months.sum()
    if share <= BIG_BUYER_SHARE:
        return ""
    money = "$" if unit == "dollars" else ""
    per = top.last_12_months / max(top.months_ordering, 1)
    per = round(per, -max(int(np.floor(np.log10(per))) - 1, 0)) if per >= 1 else per  # "about": two significant figures
    return (f"<li><strong>One big buyer:</strong> {esc(top.store_name)} placed {share:.0%} of the last 12 months' "
            f"{unit}, ordering in {int(top.months_ordering)} of those months (about {money}{per:,.0f} each time). Months it "
            f"orders or skips swing the total, which is part of why the range is wide.</li>")


def fig_store_map(stores, unit):
    """Where the stores are: dot size is each store's last-12-months volume; grey dots have not ordered lately."""
    s = stores.dropna(subset=["lat", "lon"])
    if s.empty:
        return None
    money = "$" if unit == "dollars" else ""
    active, idle = s[s.last_12_months > 0], s[s.last_12_months <= 0]
    size = lambda v: 6 + 24 * np.sqrt(v / s.last_12_months.max()) if s.last_12_months.max() > 0 else 8
    fig = go.Figure([
        go.Scattermap(lat=idle.lat, lon=idle.lon, mode="markers", name="no orders in the last 12 months",
                      marker=dict(size=6, color="rgba(137,135,129,0.7)"), text=idle.store_name,
                      hovertemplate="%{text}<extra>no recent orders</extra>"),
        go.Scattermap(lat=active.lat, lon=active.lon, mode="markers", name=f"{unit}, last 12 months (dot size)",
                      marker=dict(size=size(active.last_12_months), color=BLUE, opacity=0.9), text=active.store_name,
                      customdata=active.last_12_months,
                      hovertemplate="%{text}<br>" + money + "%{customdata:,.0f} " + unit + ", last 12 months<extra></extra>"),
    ])
    # frame the stores: zoom from the wider of the latitude and longitude spans, ignoring the odd far-off store
    # (one licensee is in Colorado) so a statewide map still frames Iowa
    lat, lon = s.lat.quantile([0.01, 0.99]), s.lon.quantile([0.01, 0.99])
    # web-map zoom z shows 512 * 2^z / 360 pixels per degree of longitude (latitude ~1.3x more in Iowa); fit the
    # stores into about 700 x 300 pixels of the map
    lon_span = max(lon.iloc[1] - lon.iloc[0], 0.01)
    lat_span = max(lat.iloc[1] - lat.iloc[0], 0.01) * 1.33
    zoom = float(np.clip(min(np.log2(700 * 360 / (512 * lon_span)), np.log2(300 * 360 / (512 * lat_span))), 3, 13))
    # CARTO's Voyager basemap (colored roads, water, parks): no key, works from any page (OpenStreetMap's own
    # servers block pages opened as files)
    fig.update_layout(map=dict(style="carto-voyager", zoom=zoom,
                               center=dict(lat=float(s.lat.median()), lon=float(s.lon.median()))),
                      margin=dict(l=0, r=0, t=40, b=0), height=380, showlegend=True,
                      legend=dict(orientation="h", y=1.0, x=1, xanchor="right", yanchor="bottom"),
                      title=dict(text="Stores included", x=0, xanchor="left", font=dict(size=15)),
                      paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=12))  # as in viz.style
    return fig


def stores_section(stores, spec, unit, last_month, plot):
    """Which stores were added up: every store whose orders of this product in this region are in the series."""
    if stores is None or stores.empty:
        return ""
    recent = stores[stores.last_12_months > 0]
    t = stores.drop(columns=["lat", "lon", "months_ordering"], errors="ignore")
    t = t.rename(columns={"last_12_months": f"{unit}, last 12 months"})
    fig = fig_store_map(stores, unit) if {"lat", "lon"} <= set(stores.columns) else None
    money = "$" if unit == "dollars" else ""
    return (f"<h3>Stores included</h3><p>The forecast adds up the orders of {len(stores):,} stores in "
            f"{esc(spec.region.label)} that bought {esc(spec.product.label)} since {spec.start[:7]}; "
            f"{len(recent):,} of them ordered it in the 12 months to {last_month:%b %Y}. Stores that closed still "
            f"count in the months they were open.</p>"
            + (plot(fig) if fig is not None else "") +
            f"<details><summary>Show the stores</summary>"
            f"{table(t, {f'{unit}, last 12 months': lambda v: f'{money}{v:,.0f}'})}</details>")


def short_model(res, joiner=", "):
    """The chosen mix in a few words, e.g. '50% same month last year + 33% ridge regression + 17% LightGBM'."""
    parts = pd.DataFrame(forecast_parts(res), columns=["part", "weight", "settings", "err"])
    mix = parts.groupby("part", sort=False).weight.sum()
    if list(mix.index) == [base()]:
        return f"the {base()} (no model beat it)"
    if len(mix) == 1:  # one algorithm, no blend with last year: "a ridge regression", "the average of 3 ridge regressions"
        n, name = len(parts), mix.index[0]
        return f"a {name}" if n == 1 else f"the average of {n} {name}{'s' if name != 'LightGBM' else ' models'}"
    return joiner.join(f"{v:.0%} {k}" for k, v in mix.items() if v > 0)


def read_as_html(spec, unit, months, wide, assumptions_html):
    """How the request was read, as one line of short phrases, with the agent's assumptions one click away."""
    n = wide.shape[1]
    series = "combined into one forecast" if spec.series_by == "none" else f"one forecast per {spec.series_by} ({n})"
    parts = [spec.product.label, spec.region.label, f"{unit} per {W['unit']}", months.replace(" ", "\u00a0"), series]
    why = (f'<details class="note"><summary>Why it was read this way</summary><ul>{assumptions_html}</ul></details>'
           if assumptions_html else "")
    return f'<p class="readas"><span>Read as</span> {" &middot; ".join(esc(x) for x in parts)}</p>{why}'


def fig_series(code, label, wide, bt, fc, windows, unit, train_start):
    """Actuals, what the model would have said 1 to N months ahead during the test (one at a time, picked with
    buttons), and the forecast."""
    hist = wide[code].dropna().iloc[-W["history"]:]
    mine = bt[bt.series == code]
    steps = sorted(mine.step.unique())
    one = mine[mine.step == 1]
    f = fc[fc.series == code].sort_values("month")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(f.month) + list(f.month[::-1]), y=list(f.hi) + list(f.lo[::-1]),
                             fill="toself", fillcolor="rgba(27,175,122,0.18)", line=dict(width=0), mode="lines",
                             hoverinfo="skip", name="80% range"))
    fig.add_trace(line(hist.index, hist.values, "Actual", BLUE))
    for k in steps:  # one dotted line per horizon; only 1 month ahead shows until another is picked
        b = mine[mine.step == k].sort_values("month")
        fig.add_trace(line(b.month, b.pred, f"Backtest, {k} {units(k)} ahead", ORANGE, dash="dot"))
        fig.data[-1].visible = bool(k == 1)
    fig.add_trace(line(f.month, f.pred, "Forecast", AQUA))
    if len(steps) > 1:
        shown = lambda k: [True, True] + [j == k for j in steps] + [True]
        fig.update_layout(updatemenus=[dict(
            type="buttons", direction="right", showactive=True, active=0, x=1, xanchor="right", y=1.02, yanchor="bottom",
            pad=dict(r=0, t=0), font=dict(size=11), bgcolor="rgba(0,0,0,0)",
            buttons=[dict(label=f"{k}", method="restyle", args=[{"visible": shown(k)}]) for k in steps])])
        fig.add_annotation(text=f"backtest, {units()} ahead:", x=1, xref="paper", xanchor="right", xshift=-34 * len(steps),
                           y=1.02, yref="paper", yanchor="bottom", yshift=4, showarrow=False,
                           font=dict(size=11, color="rgba(137,135,129,1)"))
    fig.update_traces(selector=dict(name="Forecast"), mode="lines+markers", marker=dict(size=8))
    if len(one) == 0:
        fig.update_layout(title_text=f"{label} (not backtested)")
    # the three periods: model chosen (selection), model tested (rolling backtest), model applied (forecast)
    (tune_start, _), (test_start, _) = windows
    first_fc, end = f.month.min(), back(f.month.max(), -1)
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
                       text=f"final model trained on {when(train_start)} to {when(wide.index[-1])}")
    fig.update_traces(hovertemplate="%{y:,.0f}", selector=dict(type="scatter"))
    fig = style(fig, label, f"{unit} per {W['unit']}", height=390, legend=True)
    return fig.update_layout(legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, xanchor="left"))  # clear of long titles


def fig_accuracy(per_step):
    """Typical miss by months ahead, model vs same month last year. Dots and lines, not bars, so the axis can zoom
    to the data's range without exaggerating the gap."""
    fig = go.Figure([line(per_step.step, per_step.wape * 100, "Model", BLUE),
                     line(per_step.step, per_step.wape_naive * 100, base().capitalize(), ORANGE)])
    fig.update_traces(mode="lines+markers", marker=dict(size=9), hovertemplate="%{y:.1f}%<extra>%{fullData.name}</extra>")
    lo = min(per_step.wape.min(), per_step.wape_naive.min()) * 100
    hi = max(per_step.wape.max(), per_step.wape_naive.max()) * 100
    pad = max((hi - lo) * 0.4, 2)
    fig.update_yaxes(range=[max(0, lo - pad), hi + pad], ticksuffix="%")
    fig.update_xaxes(title=f"{units()} ahead", dtick=1)
    return style(fig, f"Typical miss in the Test period, by {units()} ahead (lower is better)", "typical miss (% of actual)",
                 height=300, legend=True).update_layout(hovermode="x unified")


def build(spec, panel, res, usage=None, agent=None, harness_seconds=None, ai=None):
    """The dashboard. ai is set for the on-the-fly path (dod/onthefly.py): the AI's SQL, form fill and cross-check."""
    set_grain(spec.grain)
    plot = Plots(numbered=True, toolbar=False)
    wide, fc, bt, ps = panel.series, res["forecast"], res["backtest"], res["per_step"]
    labels = panel.labels
    months = f"{when(fc.month.min())} to {when(fc.month.max())}"
    unit = {"sales_bottles": "bottles", "sales_dollars": "dollars", "sales_liters": "liters"}[spec.target]
    total = fc.pred.sum()
    last_year = sum(wide.at[back(m, W["season"]), c] for m, c in zip(fc.month, fc.series)
                    if back(m, W["season"]) in wide.index)
    yoy = total / last_year - 1 if last_year else float("nan")
    rel = res["test_rel_mae"]
    money = "$" if unit == "dollars" else ""
    tiles = [
        (f"{money}{total:,.0f}", f"forecast {unit}, {months}"),
        (f"{yoy:+.1%}", f"vs the same {units()} last year"),
        (f"{bt.dropna(subset=['actual']).pipe(lambda d: (d.actual - d.pred).abs().sum() / d.actual.sum()):.0%}",
         f"typical {W['adj']} miss in the Test period ({when(res['test_window'][0])} to {when(res['test_window'][1])})"),
        (f"{round(abs(1 - rel) * 100)}%", (("more" if rel < 1 else "less") + f" accurate than repeating the {base()}")
         if round(abs(1 - rel) * 100) else f"as accurate as repeating the {base()}"),
    ]
    # what this page took to make from the plain-English request: agent time, harness time, Claude API cost
    if harness_seconds is not None:
        u = usage or {}
        agent_s = u.get("agent_seconds", 0)
        parts = ([f"agent {agent_s:.0f} s"] if agent_s else []) + [f"models {harness_seconds:.0f} s"]
        cost = f" \u00b7 ${u['est_cost_usd']:.2f}" if u.get("est_cost_usd") else ""
        tiles.append((f"{agent_s + harness_seconds:.0f} s{cost}",
                      f"to build from scratch ({', '.join(parts)}" + ("; Claude API cost" if cost else "") + ")"))
    tiles_html = "".join(f'<div class="tile"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>'
                         for v, k in tiles)

    # forecast table: one row per series and period
    ft = fc.assign(series=fc.series.map(lambda c: labels.get(c, c)), month=fc.month.map(stamp))
    ft = ft[["series", "month", "pred", "lo", "hi"]].rename(columns={"month": W["unit"], "pred": "forecast",
                                                                      "lo": "low (10%)", "hi": "high (90%)"})
    num = lambda v: f"{v:,.0f}"

    charts = "".join(plot(fig_series(c, labels.get(c, c), wide, bt, fc, (res["tune_window"], res["test_window"]), unit,
                                    panel.start))
                     for c in [c for c in wide.columns if c in set(fc.series)][:MAX_PANELS])
    more = f'<p class="note">{len(wide.columns) - MAX_PANELS} more series are in the table only.</p>' \
        if len(wide.columns) > MAX_PANELS else ""

    skipped_html = "".join(f'<p class="warn">Not forecast: {esc(labels.get(c, c))}, {esc(why)}.</p>'
                           for c, why in res.get("skipped", {}).items())
    skipped_html += "".join(f'<p class="warn">Unvalidated: {esc(labels.get(c, c))} was too new to backtest during the '
                            f'test window, so its forecast comes from the pooled model with no track record of its own. '
                            f'Treat it as indicative.</p>' for c in res.get("unvalidated", []))

    grid = grid_words(res["grid"].head(10))
    space_html, space_count = search_space(res, 0 if panel.pool is None else panel.pool[0].shape[1])
    # an after-the-fact check: how each feature choice would have scored in the Test period (never used to choose)
    names = {"seasonal naive baseline": f"{base()} (baseline)"}
    abl = pd.DataFrame({"inputs besides past sales": [names.get(f, f.replace("chosen: none", "chosen: none (past sales only)"))
                                                      for f in res["ablation"].features],
                        "error vs last year, Test period\n(smaller is better)": res["ablation"].rel_mae.map("{:.3f}".format)})
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
        others = f" and {len(panel.unknown_packs) - 3} more" if len(panel.unknown_packs) > 3 else ""
        counts = "only one bottle's volume" if unit == "liters" else "as one bottle"
        units_note = (f" {len(panel.unknown_packs)} item(s) in this product ({esc(names)}{others}) are sold in sleeves or "
                      f"packs of unknown size, so each pack counts {counts}.")
    pooling_tried = "True" in set(res["grid"].get("pool", pd.Series(dtype=str)).astype(str))
    stride = model.GRAINS[W["grain"]]["stride"]
    refit = f"every {W['unit']}" if stride == 1 else f"every {stride} {units()}"
    ask_html, trace_html = "", ""
    if agent:
        assumptions = "".join(f"<li>{esc(a)}</li>" for a in agent.get("assumptions", []))
        ask_html = (f'<p class="asked">&ldquo;{esc(agent["request"])}&rdquo;</p>' + read_as_html(spec, unit, months, wide, assumptions)
                    + (f'<p class="headline">{esc(agent["summary"])}</p>' if agent.get("summary") else ""))
        tr = pd.DataFrame(agent.get("trace", []))
        if not tr.empty:
            steps = "".join(f"<li>{esc(agent_step(t))}</li>" for t in agent.get("trace", []))
            intro = ("How the AI agent (Claude) turned the request into what \u201cRead as\u201d shows at the top: the "
                     "exact products, place, measure and months. Its tools only look things up; it never writes the SQL "
                     f"or the models, and the harness checks the request before running it.</p>{toolbox_html(usage)}")
            if ai:
                intro = ("How the AI agent (Claude) turned the request into what \u201cRead as\u201d shows at the top. On "
                         "this prototype path it writes the SQL for the daily history itself (text-to-SQL, with "
                         f'<a href="{SITE}/differential.html">three rules for this warehouse</a>), and names the time '
                         "grain. Fixed code checks the SQL is one read-only SELECT, buckets the days, picks and tests "
                         "the model, and cross-checks the AI's data against the tested path.</p>")
            trace_html = (f"<h2>What the agent did</h2><p>{intro}{agent_knowledge(ai['sql'] if ai else None)}"
                          "<p><strong>What it did, step by step:</strong></p>"
                          f"<ol>{steps}</ol><details><summary>The raw tool calls</summary>"
                          + table(tr[["turn", "tool", "input", "result"]], nowrap=("turn", "tool"), mono=("result",), wide=("input",)) + "</details>")

    body = f"""
{nav_html()}
<h1>{esc(spec.title)}</h1>
{updated_html(panel)}
{ask_html or read_as_html(spec, unit, months, wide, "")}
<div class="tiles">{tiles_html}</div>
{skipped_html}
{charts}{more}
<ul class="note">
<li><strong>Model selection</strong> ({when(uw[0])} to {when(uw[1])}): {len(res["grid"]) - 1} distinct configurations of ridge
regression and LightGBM compared, differing in targets, inputs and history lengths{", with or without other counties" if pooling_tried else ""}.</li>
<li><strong>Selected model:</strong> {esc(short_model(res, " + "))}</li>
<li><strong>Test</strong> ({when(tw[0])} to {when(tw[1])}): a replay of real use. {refit.capitalize()} the model was retrained on
all {units()} before that point and forecast the next {max(ps.step)}, {bt.origin.nunique()} times in all, each scored
against what actually sold. Dotted orange is those forecasts, 1 to {max(ps.step)} {units()} ahead (pick above the
chart).</li>
<li><strong>Forecast</strong> ({months}): retrained on {when(panel.start)} to {when(wide.index[-1])}, then applied.{units_note}</li>
<li><strong>Green band (80% range):</strong> inferred by comparing the model's forecasts with actual sales in the Test
period; it spans the middle 80% of those misses.</li>
{big_buyer_note(panel.stores, unit, wide.shape[1])}
</ul>
{table(ft, {"forecast": num, "low (10%)": num, "high (90%)": num})}

<h2>How far to trust it</h2>
<p>Every {W['unit']} in the Test period was forecast by a model trained only on earlier {units()}, then compared with what
actually happened and with the simplest serious baseline: the {base()}.</p>
{plot(fig_accuracy(ps))}

<h2>How the data was prepared</h2>
{prep_section(spec, panel, res, unit, wide, ai)}
{features_section(spec, panel, res, unit, fc)}
{stores_section(panel.stores, spec, unit, wide.index[-1], plot)}

<h2>How the model was chosen</h2>
{model_explanation(res, unit, spec, panel)}
<p>What was compared: every combination of these settings ({space_count} configurations):</p>
{space_html}
<details><summary>The 10 best configurations</summary>
<p>With the baseline (a model had to beat it in model selection to be used). Feature groups were then kept or dropped
on the same {units()}; the test window was not used for any choice.</p>
{table(grid)}</details>
{blend_details(res)}
<details><summary>Feature choice, checked afterward</summary><p>Whether to add calendar or population inputs was
decided in model selection. For the record, here is how each choice would have scored in the Test period, which no
choice ever saw; the Test period can disagree with the selection.</p>
{table(abl)}</details>

{trace_html}
<h2>Exactly what ran</h2>
{cost}
{exact_html(spec, res, panel, ai)}

<footer>
Data: <a href="https://catalog.data.gov/dataset?q=iowa+liquor+sales">Iowa Liquor Sales</a>, State of Iowa, via the Iowa
Data Hub, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; modified (duplicates removed, aggregated).
Census population: U.S. Census Bureau. Not endorsed by the State of Iowa. Orders through {panel.data_end:%Y-%m-%d}.<br>
<a href="https://github.com/joehahn/demand-on-demand">demand-on-demand</a> by Joseph M. Hahn, Ph.D.,
<a href="https://jmh-datasciences.com">JMH DataSciences</a>.
</footer>"""
    return page(spec.title, body)
