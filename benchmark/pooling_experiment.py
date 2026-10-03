"""Experiment: what the slot-filling path's monthly extras are worth, before retiring that path.

    python benchmark/pooling_experiment.py            # the benchmark's 30 forecasts (about 30 minutes)
    python benchmark/pooling_experiment.py --n 3      # a quick smoke test

For each benchmark forecast (benchmark/run_benchmark.sample_specs, seed 0), monthly:
  A  today: calendar and population inputs offered, pooling with 15 companion counties offered (county forecasts)
  B  the same inputs, no pooling
  C  no inputs, no pooling (what the AI-written-SQL path has for monthly forecasts today)
Scored like the harness: error relative to the same month last year on the test window. No LLM calls. Writes
benchmark/pooling.csv and benchmark/pooling.md.
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import model, panel  # noqa: E402
from run_benchmark import sample_specs  # noqa: E402

HERE = Path(__file__).parent


def case(spec):
    p = panel.build(spec)
    quiet = lambda *a: None
    a = model.run(p.series, p.exog, p.future_index, spec.horizon, list(spec.features), log=quiet, pool=p.pool)
    b = model.run(p.series, p.exog, p.future_index, spec.horizon, list(spec.features), log=quiet)
    c = model.run(p.series, p.exog, p.future_index, spec.horizon, [], log=quiet)
    return {"A": a["test_rel_mae"], "B": b["test_rel_mae"], "C": c["test_rel_mae"],
            "pool_offered": p.pool is not None and len(p.pool[0].columns) > 0, "pooled": a["pooled"],
            "A_kept": ",".join(a["feature_groups"]) or "none"}


def line(df, col, label):
    return f"| {label} | {(df[col] < 1).sum()} | {df[col].median():.3f} | {df[col].mean():.3f} |"


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    rows = []
    for spec in sample_specs(n):
        t0 = time.time()
        row = {"forecast": spec.title}
        try:
            row.update(case(spec))
        except Exception as e:   # too little history etc. is a result, not a crash
            row["error"] = str(e)[:120]
        rows.append(row)
        print(f"  {time.time() - t0:4.0f}s  A {row.get('A', float('nan')):.3f}  B {row.get('B', float('nan')):.3f}  "
              f"C {row.get('C', float('nan')):.3f}  pooled={row.get('pooled')}  {spec.title}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "pooling.csv", index=False)
    ok = df.dropna(subset=["A", "B", "C"])
    offered = ok[ok.pool_offered]
    md = ["# Experiment: pooling and monthly inputs, before retiring slot filling\n",
          "Error relative to the same month last year on the test window (below 1 beats it). A = today (calendar and "
          "population inputs, pooling with 15 companion counties); B = inputs, no pooling; C = no inputs, no pooling.\n",
          f"**All {len(ok)} forecasts**\n", "| run | beat last year | median | mean |", "|---|---|---|---|",
          line(ok, "A", "A today"), line(ok, "B", "B no pooling"), line(ok, "C", "C no inputs, no pooling"), "",
          f"**The {len(offered)} forecasts where pooling was offered** (statewide ones pool with counties too); a pooled model was chosen "
          f"in {int(offered.pooled.sum())}\n", "| run | beat last year | median | mean |", "|---|---|---|---|",
          line(offered, "A", "A today"), line(offered, "B", "B no pooling"), "",
          f"B vs A: better on {(ok.B < ok.A - 1e-9).sum()}, worse on {(ok.B > ok.A + 1e-9).sum()}, same on "
          f"{(abs(ok.B - ok.A) <= 1e-9).sum()}. C vs B: better on {(ok.C < ok.B - 1e-9).sum()}, worse on "
          f"{(ok.C > ok.B + 1e-9).sum()}, same on {(abs(ok.C - ok.B) <= 1e-9).sum()}.\n",
          "| forecast | A | B | C | pooled | inputs kept (A) |", "|---|---|---|---|---|---|"]
    md += [f"| {r.forecast} | {r.A:.3f} | {r.B:.3f} | {r.C:.3f} | {'yes' if r.pooled else ''} | {r.A_kept} |"
           for r in ok.itertuples()]
    (HERE / "pooling.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[2:18]))
