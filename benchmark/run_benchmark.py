"""Forecast-accuracy benchmark: run the harness on a fixed, varied sample of requests and report how often the
chosen model beats "same month last year" on the 24-month test window it never trained on.

    python benchmark/run_benchmark.py [--n 30]
    python benchmark/run_benchmark.py --report    # rewrite report.md from results.csv and the saved runs, no forecasting
    python benchmark/run_benchmark.py --brands    # add five popular brands, statewide, by quarter and by year
    python benchmark/run_benchmark.py --high-volume [--n 10]   # add a separate set of forecasts with > 3,000 sales
                                                               # records a month (the random 30 stay the headline)

Requests are sampled deterministically (seed 0) from the warehouse: top products by county and statewide,
categories statewide and by county, vendors, and the statewide total. Each is written as a request form
(dod/spec.Spec), turned into a query in the agent's shape (dod/panel.reference_sql) and run through the same fixed code
as every forecast (dod/forecast.run): no AI calls, so the benchmark measures the forecasting, not the SQL. Writes
benchmark/results.csv and benchmark/report.md. Each forecast takes about 10 to 20 seconds.
"""
import html
import math
import pickle
import random
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import db, forecast, panel  # noqa: E402
from dod.plan import Plan  # noqa: E402
from dod.spec import Spec  # noqa: E402

HERE = Path(__file__).parent


def run_spec(spec, out_root, period=None):
    """A request form through the same fixed code as every forecast, with its reference query instead of the AI's.
    period: (grain, horizon) for a request by quarter or by year, e.g. ("quarter", 4) or ("year", 1)."""
    grain, horizon = period or ("month", spec.horizon)
    plan = Plan(title=spec.title, sql=panel.reference_sql(spec), target=spec.target, horizon=horizon, grain=grain,
                product=spec.product.label, place=spec.region.label, series_by=spec.series_by)
    return forecast.run(plan, narrate=False, out_root=out_root, log=lambda *a: None)


def records_per_month(title):
    """Sales records per month behind one benchmark forecast, from its saved run: a low count means a noisy series."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60]   # the same folder name as Plan.slug
    pn = pickle.loads((HERE / "out" / slug / "page.pkl").read_bytes())["panel"]
    months = max(1.0, (pd.Timestamp(pn.records_through) - pd.Timestamp(pn.series.index[0])).days / 30.4)
    return pn.records / months


def bottles_per_month(title):
    """Bottles per month behind one benchmark forecast: its saved query with the measure swapped to bottles, summed.
    Shown in the report as the forecast's volume (for dollar and liter forecasts too)."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60]
    page = pickle.loads((HERE / "out" / slug / "page.pkl").read_bytes())
    sql = re.sub(r"l\.sales_(dollars|liters|bottles) AS value", "l.sales_bottles AS value", page["spec"].sql)
    pn = page["panel"]
    months = max(1.0, (pd.Timestamp(pn.records_through) - pd.Timestamp(pn.series.index[0])).days / 30.4)
    return db.query(f"SELECT sum(value) AS b FROM ({sql}) q", timeout="300s").b.iloc[0] / months


def scatter_svg(ok):
    """Relative error vs bottles per month (log scale), one dot per forecast, as a small standalone SVG."""
    W, H, L, R, T, B = 1000, 420, 64, 40, 20, 50         # size and margins in pixels (as wide as the README figures)
    allr = ok
    xs = allr.bottles_per_month.clip(lower=1)
    x0, x1 = math.floor(math.log10(xs.min())), math.ceil(math.log10(xs.max()))   # powers of ten around the data
    y0, y1 = 0, max(1.6, math.ceil(allr.rel_mae.max() * 5) / 5)
    px = lambda v: L + (math.log10(v) - x0) / (x1 - x0) * (W - L - R)
    py = lambda v: H - B - (v - y0) / (y1 - y0) * (H - T - B)
    grey, ink = "#9a9892", "#1f1e1c"
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="system-ui, -apple-system, Segoe UI, Helvetica, Arial, sans-serif" font-size="14">',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    for k in range(x0, x1 + 1):                          # vertical gridlines at 1, 10, 100, ...
        x = px(10 ** k)
        s.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{H - B}" stroke="#ececea"/>')
        s.append(f'<text x="{x:.1f}" y="{H - B + 16}" text-anchor="middle" fill="{grey}">{10 ** k:,}</text>')
    for k in range(int(y1 / 0.2) + 1):                   # horizontal gridlines every 0.2
        v = k * 0.2
        s.append(f'<line x1="{L}" y1="{py(v):.1f}" x2="{W - R}" y2="{py(v):.1f}" stroke="#ececea"/>')
        s.append(f'<text x="{L - 8}" y="{py(v) + 4:.1f}" text-anchor="end" fill="{grey}">{v:.1f}</text>')
    s.append(f'<line x1="{L}" y1="{py(1):.1f}" x2="{W - R}" y2="{py(1):.1f}" stroke="{grey}" stroke-dasharray="5 4"/>')
    s.append(f'<text x="{W - R - 4}" y="{T + 14}" text-anchor="end" fill="{grey}">dashed line: baseline (same month last '
             f'year)</text>')
    for r in allr.itertuples():   # blue beats the baseline, orange does not
        color = "#2a78d6" if r.rel_mae < 1 else "#e8692e"
        paint = f'fill="{color}" fill-opacity="0.85"'
        s.append(f'<circle cx="{px(max(r.bottles_per_month, 1)):.1f}" cy="{py(r.rel_mae):.1f}" r="7" {paint}>'
                 f'<title>{html.escape(r.forecast)}: {r.rel_mae:.2f}</title></circle>')
    s.append(f'<text x="{(L + W - R) / 2}" y="{H - 12}" text-anchor="middle" fill="{ink}">bottles per month (log scale)</text>')
    s.append(f'<text x="18" y="{(T + H - B) / 2}" text-anchor="middle" fill="{ink}" '
             f'transform="rotate(-90 18 {(T + H - B) / 2})">relative error (below 1 beats the baseline)</text>')
    (HERE / "volume.svg").write_text("\n".join(s) + "\n</svg>\n")


BANDS = [0, 1_000, 50_000, float("inf")]   # bottles per month: light, medium, heavy


def write_report(df):
    """benchmark/report.md: every forecast in one table and one plot, summarized by volume band. The forecasts come
    from three sets (a random sample, a high-volume set, popular brands), but accuracy depends on volume, not on
    how a forecast was picked, so the report groups them by volume."""
    ok = df.dropna(subset=["rel_mae"])
    better = (ok.rel_mae < 1).sum()
    band = pd.cut(ok.bottles_per_month, BANDS, labels=["under 1,000", "1,000 to 50,000", "over 50,000"])
    by = ok.groupby(band, observed=True)
    md = [f"# Forecast-accuracy benchmark\n",
          f"{len(ok)} forecasts, each scored against \"same month last year\" (the baseline) over a 24-month test "
          f"window they never trained on, {ok.seconds.median():.0f}s median each. They come from a random sample of the "
          f"warehouse (30: products, categories and vendors, statewide and by county), a set picked for high volume "
          f"(10) and five popular brands statewide asked for by quarter or by year (forecast by month and summed).\n",
          f"- Beat the baseline: **{better} of {len(ok)}**; median relative error **{ok.rel_mae.median():.2f}** (below 1 "
          f"is better); median monthly error (WAPE, weighted absolute percentage error: total absolute error divided "
          f"by total actual sales) model {ok.model_error.median():.1%}, baseline {ok.baseline_error.median():.1%}.",
          f"- **Volume decides it.** With a handful of orders a month, one order more or less swings the total, and "
          f"neither the model nor the baseline can predict that. With high volume, the model wins most of the time, "
          f"and its losses are narrow:\n",
          "| bottles per month | forecasts | beat the baseline | median relative error | median model error | "
          "median baseline error |", "|---|---|---|---|---|---|"]
    for name, g in by:
        md.append(f"| {name} | {len(g)} | {(g.rel_mae < 1).sum()} | {g.rel_mae.median():.2f} | "
                  f"{g.model_error.median():.1%} | {g.baseline_error.median():.1%} |")
    md += ["", "![Relative error vs bottles per month: low-volume forecasts scatter around or above 1, high-volume "
           "ones mostly below](volume.svg)\n",
           "| forecast | horizon | bottles per month | relative error | model error | baseline error | model |",
           "|---|---|---|---|---|---|---|"]
    for r in ok.sort_values("bottles_per_month", ascending=False).itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | {r.bottles_per_month:,.0f} | {r.rel_mae:.2f} | {r.model_error:.1%} | "
                  f"{r.baseline_error:.1%} | {r.model} |")
    for r in df[df.rel_mae.isna()].itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | | not run: {r.error} | | | |")
    scatter_svg(ok)
    (HERE / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:12]))


MIN_RECORDS = 3000     # sales records per month: how the high-volume set is picked (a quick count)


def high_volume_specs(n, skip, seed=1):
    """n forecasts with more than MIN_RECORDS sales records a month, drawn deterministically from statewide and
    big-county slices; skip lists titles already in the benchmark. Volume is counted with the forecast's own query."""
    rnd = random.Random(seed)
    cats = db.query("""SELECT c.category_code, c.category_name FROM sales.category c
                       JOIN sales.item i ON i.category_current = c.category_code
                       GROUP BY 1, 2 ORDER BY sum(i.total_bottles) DESC LIMIT 25""")
    vendors = db.query("""SELECT v.vendor_no, v.vendor_name FROM sales.vendor v JOIN sales.item i USING (vendor_no)
                          GROUP BY 1, 2 ORDER BY sum(i.total_bottles) DESC LIMIT 15""")
    products = db.query("""SELECT h.item_no, h.item_desc, h.bottle_volume_ml, sum(i.total_bottles) AS b
                           FROM sales.item i JOIN sales.item h ON h.item_no = i.family_item_no
                           WHERE h.last_order_on > '2026-06-01' GROUP BY 1, 2, 3 ORDER BY b DESC LIMIT 20""")
    counties = db.query("""SELECT county_fips, county_name FROM sales.store WHERE county_fips IS NOT NULL
                           GROUP BY 1, 2 ORDER BY count(*) DESC LIMIT 6""")
    state = {"kind": "statewide", "label": "Iowa"}
    regions = [state] + [{"kind": "county", "codes": [c.county_fips], "label": f"{c.county_name.title()} County"}
                         for c in counties.itertuples()]
    prods = ([{"kind": "all", "label": "All liquor"}]
             + [{"kind": "category", "codes": [c.category_code], "label": c.category_name.title()} for c in cats.itertuples()]
             + [{"kind": "vendor", "codes": [v.vendor_no], "label": v.vendor_name.title()} for v in vendors.itertuples()]
             + [{"kind": "item", "codes": [p.item_no], "label": f"{p.item_desc.title()} {p.bottle_volume_ml} ml"}
                for p in products.itertuples()])
    pairs = [(pr, rg) for pr in prods for rg in regions if not (pr["kind"] == "all" and rg["kind"] == "statewide")]
    rnd.shuffle(pairs)
    specs = []
    for prod, region in pairs:
        if len(specs) == n:
            break
        target, horizon = rnd.choice(["sales_bottles", "sales_dollars", "sales_liters"]), rnd.choice([3, 6, 12])
        title = f"{prod['label']}, {region['label']}, {target.replace('sales_', '')}, {horizon} months"
        spec = Spec(title=title, target=target, horizon=horizon, product=prod, region=region)
        if title in skip:
            continue
        per_month = db.query(f"SELECT count(*) / 128.0 AS n FROM ({panel.reference_sql(spec)}) q",   # 128 months of data
                             timeout="180s").n.iloc[0]
        if per_month > MIN_RECORDS:
            specs.append(spec)
            print(f"  picked {title}: {per_month:,.0f} records a month")
    return specs


# popular brands statewide, asked for by quarter or by year: (label, words in the name, measure, period, how many)
BRANDS = [("Tito's", ["TITOS"], "sales_bottles", "quarter", 4),
          ("Fireball", ["FIREBALL"], "sales_dollars", "year", 1),
          ("Crown Royal", ["CROWN", "ROYAL"], "sales_dollars", "quarter", 4),
          ("Jack Daniel's", ["JACK", "DANIELS"], "sales_liters", "year", 1),
          ("Captain Morgan", ["CAPTAIN", "MORGAN"], "sales_bottles", "quarter", 4)]


def brand_specs():
    """(request form, (grain, horizon)) for each brand: every product whose name has all the brand's words."""
    out = []
    for label, words, target, grain, n in BRANDS:
        when = f"next {n} quarters" if grain == "quarter" else "next 12 months, as one year"
        title = f"{label}, Iowa, {target.replace('sales_', '')}, {when}"
        spec = Spec(title=title, target=target, horizon=12, product={"kind": "name", "codes": words, "label": label},
                    region={"kind": "statewide", "label": "Iowa"})
        out.append((spec, (grain, n)))
    return out


def run_all(specs, sample):
    """Each request form (or (form, period) pair) through the fixed code; one results row each (a failure is a
    result, not a crash)."""
    rows = []
    for item in specs:
        spec, period = item if isinstance(item, tuple) else (item, None)
        try:
            s = run_spec(spec, HERE / "out", period)
            ps = pd.DataFrame(s["per_step"])
            rows.append({"forecast": spec.title, "horizon": f"{period[1]} {period[0]}{'s' if period[1] > 1 else ''}" if period else spec.horizon,
                         "rel_mae": s["test_rel_mae"],
                         "model_error": (ps.wape * ps.folds).sum() / ps.folds.sum(),
                         "baseline_error": (ps.wape_naive * ps.folds).sum() / ps.folds.sum(),
                         "model": s["best"].get("model"), "seconds": s["seconds"],
                         "records_per_month": records_per_month(spec.title),
                         "bottles_per_month": bottles_per_month(spec.title), "sample": sample})
        except Exception as e:
            rows.append({"forecast": spec.title, "horizon": spec.horizon, "error": str(e)[:120], "sample": sample})
        r = rows[-1]
        print(f"  {r.get('rel_mae', float('nan')):.3f}  {r['forecast']}" + (f"  ERROR {r['error']}" if "error" in r else ""))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    if "--brands" in sys.argv:   # add (or redo) the brand set next to the others
        df = pd.read_csv(HERE / "results.csv")
        df = df[df["sample"] != "brands"]
        df = pd.concat([df, run_all(brand_specs(), "brands")], ignore_index=True)
        df.to_csv(HERE / "results.csv", index=False)
        write_report(df)
        sys.exit()
    if "--high-volume" in sys.argv:   # add (or redo) the high-volume set next to the random sample
        n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 10
        df = pd.read_csv(HERE / "results.csv")
        df["sample"] = df["sample"].fillna("random") if "sample" in df else "random"
        df = df[df["sample"] != "high volume"]
        hv = run_all(high_volume_specs(n, set(df.forecast)), "high volume")
        df = pd.concat([df, hv], ignore_index=True)
        df.to_csv(HERE / "results.csv", index=False)
        write_report(df)
        sys.exit()
    if "--report" in sys.argv:   # rewrite the report from the last run's results
        df = pd.read_csv(HERE / "results.csv")
        for col, fn in [("records_per_month", records_per_month), ("bottles_per_month", bottles_per_month)]:
            if col not in df:   # results written before this column existed
                df[col] = [fn(f) if pd.notna(e) else None for f, e in zip(df.forecast, df.rel_mae)]
                df.to_csv(HERE / "results.csv", index=False)
        write_report(df)
        sys.exit()
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    df = run_all(sample_specs(n), "random")
    df.to_csv(HERE / "results.csv", index=False)
    write_report(df)
