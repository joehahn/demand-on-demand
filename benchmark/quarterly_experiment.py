"""Experiment: quarterly forecasts, built from monthly forecasts (bottom-up, as today) or modelled on quarters directly.

    python benchmark/quarterly_experiment.py            # the benchmark's 30 forecasts (about 15 minutes)
    python benchmark/quarterly_experiment.py --n 2      # a quick smoke test

For each benchmark forecast (benchmark/run_benchmark.sample_specs, seed 0), the same request is forecast as quarters
two ways, each through the same fixed code as the dashboards (dod/history.py, dod/model.py: tuned on the Tuning period,
tested on the Testing period, same input menu):
  A  bottom-up: models learn from monthly sums, 12 months ahead; each quarter is the sum of its three months
  B  direct: models learn from quarterly sums, 4 quarters ahead
Both are scored on the same thing: the Testing period's forecasts made at the start of a quarter, for each of the next
4 quarters, against what sold, relative to the same quarter last year (below 1 beats it). Only quarter starts and
quarters that both arms forecast count. No AI calls. Writes benchmark/quarterly.csv and benchmark/quarterly.md.
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import history, model, panel  # noqa: E402
from run_benchmark import sample_specs  # noqa: E402

HERE = Path(__file__).parent


def quarterly_misses(bt, months_per_step):
    """Backtest rows -> one row per (origin, quarter ahead): forecast, actual and last year's same quarter, summed.
    Only origins at a quarter start; months_per_step is 3 for monthly models (3 steps make a quarter), 1 for quarterly."""
    bt = bt[pd.to_datetime(bt.origin).dt.month.isin([1, 4, 7, 10])].dropna(subset=["actual", "pred", "naive"])
    bt = bt.assign(ahead=(bt.step - 1) // months_per_step + 1)
    g = bt.groupby(["origin", "ahead"]).agg(pred=("pred", "sum"), actual=("actual", "sum"), naive=("naive", "sum"),
                                           n=("pred", "size"))
    return g[g.n == months_per_step].drop(columns="n")


def run(sql, grain, steps):
    p, groups = history.build(sql, grain, steps)
    with model.use_grain(grain):
        res = model.run(p.series, p.exog, p.future_index, steps, groups, log=lambda *a: None)
    return res["backtest"]


def case(spec):
    sql = panel.reference_sql(spec)
    a = quarterly_misses(run(sql, "month", 12), 3)
    b = quarterly_misses(run(sql, "quarter", 4), 1)
    both = a.index.intersection(b.index)   # the same origins and quarters ahead for both arms
    a, b = a.loc[both], b.loc[both]
    rel = lambda d: (d.actual - d.pred).abs().sum() / (d.actual - d.naive).abs().sum()
    return {"A": rel(a), "B": rel(b), "quarters": len(both)}


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    rows = []
    for spec in sample_specs(n):
        t0, row = time.time(), {"forecast": spec.title}
        try:
            row.update(case(spec))
        except Exception as e:   # too little history etc. is a result, not a crash
            row["error"] = str(e)[:120]
        rows.append(row)
        print(f"  {time.time() - t0:4.0f}s  A {row.get('A', float('nan')):.3f}  B {row.get('B', float('nan')):.3f}  "
              f"({row.get('quarters', 0)} quarters)  {spec.title}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "quarterly.csv", index=False)
    ok = df.dropna(subset=["A", "B"])
    md = ["# Experiment: quarterly forecasts, bottom-up from months vs modelled on quarters\n",
          "Error relative to the same quarter last year on the Testing period, over forecasts made at quarter starts for "
          "the next 4 quarters (below 1 beats it). A = bottom-up (monthly models, quarters are sums of months, as "
          "today); B = direct (models learn from quarterly sums).\n",
          f"**{len(ok)} forecasts**\n", "| arm | beat last year | median | mean |", "|---|---|---|---|"]
    md += [f"| {c} | {(ok[c] < 1).sum()} | {ok[c].median():.3f} | {ok[c].mean():.3f} |" for c in "AB"]
    md += ["", f"B vs A: better on {(ok.B < ok.A - 1e-9).sum()}, worse on {(ok.B > ok.A + 1e-9).sum()}.\n",
           "| forecast | A bottom-up | B direct | quarters scored |", "|---|---|---|---|"]
    md += [f"| {r.forecast} | {r.A:.3f} | {r.B:.3f} | {r.quarters} |" for r in ok.itertuples()]
    md += [f"| {r.forecast} | not run: {r.error} | | |" for r in df[df.A.isna()].itertuples()] if "error" in df else []
    (HERE / "quarterly.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[2:9]))
