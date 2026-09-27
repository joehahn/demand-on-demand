"""Forecast-accuracy benchmark: run the harness on a fixed, varied sample of requests and report how often the
chosen model beats "same month last year" on the 24-month test window it never trained on.

    python benchmark/run_benchmark.py [--n 30]

Specs are sampled deterministically (seed 0) from the warehouse: top products by county and statewide,
categories statewide and by county, vendors, and the statewide total. Writes benchmark/results.csv and
benchmark/report.md. No LLM calls; each forecast takes about 10 seconds.
"""
import random
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import db, run  # noqa: E402
from dod.spec import Spec  # noqa: E402

HERE = Path(__file__).parent


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
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    rows, t0 = [], time.time()
    out_root = HERE / "out"
    for spec in sample_specs(n):
        try:
            s = run.run(spec, out_root=out_root, log=lambda *a: None)
            ps = pd.DataFrame(s["per_step"])
            rows.append({"forecast": spec.title, "horizon": spec.horizon, "rel_mae": s["test_rel_mae"],
                         "model_error": (ps.wape * ps.folds).sum() / ps.folds.sum(),
                         "baseline_error": (ps.wape_naive * ps.folds).sum() / ps.folds.sum(),
                         "model": s["best"].get("model"), "seconds": s["seconds"]})
        except Exception as e:  # too little history etc. is a result, not a crash
            rows.append({"forecast": spec.title, "horizon": spec.horizon, "error": str(e)[:120]})
        r = rows[-1]
        print(f"  {r.get('rel_mae', float('nan')):.3f}  {r['forecast']}" + (f"  ERROR {r['error']}" if "error" in r else ""))
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "results.csv", index=False)
    ok = df.dropna(subset=["rel_mae"])
    better = (ok.rel_mae < 1).sum()
    md = [f"# Forecast-accuracy benchmark\n",
          f"{len(df)} forecasts sampled from the warehouse (seed 0), {len(ok)} completed, in {time.time() - t0:.0f}s "
          f"({ok.seconds.median():.0f}s median each).\n",
          f"- Beat \"same month last year\" on the 24-month test window: **{better} of {len(ok)}** ({better / len(ok):.0%})",
          f"- Median error relative to that baseline: **{ok.rel_mae.median():.2f}** (below 1 is better)",
          f"- Median monthly error (WAPE): model {ok.model_error.median():.1%}, baseline {ok.baseline_error.median():.1%}\n",
          "| forecast | horizon | relative error | model error | baseline error | model |", "|---|---|---|---|---|---|"]
    for r in ok.sort_values("rel_mae").itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | {r.rel_mae:.2f} | {r.model_error:.1%} | {r.baseline_error:.1%} | {r.model} |")
    for r in df[df.rel_mae.isna()].itertuples():
        md.append(f"| {r.forecast} | {r.horizon} | not run: {r.error} | | | |")
    (HERE / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:6]))
