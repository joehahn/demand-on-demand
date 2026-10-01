"""Experiment: a finer hyperparameter grid. Runs the benchmark's 30 forecasts (seed 0) with the current grid and with
a finer one (6 ridge regularization strengths, 6 LightGBM leaf counts: 288 configurations instead of 96), and
compares accuracy against "same month last year" and harness time. No LLM calls.

    python benchmark/grid_experiment.py
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import model, run  # noqa: E402
from run_benchmark import sample_specs  # noqa: E402

HERE = Path(__file__).parent
GRIDS = {"current": dict(model.FAMILY),
         "finer": {"lightgbm": {"num_leaves": [4, 7, 11, 15, 23, 31]}, "ridge": {"alpha": [0.1, 0.3, 1.0, 3.0, 10.0, 30.0]}}}

rows = []
for spec in sample_specs(30):
    row = {"forecast": spec.title}
    for name, family in GRIDS.items():
        model.FAMILY = family   # configs() reads the module's grid when it runs
        t0 = time.time()
        try:
            s = run.run(spec, out_root=HERE / "out" / f"grid_{name}", log=lambda *a: None)
            row[f"{name}_rel"], row[f"{name}_s"] = s["test_rel_mae"], time.time() - t0
        except Exception as e:  # too little history etc.
            row[f"{name}_rel"], row[f"{name}_s"] = None, None
    rows.append(row)
    print(f"  {row.get('current_rel') or float('nan'):.3f} -> {row.get('finer_rel') or float('nan'):.3f}  "
          f"{row.get('current_s') or 0:.0f}s -> {row.get('finer_s') or 0:.0f}s  {spec.title}", flush=True)

df = pd.DataFrame(rows).dropna()
df.to_csv(HERE / "grid_experiment.csv", index=False)
md = ["# Experiment: a finer hyperparameter grid\n",
      "Ridge regularization 0.1, 0.3, 1, 3, 10, 30 and LightGBM 4, 7, 11, 15, 23, 31 leaves (288 configurations) against the",
      "current 1 or 10 and 7 or 15 leaves (96), on the benchmark's 30 forecasts. Error relative to same month last year",
      "on the 24-month test window (below 1 beats it).\n",
      f"- Beat last year: current **{(df.current_rel < 1).sum()} of {len(df)}**, finer **{(df.finer_rel < 1).sum()} of {len(df)}**",
      f"- Median relative error: current **{df.current_rel.median():.3f}**, finer **{df.finer_rel.median():.3f}**",
      f"- Finer grid better on {(df.finer_rel < df.current_rel - 1e-9).sum()}, worse on {(df.finer_rel > df.current_rel + 1e-9).sum()}",
      f"- Median harness time: current {df.current_s.median():.0f} s, finer {df.finer_s.median():.0f} s\n",
      "| forecast | current | finer | current s | finer s |", "|---|---|---|---|---|"]
md += [f"| {r.forecast} | {r.current_rel:.3f} | {r.finer_rel:.3f} | {r.current_s:.0f} | {r.finer_s:.0f} |" for r in df.itertuples()]
(HERE / "grid_experiment.md").write_text("\n".join(md) + "\n")
print("\n".join(md[4:9]))
