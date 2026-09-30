"""Step 3 experiment: forecast big buyers separately. For each single-series forecast (benchmark sample + the five
examples), find stores with > SHARE of the series during model selection (before the test window, so no leakage).
Compare the current harness on the total against: harness on (total - big buyers) + big buyers' expected volume,
estimated at each backtest origin from earlier data only. Scored like the harness: relative MAE vs same month last
year on the same test months."""
import json, sys, glob, os, time
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "benchmark"))  # run from the repo root: python benchmark/big_buyer_experiment.py benchmark/big_buyers.csv
from dod import db, model, panel
from dod.spec import Spec
import run_benchmark

SHARE = 0.20

def per_store(spec):
    items = panel.member_items(spec)
    sql, params = panel.build_sql(spec, items)
    raw = db.query(sql, params)
    raw["month"] = pd.to_datetime(raw.month)
    return raw

def buyer_forecast(b, origin, month, how):
    """Expected big-buyer volume for `month`, from data before `origin` only."""
    hist = b[b.index < origin]
    if how == "same_month":   # same calendar month in up to 3 earlier years
        same = hist[hist.index.month == month.month].iloc[-3:]
        return same.mean() if len(same) else 0.0
    return hist.iloc[-12:].mean() if len(hist) else 0.0   # flat: last 12 months' average

specs = run_benchmark.sample_specs(30)
for e in json.load(open("docs/examples/index.json")):
    src = max([d for d in glob.glob("out/*/summary.json") if json.load(open(d))["title"] == e["title"]], key=os.path.getmtime)
    specs.append(Spec.model_validate(json.load(open(src))["spec"]))

rows = []
for spec in specs:
    if spec.series_by != "none":
        continue
    t0 = time.time()
    p = panel.build(spec)
    T = p.series.iloc[:, 0]
    code = p.series.columns[0]
    tune_origins, test_origins = model.windows(p.series, spec.horizon)
    raw = per_store(spec)
    raw = raw[raw.month <= T.index[-1]]
    sel = raw[(raw.month >= tune_origins[0]) & (raw.month < test_origins[0])]
    share = sel.groupby("store_no").value.sum() / sel.value.sum()
    big = list(share[share > SHARE].index)
    if not big:
        rows.append({"forecast": spec.title, "big_buyers": 0}); print(spec.title, "- no big buyer", flush=True); continue
    B = raw[raw.store_no.isin(big)].groupby("month").value.sum().reindex(T.index, fill_value=0.0)
    R = (T - B).clip(lower=0)
    wide_R = pd.DataFrame({code: R.where(T.notna())})
    base = model.run(p.series, p.exog, p.future_index, spec.horizon, spec.features, log=lambda *a: None, pool=p.pool)
    split = model.run(wide_R, p.exog, p.future_index, spec.horizon, spec.features, log=lambda *a: None, pool=p.pool)
    bt = split["backtest"].copy()
    res = {"forecast": spec.title, "big_buyers": len(big), "big_share": round(share[big].sum(), 2),
           "current": round(base["test_rel_mae"], 3)}
    for how in ("same_month", "flat"):
        b = bt.copy()
        b["pred"] = b.pred + [buyer_forecast(B, o, m, how) for o, m in zip(b.origin, b.month)]
        b["actual"] = [T[m] for m in b.month]
        b["naive"] = [model.seasonal_naive(p.series, m, code) for m in b.month]
        res[f"split_{how}"] = round(model.score(b), 3)
    rows.append(res); print(res, f"{time.time() - t0:.0f}s", flush=True)

out = pd.DataFrame(rows)
out.to_csv(sys.argv[1], index=False)
has = out[out.big_buyers > 0]
print(f"\n{len(out)} single-series forecasts, {len(has)} with a big buyer (> {SHARE:.0%} in model selection)")
if len(has):
    for c in ("split_same_month", "split_flat"):
        print(f"{c}: better than current on {(has[c] < has.current).sum()} of {len(has)}; "
              f"median rel MAE {has.current.median():.3f} -> {has[c].median():.3f}")
