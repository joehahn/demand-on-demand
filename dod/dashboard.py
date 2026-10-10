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
    """The last step of the forecast's choice, collapsed: every way of combining the top configurations with last year,
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
    n = max(model.TOP_K)
    return (f"<details><summary>How the mix with last year was chosen</summary><p>Each {W['unit']}'s forecast can blend "
            f"the models' forecast with simply repeating the {base()}. {len(t)} blends were tried (the best model or the "
            f"average of the best {n}; 0% to 100% weight on the models) and scored on the Testing period, as their misses "
            f"divided by last year's: 1.000 = as good as last year, smaller is better. The best blend, marked below, is "
            f"used.</p>" + table(t) + "</details>")


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
    tested = f"Tuning on the Tuning period ({when(uw[0])} to {when(uw[1])}) chose " \
             f"{short_model(res['tested'])}, which was then {test} in the Testing period ({when(tw[0])} to {when(tw[1])}), " \
             f"{units()} it never saw: that is where this page's accuracy figures come from."
    if [p[0] for p in parts] == [base()]:
        return (f"<p><strong>How this forecast is made.</strong> No model beat simply repeating the {base()} "
                f"after re-tuning on the Testing period ({when(tw[0])} to {when(tw[1])}), so that is the forecast. {tested}</p>")
    b = res["blend"]
    best_alone = b[(b.models_averaged == 1) & (b.model_share == 1.0)].tuning_rel_mae.iloc[0]
    chosen = b[(b.models_averaged == len(res["ensemble"])) & (b.model_share == res["model_share"])].tuning_rel_mae.iloc[0]
    lead = (f"Each {W['unit']}'s forecast is this weighted mix." if len(parts) > 1
            else f"Each {W['unit']}'s forecast comes from this model.")
    return (f"<p><strong>How this forecast is made.</strong> {lead} It was picked by re-tuning on the Testing "
            f"period ({when(tw[0])} to {when(tw[1])}), with models trained on earlier {units()} only: its total misses there "
            f"were {chosen:.2f} times those of last year alone, against {best_alone:.2f} for the best single model "
            f"(smaller is better; 1.00 = as good as last year). {tested}</p>{tbl}")


FEATURE_NAMES = {"season": "time of year (season)", "calendar": "business days and holidays",
                 "population": "county population", "stores": "active stores"}
FEATURE_COLUMNS = model.FEATURE_GROUPS


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
    plain = lambda v: f"{v:,.0f}" if abs(v) >= 10 or float(v).is_integer() else f"{v:.2f}"   # season is -1 to 1
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
    if "season" in chosen and any(c["model"] == "lightgbm" and c.get("month_number") for c in ens):
        notes.append("LightGBM sees the month number (1 to 12) in place of the sine and cosine.")
    dropped = [g for g in spec.features if g not in chosen]
    if dropped:
        notes.append("Tried and left out, because the model did better without them when re-tuned on the Testing period: "
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
    if t["tool"] == "run_select":
        return f"Ran a read-only query: {args.get('sql', '')[:120]}"
    if t["tool"] == "ask_user":
        return f"Asked: \u201c{args.get('question', '')}\u201d Answer: \u201c{out}\u201d"
    if t["tool"] == "submit_query":   # its SQL for the sales records, the grain and the horizon
        import re   # the stored input is shortened (the SQL is long), so read grain and horizon from the text
        grain = re.search(r'"grain": "(\w+)"', t["input"])
        horizon = re.search(r'"horizon": (\d+)', t["input"])
        ahead = (f", {horizon.group(1)} {grain.group(1)}{'s' if horizon.group(1) != '1' else ''} ahead"
                 if grain and horizon else "")
        return (f"Submitted its SQL selecting the sales records{ahead}; fixed code checked it is one read-only SELECT with the "
                f"right columns.")
    return f"{t['tool']}: {out[:120]}"


MEASURE_WORDS = {"sales_bottles": "bottles", "sales_dollars": "dollars", "sales_liters": "liters"}


def spec_table(spec, res):
    """How the agent read the request, in plain words: one row per field."""
    kept = set(res.get("feature_groups", []))
    tried = ", ".join(f"{FEATURE_NAMES.get(f, f)} ({'kept' if f in kept else 'dropped'})" for f in spec.features)
    rows = [("measure", MEASURE_WORDS.get(spec.target, spec.target), "what is forecast"),
            (f"{units()} ahead", str(spec.horizon), "how far ahead"),
            ("product", spec.product, "which products (the SQL decides exactly which)"),
            ("place", spec.place, "where (the SQL decides exactly which stores)"),
            ("breakout", "combined into one forecast" if spec.series_by == "none" else f"one forecast per {spec.series_by}",
             "one total or several"),
            ("history from", spec.start[:7], "the earliest month used"),
            ("extra inputs tried", tried or "none", "kept or dropped when re-tuning on the Testing period")]
    return table(pd.DataFrame(rows, columns=["field", "value", "meaning"]), bold=("field",))


SITE = "https://joehahn.github.io/demand-on-demand"
def agent_knowledge(sql):
    """How the agent knows the tables and columns: the dictionary it reads, and the tables its query read."""
    from .agent import schema_rows   # imported here: the agent module imports the harness, which imports this one
    rows = schema_rows()
    notes = rows.groupby("tbl").table_note.first()
    import sqlglot
    from sqlglot import exp
    read = sorted({f"{t.db}.{t.name}" for t in sqlglot.parse_one(sql, read="postgres").find_all(exp.Table) if t.db})
    used = [(tbl, "read by the AI's query") for tbl in read]
    t = pd.DataFrame([(tbl, role, notes.get(tbl, "")) for tbl, role in used],
                     columns=["table", "used for", "what the agent is told about it"])
    return (f"<p><strong>How it knows the tables and columns.</strong> At the start of every request the agent reads the "
            f"warehouse's <a href=\"{SITE}/data_dictionary.html\">data dictionary</a> from the database: "
            f"{rows.tbl.nunique()} tables and {len(rows)} columns. Its search tools then "
            f"find the actual names below. This forecast's data came from "
            f"{({1: 'one', 2: 'two', 3: 'three', 4: 'four'}).get(len(used), len(used))} of the tables:</p>"
            + table(t, bold=("table",), nowrap=("table",)))


GITHUB = "https://github.com/joehahn/demand-on-demand/blob/main"


def query_prep_rows(unit, panel, wide):
    """This forecast's own steps: the AI's query, then fixed code's sums."""
    shape = {"week": "Monday to Sunday", "quarter": "calendar quarters"}.get(W["grain"], "calendar months")
    hist = f'<a href="{GITHUB}/dod/history.py">dod/history.py</a>'
    return [("This forecast", f"The AI wrote one SQL query that selects the sales records for this request: which "
             f"products, which stores, and the {unit} on each record (see The SQL as run).",
             f'the AI (Claude), checked by <a href="{GITHUB}/dod/sqlcheck.py">dod/sqlcheck.py</a>'),
            ("This forecast", f"Computed {W['adj']} sums of the selected records ({shape}), complete {units()} only, "
             f"and monthly sums for each store (for the store list and map). A {W['unit']} with no "
             f"orders counts as 0, since the warehouse was checked to have orders in every month from "
             f"{when(panel.start)} to {when(wide.index[-1])}; {units()} before the first sale are left blank.",
             hist + " (SQL + Python)")]


def prep_section(spec, panel, res, unit, wide):
    """How this forecast's data was prepared: what was done once in the warehouse (SQL run by load_data.py) and what
    fixed code did for this request (SQL + Python), with the details that touched this forecast's own numbers."""
    from . import db
    fixes = dict(db.query("SELECT fix_id, rows_affected FROM meta.data_fixes").itertuples(index=False, name=None))
    n = lambda k: f"{int(fixes.get(k, 0)):,}"
    fixed = lambda anchor: f'<a href="{SITE}/data_fixes.html#{anchor}">details</a>'
    code = lambda f, what: f'<a href="{GITHUB}/{f}">{what}</a>'
    items, sql = panel.items, panel.sql.lower()
    rows = []

    # once, in the warehouse
    w = code("load_data.py", "load_data.py")
    rows.append(("Warehouse, once", "Loaded every sales record the state published since 2016 into Postgres: text turned into real dates "
                 "and numbers, each record given its own id, and each store, product and vendor kept once in its own table (sales "
                 "records refer to them by number), so a correction made there applies to every record.",
                 f"SQL run by {w} (raw, curate)"))
    rows.append(("Warehouse, once", f"Removed {n('export_duplicates')} rows the state's export repeats verbatim, and "
                 f"{n('zero_value_lines')} zero records (likely cancelled). {fixed('duplicates')}", f"SQL in {w} (clean)"))
    older = panel.older
    if older:   # renumbered products in this forecast: their older numbers carry the early history
        rows.append(("Warehouse, once", f"Linked each product's old product IDs to its current one, so sales recorded under "
                     f"an old ID count toward the same product. {fixed('renumbering')}", f"Python + SQL in {w} (clean)"))
    if "category" in sql or spec.series_by == "category":
        rows.append(("Warehouse, once", f"Some product categories changed over time, so each product is counted in its "
                     f"current category for all of its history. {fixed('categories')}", f"SQL in {w} (clean)"))
    if unit in ("bottles", "liters") and items and len(items) <= 5000:
        u = db.query("SELECT u.item_no, i.item_desc, u.units_per_sale FROM sales.item_units u JOIN sales.item i "
                     "USING (item_no) WHERE u.item_no = ANY(%s)", (items,))
        known, unknown = u[u.units_per_sale.notna()], u[u.units_per_sale.isna()]
        if len(known):
            rows.append(("Warehouse, once", f"Counted real bottles where the state counts a sleeve or pack of minis as one. "
                         f"{fixed('units')}", f"SQL in {w} (clean)"))
        if len(unknown):
            rows.append(("Warehouse, once", f"Left {len(unknown)} item(s) priced like packs of unknown size in selling "
                         f"units, flagged rather than guessed. {fixed('units')}", f"SQL in {w} (clean)"))
    if unit == "liters":
        rows.append(("Warehouse, once", f"Recomputed liters as bottles x volume ({n('liters_truncated')} lines from Nov "
                     f"2025 to Jan 2026 had been rounded down to whole liters). {fixed('liters')}", f"SQL in {w} (clean)"))
    cities = list(panel.stores.city.dropna().unique()) if "city" in sql and panel.stores is not None else []
    variants = db.query("SELECT city_recorded, city FROM sales.city_crosswalk WHERE city = ANY(%s)",
                        (cities,)) if cities else pd.DataFrame()
    if len(variants):   # only when a city in this forecast was spelled more than one way
        eg = (f"{variants.city_recorded.iloc[0]} counted as {variants.city.iloc[0]}" if len(variants)
              else "e.g. MT PLEASANT and MOUNT PLEASANT")
        rows.append(("Warehouse, once", f"Gave each city one spelling ({eg}). {fixed('cities')}",
                     f"Python + SQL in {w} (clean)"))
    if "population" in res.get("feature_groups", []):
        rows.append(("Warehouse, once", "Carried the latest Census population forward to months Census has not published "
                     f"yet, flagged. {fixed('census')}", f"SQL in {w} (clean)"))

    if "city" in sql or "county" in sql or spec.series_by in ("city", "county"):
        rows.append(("Warehouse, once", "Counted each store in its current city and county for its whole history (a few "
                     "stores moved or were re-recorded over the years).", f"SQL in {w} (curate)"))

    # for this forecast: the AI's query, then fixed code
    rows += query_prep_rows(unit, panel, wide)
    kept = res.get("feature_groups", [])
    month_note = " (for a week, the month it starts in)" if W["grain"] == "week" else ""
    built = {"season": "time of year: where the period falls in the year. Ridge regression sees the sine and cosine of the "
                       "date, a smooth wave that repeats every year so that December sits next to January; LightGBM sees "
                       f"the month number, 1 to 12{month_note}",
             "calendar": f"business days and holidays: business days in each {W['unit']} (weekdays minus federal holidays), and four flags "
                         f"for whether Thanksgiving, Christmas, New Year's Day or July 4th falls in it",
             "population": "county population: Census population of the counties this forecast's stores are in",
             "stores": f"active stores: how many stores ordered the product in the 12 months before each {W['unit']}, "
                       f"counted one forecast horizon earlier, so the count is always known when the forecast is made"}
    offered = [g for g in built if g in spec.features]   # all of them are built; Figure 4 shows which were used
    if offered:
        rows.append(("This forecast", "Derived new features for every " + W["unit"] + ", including the "
                     + units() + " being forecast (Figure 4 shows which ones the forecast uses): "
                     + "; ".join(built[g] for g in offered) + ".",
                     f'<a href="{GITHUB}/dod/features.py">dod/features.py</a> (Python)'))
    targets = {c["target"] for c in res.get("ensemble") or []}
    scaled = "each series and input scaled to mean 0, spread 1 before fitting, and predictions scaled back"
    if targets == {"yoy"}:
        scaled = "the change from last year used as is (it has no units); inputs scaled to mean 0, spread 1"
    elif "yoy" in targets:
        scaled += " (a model predicting the change from last year uses that change as is: it has no units)"
    rows.append(("This forecast", f"Standardized for the models: {scaled}.", code("dod/model.py", "dod/model.py") + " (Python)"))
    # two parts, before and after the request, each under its own heading row
    head = "<th>what was done</th><th>done by</th>"
    part = lambda text: (f'<tr><td colspan="2" style="padding-top:14px;font-size:12px;font-weight:600;'
                         f'text-transform:uppercase;letter-spacing:.04em;color:var(--muted)">{text}</td></tr>')
    sections = [("Warehouse, once", "Before any request: building the warehouse (once, with load_data.py)"),
                ("This forecast", "After the request: shaping the data for this forecast")]
    body = "".join(part(title) + "".join(f"<tr><td>{b}</td><td>{c}</td></tr>" for a, b, c in rows if a == key)
                   for key, title in sections)
    return (f"<p>{W['adj'].capitalize()} {unit} from {when(panel.start)} through {when(wide.index[-1])}. "
            + f"The AI wrote the SQL query that selects the sales records for this request; fixed code adds them up, "
              f"and every other step is fixed code that runs the same way for every request. "
            + f"The code itself was written in advance with Claude Code, with a person reviewing and approving every data fix.</p><div class=\"tbl\"><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


REPO = "https://github.com/joehahn/demand-on-demand"


def updated_html(panel):
    """When this page was built, and how far its data goes."""
    import datetime
    d = getattr(panel, "built_at", None) or datetime.datetime.now().astimezone()   # a rebuilt page keeps its time
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
    from .agent import TOOLS
    return (f"<p><strong>The agent's toolbox.</strong> The AI agent ({esc(model_label(usage))}) does text-to-SQL. To turn "
            f"words like \u201ccream liqueur\u201d or \u201cDes Moines\u201d into the warehouse's own codes it has "
            f"{len(TOOLS) - 1} tools: search the names of products, categories, vendors, stores and places; run a small "
            f"test query; and, in a live session, ask the requester one clarifying question when a request is "
            f"ambiguous. None of them can change the data. It then writes one SQL "
            f"query that selects the sales records to forecast "
            f"(<a href=\"{REPO}/blob/main/dod/agent.py\">instructions</a>, "
            f"<a href=\"{REPO}/blob/main/dod/tools.py\">tools</a>).</p>")


def exact_html(spec, res, panel):
    """Exactly what ran: the agent's reading of the request and its SQL; everything after it is fixed code."""
    return (f"<p>What ran: the AI's SQL selecting the sales records, then fixed code for everything after it.</p>"
            f"{spec_table(spec, res)}"
            f"<details><summary>The SQL as run</summary><p>Written by the AI, checked to be one read-only SELECT, and run "
            f"under a read-only database login, inside fixed code's own sums (by {W['unit']}, store and product). It "
            f"selected {panel.records:,} sales records ({pd.Timestamp(panel.start):%b %Y} through "
            f"{panel.records_through:%b %Y}).</p>"
            f"<pre>{esc(panel.sql)}</pre></details>")


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


def products_section(products, unit, last_month):
    """Which products were added up: every product the AI's query selected, so a reader can check what it counted."""
    if products is None or products.empty:
        return ""
    recent = products[products.last_12_months > 0]
    money = "$" if unit == "dollars" else ""
    t = products.rename(columns={"product_id": "product ID", "ml": "size (ml)", "first_sold": "first sold",
                                 "last_sold": "last sold", "last_12_months": f"{unit}, last 12 months"})
    return (f"<h3>Products included</h3><p>The AI's query selected {len(products):,} products; {len(recent):,} of them "
            f"sold in the 12 months to {last_month:%b %Y}. Products renumbered over the years appear once, under their "
            f"current product ID.</p><details><summary>Show the products</summary>"
            f"{table(t, {f'{unit}, last 12 months': lambda v: f'{money}{v:,.0f}', 'size (ml)': lambda v: f'{v:,.0f}'})}"
            f"</details>")


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
            f"{esc(spec.place)} that bought {esc(spec.product)} since {spec.start[:7]}; "
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
    per = "quarter" if months.startswith("Q") else W["unit"]
    parts = [spec.product, spec.place, f"{unit} per {per}", months.replace(" ", "\u00a0"), series]
    why = (f'<details class="note"><summary>Why it was read this way</summary><ul>{assumptions_html}</ul></details>'
           if assumptions_html else "")
    return f'<p class="readas"><span>Read as</span> {" &middot; ".join(esc(x) for x in parts)}</p>{why}'


def quarters_section(res, wide, unit, plot):
    """For a quarterly request: calendar quarters, actual and forecast, with each quarter's 80% range and a table."""
    q = res.get("quarters")
    if q is None or not len(q):
        return ""
    money = "$" if unit == "dollars" else ""
    total = wide.sum(axis=1, min_count=1).dropna()
    hist = total.groupby(total.index.to_period("Q")).agg(["sum", "size"])
    hist = hist[hist["size"] == 3]["sum"].iloc[-8:]   # the last 8 complete quarters
    x_hist = [f"Q{p.quarter} {p.year}" for p in hist.index]
    fig = go.Figure([go.Bar(x=x_hist, y=hist.values, name="actual", marker_color=BLUE),
                     go.Bar(x=list(q.quarter), y=list(q.sold), name="sold so far", marker_color=BLUE, opacity=0.55),
                     go.Bar(x=list(q.quarter), y=list(q.forecast), name="forecast", marker_color=AQUA,
                            error_y=dict(type="data", symmetric=False, array=list(q.high - q.total),
                                         arrayminus=list(q.total - q.low), color="rgba(137,135,129,0.9)"))])
    fig.update_traces(hovertemplate=f"{money}%{{y:,.0f}}<extra>%{{fullData.name}}</extra>")
    fig = style(fig, "By quarter: actual, and the forecast with its 80% range", f"{unit} per quarter", height=340,
                legend=True).update_layout(barmode="stack", hovermode="closest")
    t = pd.DataFrame({"quarter": q.quarter, "months": q.months,
                      "sold so far": [f"{money}{v:,.0f}" if v else "" for v in q.sold],
                      "forecast": q.forecast.map(lambda v: f"{money}{v:,.0f}"),
                      "total": q.total.map(lambda v: f"{money}{v:,.0f}"),
                      "low (10%)": q.low.map(lambda v: f"{money}{v:,.0f}"),
                      "high (90%)": q.high.map(lambda v: f"{money}{v:,.0f}"),
                      "same quarter last year": q.last_year.map(lambda v: "" if v != v else f"{money}{v:,.0f}")})
    asked, full = res.get("quarters_asked", 0), int((q.status == "forecast").sum())
    short = (f" You asked for {asked} quarters; the models look at most 12 months ahead, so the forecast stops after "
             f"{full} full quarters." if full < asked else "")
    progress = q[q.status == "in progress"]
    inprog = (f" {progress.quarter.iloc[0]} is in progress: the months already sold are actual sales, the rest is "
              f"forecast." if len(progress) else "")
    return (f"<h2>By quarter</h2><p>The models forecast month by month; here the months are added up into calendar "
            f"quarters.{inprog}{short} Each range comes from the Testing period: forecasts made there, added up over "
            f"the same months ahead, compared with what actually sold.</p>{plot(fig)}{table(t)}")


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
    for x0, x1, name, shade in [(max(tune_start, hist.index[0]), test_start, "Tuning", 0.05),
                                (test_start, first_fc, "Testing", 0.10), (first_fc, end, "Forecast", 0.05)]:
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
    return style(fig, f"Typical miss in the Testing period, by {units()} ahead (lower is better)", "typical miss (% of actual)",
                 height=300, legend=True).update_layout(hovermode="x unified")


def fig_inputs(effects, tw):
    """How much each input group helped when re-tuning on the Testing period, which decides the forecast's inputs:
    the forecast's error without the input, relative to its error with it (right of 0 = the input helps)."""
    label = {"season": "time of year (sine/cosine, month)"}   # both encodings: ridge sees one, LightGBM the other
    names = [label.get(g, FEATURE_NAMES.get(g, g).split(" (")[0]) + (": used" if k else ": left out")
             for g, k in zip(effects.group, effects.kept)]
    fig = go.Figure(go.Bar(y=names, x=effects.latest * 100, orientation="h",
                           marker_color=[AQUA if k else ORANGE for k in effects.kept],
                           hovertemplate="%{x:+.1f}%<extra></extra>"))
    fig.update_xaxes(ticksuffix="%", zeroline=True, zerolinecolor="rgba(137,135,129,0.8)", zerolinewidth=2,
                     title="how much worse the forecast is without it (right of 0 = it helps)")
    if model.KEEP_MARGIN:
        fig.add_vline(x=model.KEEP_MARGIN * 100, line_dash="dot", line_color="rgba(137,135,129,0.8)",
                      annotation_text="keep line", annotation_position="top")
    fig = style(fig, f"Which inputs helped, Testing period ({when(tw[0])} to {when(tw[1])})", height=120 + 50 * len(effects))
    return fig.update_layout(margin=dict(l=230, r=20, t=50, b=50), hovermode="closest")


def inputs_section(res, plot):
    """The input groups offered to this forecast and how re-tuning on the Testing period judged them."""
    eff = res.get("effects")
    if eff is None or not len(eff) or eff.latest.isna().all():
        return ""
    tw = res["test_window"]
    margin = f" by at least {model.KEEP_MARGIN:.0%}" if model.KEEP_MARGIN else ""
    name = lambda g: FEATURE_NAMES.get(g, g).split(" (")[0]
    words = lambda xs: " and ".join([", ".join(xs[:-1]), xs[-1]]) if len(xs) > 1 else "".join(xs)
    used = [name(g) for g, k in zip(eff.group, eff.kept) if k]
    tested = [name(g) for g, k in zip(eff.group, eff.kept_tested) if k]
    uw = res["tune_window"]
    offered = [name(g) for g in eff.group]
    return (f"<p><strong>Inputs.</strong> Besides its own past sales, the model can learn from {words(offered)} (described "
            f"under How the data was prepared). Each was "
            f"tried with and without on the Testing period and kept only if it made the forecast better{margin}. This "
            f"forecast uses {words(used) if used else 'none of them'}. <em>Note:</em> the accuracy figures at the top come "
            f"from an earlier round of tuning ({when(uw[0])} to {when(uw[1])}), so they are measured on {units()} that "
            f"tuning never saw; that round used {words(tested) if tested else 'none of them'}.</p>"
            f"{plot(fig_inputs(eff, tw))}")


def build(spec, panel, res, usage=None, agent=None, harness_seconds=None):
    """The dashboard for one forecast: spec is the agent's Plan at the model's grain (dod/plan.py), panel the history
    fixed code built from its SQL (dod/history.py), res the model's results (dod/model.py)."""
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
    q = res.get("quarters")
    if q is not None and len(q):   # a quarterly request: the headline is the quarters reported, sold part included
        months = f"{q.quarter.iloc[0]} to {q.quarter.iloc[-1]}"
        total, last_year = q.total.sum(), q.last_year.sum(min_count=len(q))
        yoy = total / last_year - 1 if last_year == last_year and last_year else float("nan")
    rel = res["test_rel_mae"]
    money = "$" if unit == "dollars" else ""
    tiles = [
        (f"{money}{total:,.0f}", f"forecast {unit}, {months}"),
        (f"{yoy:+.1%}", f"vs the same {'quarters' if q is not None and len(q) else units()} last year"),
        (f"{bt.dropna(subset=['actual']).pipe(lambda d: (d.actual - d.pred).abs().sum() / d.actual.sum()):.0%}",
         f"typical {W['adj']} miss in the Testing period ({when(res['test_window'][0])} to {when(res['test_window'][1])})"),
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
    ly = f"same {W['unit']} last year"
    ft = fc.assign(series=fc.series.map(lambda c: labels.get(c, c)), month=fc.month.map(stamp),
                   last_year=[wide.at[back(m, W["season"]), c] if back(m, W["season"]) in wide.index else float("nan")
                              for m, c in zip(fc.month, fc.series)])
    ft = ft[["series", "month", "pred", "lo", "hi", "last_year"]].rename(
        columns={"month": W["unit"], "pred": "forecast", "lo": "low (10%)", "hi": "high (90%)", "last_year": ly})
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
            intro = ("How the AI agent (Claude) turned the request into what \u201cRead as\u201d shows at the top. It "
                     "writes the SQL that selects the sales records (which products, which stores, which measure) and "
                     "names the time grain. Fixed code then checks that the SQL can only read data, never change it; "
                     f"sums the selected records into {W['adj']} totals for each series; picks and tests the model; and "
                     f"generates this page.</p>{toolbox_html(usage)}")
            from .agent import GLOSSARY, RULES   # imported here: the agent module imports the forecast path
            rules = (f"<details><summary>The agent's rules and business definitions</summary><p>Part of its "
                     f"instructions for every request: three rules for this warehouse's traps, and the company's "
                     f"definitions of common business words.</p><pre>{esc(RULES + GLOSSARY)}</pre></details>")
            trace_html = (f"<h2>What the agent did</h2><p>{intro}{rules}{agent_knowledge(panel.sql)}"
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
{quarters_section(res, wide, unit, plot)}
{charts}{more}
<ul class="note">
<li><strong>Tuning</strong> ({when(uw[0])} to {when(uw[1])}): {refit} through these {units()}, each candidate model was
trained on all {units()} before that point and forecast the next {max(ps.step)}, and its forecasts were compared with what
actually sold. {len(res["grid"]) - 1} distinct configurations of ridge regression and LightGBM were compared, differing in
targets, inputs and history lengths{", with or without other counties" if pooling_tried else ""}, and the settings with the
smallest misses were picked: {esc(short_model(res["tested"], " + "))}.</li>
<li><strong>Testing</strong> ({when(tw[0])} to {when(tw[1])}): the picked settings forecast {units()} they never saw; this
is where the accuracy figures come from. {refit.capitalize()} the model was retrained on all {units()} before that point and forecast the next {max(ps.step)}, {bt.origin.nunique()} times in all, each scored
against what actually sold. Dotted orange is those forecasts, 1 to {max(ps.step)} {units()} ahead (pick above the
chart).</li>
<li><strong>Forecast</strong> ({months}): tuning is repeated on the Testing period, so the forecast uses the most recent
data. The re-tuned model, <strong>{esc(short_model(res, " + "))}</strong>, is retrained on everything through
{when(wide.index[-1])} and forecasts ahead.{units_note}</li>
<li><strong>Green band (80% range):</strong> inferred by comparing the model's forecasts with actual sales in the Testing
period; it spans the middle 80% of those misses.</li>
{big_buyer_note(panel.stores, unit, wide.shape[1])}
</ul>
{table(ft, {"forecast": num, "low (10%)": num, "high (90%)": num, ly: num})}

<h2>How far to trust it</h2>
<p>Every {W['unit']} in the Testing period was forecast by a model trained only on earlier {units()}, then compared with what
actually happened and with the simplest serious baseline: the {base()}.</p>
{plot(fig_accuracy(ps))}

<h2>How the data was prepared</h2>
{prep_section(spec, panel, res, unit, wide)}
{features_section(spec, panel, res, unit, fc)}
{products_section(panel.products, unit, panel.records_through)}
{stores_section(panel.stores, spec, unit, wide.index[-1], plot)}

<h2>How the model was chosen</h2>
{model_explanation(res, unit, spec, panel)}
<p>What was compared: every combination of these settings ({space_count} configurations):</p>
{space_html}
<details><summary>The 10 best configurations</summary>
<p>The forecast's re-tuning on the Testing period, with the baseline (a model had to beat it to be used). Inputs were then
kept or dropped on the same {units()}.</p>
{table(grid)}</details>
{blend_details(res)}
{inputs_section(res, plot)}

{trace_html}
<h2>Exactly what ran</h2>
{cost}
{exact_html(spec, res, panel)}

<footer>
Data: <a href="https://catalog.data.gov/dataset?q=iowa+liquor+sales">Iowa Liquor Sales</a>, State of Iowa, via the Iowa
Data Hub, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; modified (duplicates removed, aggregated).
Census population: U.S. Census Bureau. Not endorsed by the State of Iowa. Orders through {panel.data_end:%Y-%m-%d}.<br>
<a href="https://github.com/joehahn/demand-on-demand">demand-on-demand</a> by Joseph M. Hahn, Ph.D.,
<a href="https://jmh-datasciences.com">JMH DataSciences</a>.
</footer>"""
    return page(spec.title, body)
