"""Forecast-accuracy benchmark: run the harness on a fixed, varied sample of requests and report how often the
chosen model beats "same month last year" on the 24-month test window it never trained on.

    python benchmark/run_benchmark.py [--n 30]
    python benchmark/run_benchmark.py --report    # rewrite report.md from results.csv and the saved runs, no forecasting
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


def run_spec(spec, out_root):
    """A request form through the same fixed code as every forecast, with its reference query instead of the AI's."""
    plan = Plan(title=spec.title, sql=panel.reference_sql(spec), target=spec.target, horizon=spec.horizon,
                product=spec.product.label, place=spec.region.label, series_by=spec.series_by)
    return forecast.run(plan, narrate=False, out_root=out_root, log=lambda *a: None)


def records_per_month(title):
    """Sales records per month behind one benchmark forecast, from its saved run: a low count means a noisy series."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60]   # the same folder name as Plan.slug
    pn = pickle.loads((HERE / "out" / slug / "page.pkl").read_bytes())["panel"]
    months = max(1.0, (pd.Timestamp(pn.records_through) - pd.Timestamp(pn.series.index[0])).days / 30.4)
    return pn.records / months


def scatter_svg(ok, hv=None):
    """Relative error vs sales records per month (log scale), one dot per forecast, as a small standalone SVG."""
    W, H, L, R, T, B = 640, 360, 60, 36, 20, 50          # size and margins in pixels
    hv = hv if hv is not None else ok.iloc[:0]
    allr = pd.concat([ok.assign(ring=False), hv.assign(ring=True)])
    xs = allr.records_per_month.clip(lower=1)
    x0, x1 = 0, math.ceil(math.log10(xs.max()))          # 1 to the next power of ten
    y0, y1 = 0, max(1.6, math.ceil(allr.rel_mae.max() * 5) / 5)
    px = lambda v: L + (math.log10(v) - x0) / (x1 - x0) * (W - L - R)
    py = lambda v: H - B - (v - y0) / (y1 - y0) * (H - T - B)
    grey, ink = "#9a9892", "#1f1e1c"
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="system-ui, -apple-system, Segoe UI, Helvetica, Arial, sans-serif" font-size="12">',
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
             f'year); rings: high-volume set</text>')
    for r in allr.itertuples():   # blue beats the baseline, orange does not; rings are the high-volume set
        color = "#2a78d6" if r.rel_mae < 1 else "#e8692e"
        paint = f'fill="none" stroke="{color}" stroke-width="2"' if r.ring else f'fill="{color}" fill-opacity="0.85"'
        s.append(f'<circle cx="{px(max(r.records_per_month, 1)):.1f}" cy="{py(r.rel_mae):.1f}" r="5" {paint}>'
                 f'<title>{html.escape(r.forecast)}: {r.rel_mae:.2f}</title></circle>')
    s.append(f'<text x="{(L + W - R) / 2}" y="{H - 12}" text-anchor="middle" fill="{ink}">sales records per month (log scale)</text>')
    s.append(f'<text x="16" y="{(T + H - B) / 2}" text-anchor="middle" fill="{ink}" '
             f'transform="rotate(-90 16 {(T + H - B) / 2})">relative error (below 1 beats the baseline)</text>')
    (HERE / "volume.svg").write_text("\n".join(s) + "\n</svg>\n")


def table(rows):
    """Markdown table rows, best relative error first."""
    md = ["| forecast | horizon | sales records per month | relative error | model error | baseline error | model |",
          "|---|---|---|---|---|---|---|"]
    for r in rows.sort_values("rel_mae").itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | {r.records_per_month:,.0f} | {r.rel_mae:.2f} | {r.model_error:.1%} | "
                  f"{r.baseline_error:.1%} | {r.model} |")
    return md


def write_report(df):
    """benchmark/report.md: the random sample is the headline; a high-volume set, if run, is reported beside it."""
    df = df.assign(sample=df["sample"].fillna("random") if "sample" in df else "random")
    rnd_all = df[df["sample"] == "random"]
    ok = rnd_all.dropna(subset=["rel_mae"])
    hv = df[(df["sample"] == "high volume")].dropna(subset=["rel_mae"])
    better = (ok.rel_mae < 1).sum()
    md = [f"# Forecast-accuracy benchmark\n",
          f"{len(rnd_all)} forecasts sampled from the warehouse (seed 0), {len(ok)} completed, in {ok.seconds.sum():.0f}s "
          f"({ok.seconds.median():.0f}s median each).\n",
          f"- Beat \"same month last year\" on the 24-month test window: **{better} of {len(ok)}** ({better / len(ok):.0%})",
          f"- Median error relative to that baseline: **{ok.rel_mae.median():.2f}** (below 1 is better)",
          f"- Median monthly error (WAPE, weighted absolute percentage error: total absolute error divided by total actual sales): model {ok.model_error.median():.1%}, baseline {ok.baseline_error.median():.1%}",
          f"- Volume matters: the 10 forecasts with the fewest sales records per month beat the baseline "
          f"{(ok.nsmallest(10, 'records_per_month').rel_mae < 1).sum()} times, the 10 with the most "
          f"{(ok.nlargest(10, 'records_per_month').rel_mae < 1).sum()} times. With a handful of orders a month, one "
          f"order more or less swings the total, and neither the model nor the baseline can predict that.\n"]
    if len(hv):
        both = pd.concat([ok, hv])
        big = both[both.records_per_month > MIN_RECORDS]
        md += [f"**High-volume check.** {len(hv)} more forecasts were picked to have over {MIN_RECORDS:,} sales records a "
               f"month (statewide and big-county categories, vendors and products; seed 1). They beat the baseline "
               f"**{(hv.rel_mae < 1).sum()} of {len(hv)}** times, median relative error **{hv.rel_mae.median():.2f}**. "
               f"With the random sample's high-volume forecasts, {(big.rel_mae < 1).sum()} of {len(big)} forecasts over "
               f"{MIN_RECORDS:,} records a month beat the baseline (ringed dots below are the high-volume set).\n"]
    md += ["![Relative error vs sales records per month: low-volume forecasts scatter around or above 1, high-volume "
           "ones mostly below](volume.svg)\n", "## Random sample\n"] + table(ok)
    for r in rnd_all[rnd_all.rel_mae.isna()].itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | | not run: {r.error} | | | |")
    if len(hv):
        md += ["", f"## High-volume set (over {MIN_RECORDS:,} sales records a month)\n"] + table(hv)
    scatter_svg(ok, hv)
    (HERE / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:8]))


MIN_RECORDS = 3000   # sales records per month for the high-volume set


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


def run_all(specs, sample):
    """Each request form through the fixed code; one results row each (a failure is a result, not a crash)."""
    rows = []
    for spec in specs:
        try:
            s = run_spec(spec, HERE / "out")
            ps = pd.DataFrame(s["per_step"])
            rows.append({"forecast": spec.title, "horizon": spec.horizon, "rel_mae": s["test_rel_mae"],
                         "model_error": (ps.wape * ps.folds).sum() / ps.folds.sum(),
                         "baseline_error": (ps.wape_naive * ps.folds).sum() / ps.folds.sum(),
                         "model": s["best"].get("model"), "seconds": s["seconds"],
                         "records_per_month": records_per_month(spec.title), "sample": sample})
        except Exception as e:
            rows.append({"forecast": spec.title, "horizon": spec.horizon, "error": str(e)[:120], "sample": sample})
        r = rows[-1]
        print(f"  {r.get('rel_mae', float('nan')):.3f}  {r['forecast']}" + (f"  ERROR {r['error']}" if "error" in r else ""))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    if "--high-volume" in sys.argv:   # add (or redo) the high-volume set next to the random sample
        n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 10
        df = pd.read_csv(HERE / "results.csv")
        df["sample"] = df["sample"].fillna("random") if "sample" in df else "random"
        df = df[df["sample"] == "random"]
        hv = run_all(high_volume_specs(n, set(df.forecast)), "high volume")
        df = pd.concat([df, hv], ignore_index=True)
        df.to_csv(HERE / "results.csv", index=False)
        write_report(df)
        sys.exit()
    if "--report" in sys.argv:   # rewrite the report from the last run's results
        df = pd.read_csv(HERE / "results.csv")
        if "records_per_month" not in df:   # results written before this column existed
            df["records_per_month"] = [records_per_month(f) if pd.notna(e) else None for f, e in zip(df.forecast, df.rel_mae)]
            df.to_csv(HERE / "results.csv", index=False)
        write_report(df)
        sys.exit()
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    df = run_all(sample_specs(n), "random")
    df.to_csv(HERE / "results.csv", index=False)
    write_report(df)
