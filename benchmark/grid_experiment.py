"""Experiment: other hyperparameter grids. Runs the benchmark's 30 forecasts (seed 0) with the current grid and with
a candidate (finer: 6 ridge strengths x 6 leaf counts, 288 configurations; middle: 4 x 4, 192), and
compares accuracy against "same month last year" and harness time. No LLM calls.

    python benchmark/grid_experiment.py [finer|middle]     # default: finer

The current grid's results are reused from grid_experiment.csv when it exists (same forecasts, same data).
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import model  # noqa: E402
from run_benchmark import run_spec, sample_specs  # noqa: E402

HERE = Path(__file__).parent
CANDIDATES = {"finer": {"lightgbm": {"num_leaves": [4, 7, 11, 15, 23, 31]}, "ridge": {"alpha": [0.1, 0.3, 1.0, 3.0, 10.0, 30.0]}},
              "middle": {"lightgbm": {"num_leaves": [3, 7, 12, 17]}, "ridge": {"alpha": [0.1, 1.0, 5.0, 10.0]}}}
CAND = next((a for a in sys.argv[1:] if a in CANDIDATES), "finer")
SAVED = HERE / "grid_experiment.csv"
current = pd.read_csv(SAVED).set_index("forecast") if SAVED.exists() else None
GRIDS = ({} if current is not None else {"current": dict(model.FAMILY)}) | {CAND: CANDIDATES[CAND]}

rows = []
for spec in sample_specs(30):
    row = {"forecast": spec.title}
    if current is not None and spec.title in current.index:
        row["current_rel"], row["current_s"] = current.at[spec.title, "current_rel"], current.at[spec.title, "current_s"]
    for name, family in GRIDS.items():
        model.FAMILY = family   # configs() reads the module's grid when it runs
        t0 = time.time()
        try:
            s = run_spec(spec, HERE / "out" / f"grid_{name}")
            row[f"{name}_rel"], row[f"{name}_s"] = s["test_rel_mae"], time.time() - t0
        except Exception as e:  # too little history etc.
            row[f"{name}_rel"], row[f"{name}_s"] = None, None
    rows.append(row)
    print(f"  {row.get('current_rel') or float('nan'):.3f} -> {row.get(f'{CAND}_rel') or float('nan'):.3f}  "
          f"{row.get('current_s') or 0:.0f}s -> {row.get(f'{CAND}_s') or 0:.0f}s  {spec.title}", flush=True)

df = pd.DataFrame(rows).dropna()
df.to_csv(HERE / f"grid_experiment{'' if CAND == 'finer' else '_' + CAND}.csv", index=False)
grid = CANDIDATES[CAND]
c, r = df["current_rel"], df[f"{CAND}_rel"]
md = [f"# Experiment: a {CAND} hyperparameter grid\n",
      f"Ridge regularization {', '.join(f'{a:g}' for a in grid['ridge']['alpha'])} and LightGBM "
      f"{', '.join(map(str, grid['lightgbm']['num_leaves']))} leaves, against the current 1 or 10 and 7 or 15 leaves, on the",
      "benchmark's 30 forecasts. Error relative to same month last year on the 24-month test window (below 1 beats it).\n",
      f"- Beat last year: current **{(c < 1).sum()} of {len(df)}**, {CAND} **{(r < 1).sum()} of {len(df)}**",
      f"- Median relative error: current **{c.median():.3f}**, {CAND} **{r.median():.3f}**",
      f"- {CAND.title()} grid better on {(r < c - 1e-9).sum()}, worse on {(r > c + 1e-9).sum()}",
      f"- Median harness time: current {df.current_s.median():.0f} s, {CAND} {df[f'{CAND}_s'].median():.0f} s\n",
      f"| forecast | current | {CAND} | current s | {CAND} s |", "|---|---|---|---|---|"]
md += [f"| {f} | {a:.3f} | {b:.3f} | {x:.0f} | {y:.0f} |"
       for f, a, b, x, y in zip(df.forecast, c, r, df.current_s, df[f"{CAND}_s"])]
(HERE / f"grid_experiment{'' if CAND == 'finer' else '_' + CAND}.md").write_text("\n".join(md) + "\n")
print("\n".join(md[3:7]))
