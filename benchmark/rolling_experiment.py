"""Experiment: recent averages as model inputs (the average of the last 4 and 13 periods), on top of the inputs from
benchmark/feature_experiment.py (variant B). Same 30 forecasts, monthly and weekly; compares with features.csv.

    python benchmark/rolling_experiment.py [--n 3]

The forecaster computes the averages itself as it forecasts step by step, so they never use future values. Writes
benchmark/rolling.csv and benchmark/rolling.md. No LLM calls.
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import model, panel  # noqa: E402
import feature_experiment as fx  # noqa: E402
from run_benchmark import sample_specs  # noqa: E402

HERE = Path(__file__).parent
model.ROLLING = True   # every configuration also gets the recent averages

if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    end, last_month = panel.data_end()
    rows_out = []
    for spec in sample_specs(n):
        t0 = time.time()
        row = {"forecast": spec.title}
        try:
            rows = fx.store_months(spec, last_month)
            row["month_C"] = fx.monthly_case(spec, rows, last_month, only="B")["B"][0]
            row["week_C"] = fx.weekly_case(spec, rows, end, only="B")["B"][0]
        except Exception as e:
            row["error"] = str(e)[:120]
        rows_out.append(row)
        print(f"  {time.time() - t0:4.0f}s  month {row.get('month_C', float('nan')):.3f}  week {row.get('week_C', float('nan')):.3f}"
              f"  {spec.title}", flush=True)
    c = pd.DataFrame(rows_out)
    c.to_csv(HERE / "rolling.csv", index=False)
    ab = pd.read_csv(HERE / "features.csv")
    df = ab.merge(c, on="forecast").dropna(subset=["month_A", "month_B", "month_C", "week_A", "week_B", "week_C"])
    md = ["# Experiment: recent averages as inputs (on top of season, holiday weeks and active stores)\n",
          "A = today's inputs, B = A + season (+ holiday weeks, weekly) + active stores, C = B + recent averages (last 4 and",
          "13 periods). Error relative to the same period last year on the test window (below 1 beats it).\n"]
    for g in ("month", "week"):
        a, b, cc = df[f"{g}_A"], df[f"{g}_B"], df[f"{g}_C"]
        md.append(f"**{g}ly** ({len(df)} forecasts): beat last year A {(a < 1).sum()}, B {(b < 1).sum()}, C {(cc < 1).sum()}; "
                  f"median A {a.median():.3f}, B {b.median():.3f}, C {cc.median():.3f}.\n")
    md += ["| forecast | month A | month B | month C | week A | week B | week C |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r.forecast} | {r.month_A:.3f} | {r.month_B:.3f} | {r.month_C:.3f} | {r.week_A:.3f} | {r.week_B:.3f} | "
           f"{r.week_C:.3f} |" for r in df.itertuples()]
    (HERE / "rolling.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[3:5]))
