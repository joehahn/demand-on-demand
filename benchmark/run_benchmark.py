"""Forecast-accuracy benchmark: run the harness on a fixed, varied sample of requests and report how often the
chosen model beats "same month last year" on the 24-month test window it never trained on.

    python benchmark/run_benchmark.py [--n 30]
    python benchmark/run_benchmark.py --report    # rewrite report.md from results.csv and the saved runs, no forecasting

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


def scatter_svg(ok):
    """Relative error vs sales records per month (log scale), one dot per forecast, as a small standalone SVG."""
    W, H, L, R, T, B = 640, 360, 60, 36, 20, 50          # size and margins in pixels
    xs = ok.records_per_month.clip(lower=1)
    x0, x1 = 0, math.ceil(math.log10(xs.max()))          # 1 to the next power of ten
    y0, y1 = 0, max(1.6, math.ceil(ok.rel_mae.max() * 5) / 5)
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
    s.append(f'<text x="{W - R - 4}" y="{py(1) - 6:.1f}" text-anchor="end" fill="{grey}">baseline (same month last year)</text>')
    for r in ok.itertuples():                             # blue beats the baseline, orange does not
        color = "#2a78d6" if r.rel_mae < 1 else "#e8692e"
        s.append(f'<circle cx="{px(max(r.records_per_month, 1)):.1f}" cy="{py(r.rel_mae):.1f}" r="5" fill="{color}" '
                 f'fill-opacity="0.85"><title>{html.escape(r.forecast)}: {r.rel_mae:.2f}</title></circle>')
    s.append(f'<text x="{(L + W - R) / 2}" y="{H - 12}" text-anchor="middle" fill="{ink}">sales records per month (log scale)</text>')
    s.append(f'<text x="16" y="{(T + H - B) / 2}" text-anchor="middle" fill="{ink}" '
             f'transform="rotate(-90 16 {(T + H - B) / 2})">relative error (below 1 beats the baseline)</text>')
    (HERE / "volume.svg").write_text("\n".join(s) + "\n</svg>\n")


def write_report(df):
    """benchmark/report.md from the results table (one row per sampled forecast)."""
    ok = df.dropna(subset=["rel_mae"])
    better = (ok.rel_mae < 1).sum()
    md = [f"# Forecast-accuracy benchmark\n",
          f"{len(df)} forecasts sampled from the warehouse (seed 0), {len(ok)} completed, in {ok.seconds.sum():.0f}s "
          f"({ok.seconds.median():.0f}s median each).\n",
          f"- Beat \"same month last year\" on the 24-month test window: **{better} of {len(ok)}** ({better / len(ok):.0%})",
          f"- Median error relative to that baseline: **{ok.rel_mae.median():.2f}** (below 1 is better)",
          f"- Median monthly error (WAPE, weighted absolute percentage error: total absolute error divided by total actual sales): model {ok.model_error.median():.1%}, baseline {ok.baseline_error.median():.1%}",
          f"- Volume matters: the 10 forecasts with the fewest sales records per month beat the baseline "
          f"{(ok.nsmallest(10, 'records_per_month').rel_mae < 1).sum()} times, the 10 with the most "
          f"{(ok.nlargest(10, 'records_per_month').rel_mae < 1).sum()} times. With a handful of orders a month, one "
          f"order more or less swings the total, and neither the model nor the baseline can predict that.\n",
          "![Relative error vs sales records per month: low-volume forecasts scatter around or above 1, high-volume "
          "ones mostly below](volume.svg)\n",
          "| forecast | horizon | sales records per month | relative error | model error | baseline error | model |",
          "|---|---|---|---|---|---|---|"]
    for r in ok.sort_values("rel_mae").itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | {r.records_per_month:,.0f} | {r.rel_mae:.2f} | {r.model_error:.1%} | "
                  f"{r.baseline_error:.1%} | {r.model} |")
    for r in df[df.rel_mae.isna()].itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | | not run: {r.error} | | | |")
    scatter_svg(ok)
    (HERE / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:7]))


def sample_specs(n, seed=0):
    rnd = random.Random(seed)
    products = db.query("""SELECT h.item_no, h.item_desc, h.bottle_volume_ml, sum(i.total_bottles) AS b
                           FROM sales.item i JOIN sales.item h ON h.item_no = i.family_item_no
                           WHERE h.last_order_on > '2026-06-01' GROUP BY 1, 2, 3 ORDER BY b DESC LIMIT 60""")
    cats = db.query("""SELECT c.category_code, c.category_name FROM sales.category c
                       JOIN sales.item i ON i.category_current = c.category_code
                       GROUP BY 1, 2 ORDER BY sum(i.total_bottles) DESC LIMIT 25""")
    counties = db.query("""SELECT county_fips, county_name, count(*) AS stores FROM sales.store WHERE county_fips IS NOT NULL
                           GROUP BY 1, 2 ORDER BY stores DESC LIMIT 30""")
    vendors = db.query("""SELECT v.vendor_no, v.vendor_name FROM sales.vendor v JOIN sales.item i USING (vendor_no)
                          GROUP BY 1, 2 ORDER BY sum(i.total_bottles) DESC LIMIT 15""")
    targets = ["sales_bottles", "sales_dollars", "sales_liters"]
    specs = [Spec(title="All liquor, statewide", target="sales_dollars", horizon=6,
                  product={"kind": "all", "label": "All liquor"}, region={"kind": "statewide", "label": "Iowa"})]
    while len(specs) < n:
        kind = rnd.choice(["item_county", "item_state", "cat_state", "cat_county", "vendor_county"])
        target, horizon = rnd.choice(targets), rnd.choice([3, 6, 12])
        c = counties.iloc[rnd.randrange(len(counties))]
        county = {"kind": "county", "codes": [c.county_fips], "label": f"{c.county_name.title()} County"}
        state = {"kind": "statewide", "label": "Iowa"}
        if kind.startswith("item"):
            p = products.iloc[rnd.randrange(len(products))]
            prod = {"kind": "item", "codes": [p.item_no], "label": f"{p.item_desc.title()} {p.bottle_volume_ml} ml"}
        elif kind.startswith("cat"):
            p = cats.iloc[rnd.randrange(len(cats))]
            prod = {"kind": "category", "codes": [p.category_code], "label": p.category_name.title()}
        else:
            p = vendors.iloc[rnd.randrange(len(vendors))]
            prod = {"kind": "vendor", "codes": [p.vendor_no], "label": p.vendor_name.title()}
        region = state if kind.endswith("state") else county
        title = f"{prod['label']}, {region['label']}, {target.replace('sales_', '')}, {horizon} months"
        specs.append(Spec(title=title, target=target, horizon=horizon, product=prod, region=region))
    return specs


if __name__ == "__main__":
    if "--report" in sys.argv:   # rewrite the report from the last run's results
        df = pd.read_csv(HERE / "results.csv")
        if "records_per_month" not in df:   # results written before this column existed
            df["records_per_month"] = [records_per_month(f) if pd.notna(e) else None for f, e in zip(df.forecast, df.rel_mae)]
            df.to_csv(HERE / "results.csv", index=False)
        write_report(df)
        sys.exit()
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    rows, t0 = [], time.time()
    out_root = HERE / "out"
    for spec in sample_specs(n):
        try:
            s = run_spec(spec, out_root)
            ps = pd.DataFrame(s["per_step"])
            rows.append({"forecast": spec.title, "horizon": spec.horizon, "rel_mae": s["test_rel_mae"],
                         "model_error": (ps.wape * ps.folds).sum() / ps.folds.sum(),
                         "baseline_error": (ps.wape_naive * ps.folds).sum() / ps.folds.sum(),
                         "model": s["best"].get("model"), "seconds": s["seconds"],
                         "records_per_month": records_per_month(spec.title)})
        except Exception as e:  # too little history etc. is a result, not a crash
            rows.append({"forecast": spec.title, "horizon": spec.horizon, "error": str(e)[:120]})
        r = rows[-1]
        print(f"  {r.get('rel_mae', float('nan')):.3f}  {r['forecast']}" + (f"  ERROR {r['error']}" if "error" in r else ""))
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "results.csv", index=False)
    write_report(df)
