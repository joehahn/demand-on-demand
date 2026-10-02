"""Experiment: keep an input group only if it clearly helps on the model-selection window (model.KEEP_MARGIN).

    python benchmark/margin_experiment.py            # the benchmark's 30 forecasts, monthly and weekly (about an hour)
    python benchmark/margin_experiment.py --n 3      # a quick smoke test

Today a group is kept if the model's error without it is higher at all, even by 0.1%. Small wins on the
model-selection window are often noise the Test period does not repeat (the weekly cream liqueur forecast kept season,
holiday weeks and active stores, and each one hurt in the Test period). With a margin m, a group is kept only if the
error without it is at least m higher; otherwise the simpler model wins.

For each benchmark forecast (benchmark/run_benchmark.sample_specs, seed 0):
  weekly   no inputs; season + holiday weeks + stores offered with margin 0, 2% and 5%
  monthly  calendar + population offered (today's inputs) with margin 0 and 2%
Scored like the harness: error relative to the same period last year on the test window. No LLM calls. Writes
benchmark/margin.csv and benchmark/margin.md.
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import model, panel  # noqa: E402
from dod.onthefly import bucket  # noqa: E402
from feature_experiment import add_stores, holiday_weeks, region_rows, season, store_months  # noqa: E402
from run_benchmark import sample_specs  # noqa: E402

HERE = Path(__file__).parent
WEEK_GROUPS = ["season", "holiday_weeks", "stores"]
WEEK_RUNS = {"none": ([], 0.0), "m0": (WEEK_GROUPS, 0.0), "m2": (WEEK_GROUPS, 0.02), "m5": (WEEK_GROUPS, 0.05)}
MONTH_RUNS = {"m0": 0.0, "m2": 0.02}


def fit(wide, exog, future, steps, groups, margin, pool=None):
    """One harness run at a given margin; returns (test error vs last year, groups kept)."""
    model.KEEP_MARGIN = margin
    res = model.run(wide, exog, future, steps, groups, log=lambda *a: None, pool=pool)
    return res["test_rel_mae"], ",".join(res["feature_groups"]) or "none"


def weekly(spec, rows, end):
    """The same weekly series the feature experiment built, from the slot-filling SQL at daily grain."""
    sql, params = panel.build_sql(spec)
    from dod import db
    raw = db.query(sql.replace("date_trunc('month', l.ordered_on)::date AS month", "l.ordered_on AS day")
                   .replace("GROUP BY 1, 2, 3\nORDER BY 1, 2, 3", "GROUP BY 1, 2, 3"), params)
    wide = bucket(raw.groupby(["day", "series"], as_index=False).value.sum(), "week", end)
    steps = min(spec.horizon * 4, 52)
    fut = pd.date_range(wide.index[-1] + pd.offsets.Week(weekday=0), periods=steps, freq="W-MON")
    idx = wide.index.append(fut)
    feats = season(pd.DatetimeIndex(idx, freq="W-MON")).join(holiday_weeks(idx))
    exog = {c: add_stores(feats.copy(), idx, region_rows(rows, spec), wide.index[-1], "week") for c in wide}
    out = {}
    with model.use_grain("week"):
        for name, (groups, margin) in WEEK_RUNS.items():
            out[f"week_{name}"], out[f"week_{name}_kept"] = fit(wide, exog, fut, steps, groups, margin)
    return out


def monthly(spec):
    p = panel.build(spec)
    out = {}
    for name, margin in MONTH_RUNS.items():
        out[f"month_{name}"], out[f"month_{name}_kept"] = fit(p.series, p.exog, p.future_index, spec.horizon,
                                                              list(spec.features), margin, p.pool)
    return out


def summary(df, cols, label):
    lines = [f"**{label}** ({len(df)} forecasts)\n", "| run | beat last year | median | mean |", "|---|---|---|---|"]
    lines += [f"| {c} | {(df[c] < 1).sum()} | {df[c].median():.3f} | {df[c].mean():.3f} |" for c in cols]
    return lines + [""]


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    end, last_month = panel.data_end()
    results = []
    for spec in sample_specs(n):
        t0 = time.time()
        row = {"forecast": spec.title}
        try:
            row.update(weekly(spec, store_months(spec, last_month), end))
            row.update(monthly(spec))
        except Exception as e:   # too little history etc. is a result, not a crash
            row["error"] = str(e)[:120]
        results.append(row)
        print(f"  {time.time() - t0:4.0f}s  week " + " ".join(f"{row.get('week_' + k, float('nan')):.3f}" for k in WEEK_RUNS)
              + "  month " + " ".join(f"{row.get('month_' + k, float('nan')):.3f}" for k in MONTH_RUNS)
              + f"  {spec.title}", flush=True)
    df = pd.DataFrame(results)
    df.to_csv(HERE / "margin.csv", index=False)
    ok = df.dropna(subset=["week_none", "month_m0"])
    md = ["# Experiment: keep an input only if it clearly helps (model.KEEP_MARGIN)\n",
          "Error relative to the same period last year on the test window (below 1 beats it). Weekly: none = no inputs; "
          "m0, m2, m5 = season, holiday weeks and active stores offered, kept only if the error without them is at least "
          "0%, 2% or 5% higher on the model-selection window. Monthly: calendar and population offered.\n"]
    md += summary(ok, [f"week_{k}" for k in WEEK_RUNS], "weekly")
    md += summary(ok, [f"month_{k}" for k in MONTH_RUNS], "monthly")
    md += ["| forecast | " + " | ".join(f"week {k}" for k in WEEK_RUNS) + " | week m2 kept | "
           + " | ".join(f"month {k}" for k in MONTH_RUNS) + " | month m2 kept |",
           "|---" * (len(WEEK_RUNS) + len(MONTH_RUNS) + 3) + "|"]
    md += [f"| {r['forecast']} | " + " | ".join(f"{r[f'week_{k}']:.3f}" for k in WEEK_RUNS) + f" | {r['week_m2_kept']} | "
           + " | ".join(f"{r[f'month_{k}']:.3f}" for k in MONTH_RUNS) + f" | {r['month_m2_kept']} |"
           for _, r in ok.iterrows()]
    (HERE / "margin.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[2:2 + 14]))
