"""Experiment: one input menu for every forecast, instead of one per grain.

    python benchmark/menu_experiment.py            # the benchmark's 30 forecasts, monthly and weekly (about 90 minutes)
    python benchmark/menu_experiment.py --n 2      # a quick smoke test

Arms, each offered to model selection group by group (a group is kept only if it helps), at both grains:
  A  today's menus: months get calendar (month number, business days, holiday count) and population; weeks get time
     of year (sine and cosine), four holiday flags and active stores
  B  one menu for every grain: time of year (sine and cosine), calendar (business days and the four holiday flags:
     Thanksgiving, Christmas, New Year's Day and July 4th fall in the period), population, active stores
  C  as B, but LightGBM sees the month number instead of sine and cosine (ridge keeps sine and cosine)
Each forecast runs through the same fixed code as the dashboards (dod/history.py, dod/model.py: tuned on the Tuning
period, scored on the Testing period). Weekly forecasts look the same span ahead in weeks (capped at 52). Scored as
error relative to the same period last year on the Testing period. No AI calls. Writes benchmark/menu.csv and
benchmark/menu.md.
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import db, features, history, model, panel  # noqa: E402
from run_benchmark import sample_specs  # noqa: E402

HERE = Path(__file__).parent
FLAGS = list(features.HOLIDAYS)   # thanksgiving_week, christmas_week, new_year_week, july4_week
GROUPS_B = {"season": ["season_sin", "season_cos"], "holidays": ["business_days"] + FLAGS,
            "population": ["population"], "stores": ["active_stores"]}
MENU_A = {"month": ["calendar", "population"], "week": ["season", "holiday_weeks", "stores"]}


def holiday_flags(index, grain):
    """1 if the holiday (its actual day, not the observed day off) falls in the period, at any grain."""
    cal = db.query("SELECT cal_date, holiday_name FROM ref.calendar WHERE holiday_name IS NOT NULL")
    day = pd.to_datetime(cal.cal_date)
    cal["period"] = (day - pd.to_timedelta(day.dt.weekday, unit="D")) if grain == "week" else day.dt.to_period(
        "M").dt.start_time
    out = pd.DataFrame(0.0, index=index, columns=FLAGS)
    for col, name in features.HOLIDAYS.items():
        periods = set(cal[cal.holiday_name == name].period)
        out[col] = [1.0 if p in periods else 0.0 for p in index]
    return out


def case(spec, grain):
    """The three arms for one forecast at one grain: (test error vs last year, groups kept) per arm."""
    steps = spec.horizon if grain == "month" else min(spec.horizon * 4, 52)
    sql = panel.reference_sql(spec)
    p, _ = history.build(sql, grain, steps)   # the series, as every forecast builds it
    idx = p.series.index.append(p.future_index)
    end, last_month = panel.data_end()
    months = history.monthly_rows(sql)
    months["month"] = pd.to_datetime(months.month)
    sold = months[(months.month <= last_month) & (months.value > 0)]
    step = pd.tseries.frequencies.to_offset(history.FREQ[grain])
    freq = "W-MON" if grain == "week" else "MS"
    common = (features.season(pd.DatetimeIndex(idx, freq=freq)).join(features.calendar(idx, grain))
              .join(holiday_flags(idx, grain)))
    common["active_stores"] = features.stores(sold, idx, steps * step).values
    pops = features.population(sold, idx)
    exog = {c: common.join(pops[c]) if c in pops else common.assign(population=float("nan")) for c in p.series}
    out = {}
    saved = dict(model.FEATURE_GROUPS)
    with model.use_grain(grain):
        for arm in ("A", "B", "C"):
            model.FEATURE_GROUPS.clear()
            model.FEATURE_GROUPS.update(saved if arm == "A" else GROUPS_B)
            groups = MENU_A[grain] if arm == "A" else list(GROUPS_B)
            model.LGBM_MONTH = arm == "C"
            try:
                res = model.run(p.series, exog, p.future_index, steps, groups, log=lambda *a: None)
                out[arm] = (res["test_rel_mae"], ",".join(res["tested"]["feature_groups"]) or "none")
            finally:
                model.LGBM_MONTH = False
                model.FEATURE_GROUPS.clear()
                model.FEATURE_GROUPS.update(saved)
    return out


def summary(df, grain):
    cols = [f"{grain}_{a}" for a in "ABC"]
    ok = df.dropna(subset=cols)
    lines = [f"**{grain}ly** ({len(ok)} forecasts)\n", "| arm | beat last year | median | mean |", "|---|---|---|---|"]
    lines += [f"| {c[-1]} | {(ok[c] < 1).sum()} | {ok[c].median():.3f} | {ok[c].mean():.3f} |" for c in cols]
    for a in "BC":
        b, c = ok[f"{grain}_A"], ok[f"{grain}_{a}"]
        lines.append(f"\n{a} vs A: better on {(c < b - 1e-9).sum()}, worse on {(c > b + 1e-9).sum()}, same on "
                     f"{(abs(c - b) <= 1e-9).sum()}.")
    return lines + [""]


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    rows = []
    for spec in sample_specs(n):
        t0, row = time.time(), {"forecast": spec.title}
        for grain in ("month", "week"):
            try:
                for arm, (rel, kept) in case(spec, grain).items():
                    row[f"{grain}_{arm}"], row[f"{grain}_{arm}_kept"] = rel, kept
            except Exception as e:   # too little history etc. is a result, not a crash
                row[f"{grain}_error"] = str(e)[:120]
        rows.append(row)
        print(f"  {time.time() - t0:4.0f}s  month " + " ".join(f"{row.get(f'month_{a}', float('nan')):.3f}" for a in "ABC")
              + "  week " + " ".join(f"{row.get(f'week_{a}', float('nan')):.3f}" for a in "ABC") + f"  {spec.title}",
              flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "menu.csv", index=False)
    md = ["# Experiment: one input menu for every forecast\n",
          "Error relative to the same period last year on the Testing period (below 1 beats it). A = today's menus "
          "(months: calendar with month number, population; weeks: sine and cosine, holiday flags, active stores); "
          "B = one menu (sine and cosine, business days and holiday flags, population, active stores); C = B, but "
          "LightGBM sees the month number.\n"]
    md += summary(df, "month") + summary(df, "week")
    md += ["| forecast | month A | month B | month C | week A | week B | week C |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['forecast']} | " + " | ".join(f"{r.get(f'{g}_{a}', float('nan')):.3f}" for g in ("month", "week")
                                               for a in "ABC") + " |" for _, r in df.iterrows()]
    (HERE / "menu.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[2:]))
