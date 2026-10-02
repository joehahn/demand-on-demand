"""Training, tuning and honest evaluation. The harness owns every cutoff: the model never sees a month
it is scored on, and hyperparameters are chosen on data before the test window.

Pooling: a model may also train on companion series (the same product in other counties) to learn shared
seasonality from more data; it still predicts and is scored on the requested series only. Whether pooling
helps is decided by the grid search, like every other choice.

    |<------------- tuning window ------------->|<------ test window (last 24 months) ------>|
      grid search validates on its last 24 months   rolling-origin backtest, refit at each origin
"""
import contextlib
import itertools
import os
import time
import warnings

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from lightgbm import LGBMRegressor
from skforecast.preprocessing import RollingFeatures
from skforecast.recursive import ForecasterRecursiveMultiSeries
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

TEST_MONTHS = 24
TOP_K = (1, 3)                              # candidate ensemble sizes: the single best, or the top 3 averaged
BLEND_WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]  # share of the ensemble vs "same month last year"
TUNE_MONTHS = 24
MIN_TRAIN = 36     # months the longest series needs before the tuning window
MIN_SERIES = 24    # months any one series needs to join the pooled model (lag 12 plus a year of rows)
# Two model families. Trees capture interactions but cannot extrapolate a level they have not seen;
# ridge regression on lagged values can, and behaves like a tuned seasonal autoregression.
# target: "level" models the monthly value, "diff" its month-to-month change, "yoy" the log change from
# the same month last year. A shrunk "yoy" model falls back to the seasonal-naive forecast when it finds
# no signal, so it can only improve on the baseline by learning something real.
COMMON = {"target": ["level", "diff", "yoy"], "lags": [12, [1, 2, 3, 12]], "train_years": [None, 5]}
N_JOBS = int(os.environ.get("DOD_JOBS", os.cpu_count() or 4))
FAMILY = {
    "lightgbm": {"num_leaves": [7, 15]},
    "ridge": {"alpha": [1.0, 10.0]},
}


# Time grain. Everything above is for months, the default; use_grain switches the harness to weeks or quarters for
# the on-the-fly path (dod/onthefly.py). SEASON is the number of periods in a year: the baseline is the same period
# SEASON periods back, lags reach back one season, and the selection and test windows are two seasons long.
GRAIN, SEASON, FREQ, ORIGIN_STRIDE = "month", 12, "MS", 1
GRAINS = {"month": dict(season=12, freq="MS", stride=1),
          "quarter": dict(season=4, freq="QS", stride=1),
          "week": dict(season=52, freq="W-MON", stride=4)}   # weekly: refit every 4 weeks, or backtests take minutes


@contextlib.contextmanager
def use_grain(name):
    """Run the harness at another grain inside a with-block; the monthly defaults come back afterward."""
    global GRAIN, SEASON, FREQ, ORIGIN_STRIDE, TEST_MONTHS, TUNE_MONTHS, MIN_TRAIN, MIN_SERIES, COMMON
    saved = (GRAIN, SEASON, FREQ, ORIGIN_STRIDE, TEST_MONTHS, TUNE_MONTHS, MIN_TRAIN, MIN_SERIES, COMMON)
    g = GRAINS[name]
    GRAIN, SEASON, FREQ, ORIGIN_STRIDE = name, g["season"], g["freq"], g["stride"]
    TEST_MONTHS = TUNE_MONTHS = MIN_SERIES = 2 * SEASON
    MIN_TRAIN = 3 * SEASON
    COMMON = {**COMMON, "lags": [SEASON, [1, 2, 3, SEASON]]}
    try:
        yield
    finally:
        GRAIN, SEASON, FREQ, ORIGIN_STRIDE, TEST_MONTHS, TUNE_MONTHS, MIN_TRAIN, MIN_SERIES, COMMON = saved


def in_grain(grain, fn, *args):
    """Run fn at a grain. Parallel jobs run in fresh worker processes, which start at the monthly defaults, so each
    job is told the grain explicitly."""
    with use_grain(grain):
        return fn(*args)


# Input groups model selection can try, and their columns in the exog frames. A group is kept only if the model does
# better with it on the model-selection window. Monthly forecasts are offered "calendar" and "population"; weekly ones
# "season", "holiday_weeks" and "stores" (dod/features.py; adopted after benchmark/feature_experiment.py).
FEATURE_GROUPS = {"calendar": ["month_of_year", "business_days", "holidays"], "population": ["population"],
                  "season": ["season_sin", "season_cos"],
                  "holiday_weeks": ["thanksgiving_week", "christmas_week", "new_year_week", "july4_week"],
                  "stores": ["active_stores"]}


class TooLittleData(ValueError):
    pass


# Keep an input group only if the model's error without it is at least this much higher on the model-selection window
# (benchmark/margin_experiment.py). Tested 2% and 5%: both worse on average (weekly median 0.826 -> 0.849 and 0.854),
# so any win on that window keeps the group. Kept as a setting for the experiment.
KEEP_MARGIN = 0.0

ROLLING = False   # under test (benchmark/rolling_experiment.py): also give every model its recent averages


def configs(pool_options=(False,)):
    out = []
    for family, grid in FAMILY.items():
        g = {**COMMON, "pool": list(pool_options), **grid}
        out += [{"model": family, **dict(zip(g, vals))} for vals in itertools.product(*g.values())]
    if ROLLING:   # carried inside each configuration, so parallel workers see it too
        out = [{**c, "rolling": True} for c in out]
    return out


def make_forecaster(cfg):
    yoy_target = cfg["target"] == "yoy"
    if cfg["model"] == "ridge":
        # for a change target, no intercept and no centering: heavy shrinkage then means "no change
        # from last year" (the seasonal-naive forecast), not "the average historical growth rate"
        est = Ridge(alpha=cfg["alpha"], fit_intercept=not yoy_target)
    else:
        est = LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=cfg["num_leaves"],
                            min_child_samples=5, random_state=0, verbose=-1, n_jobs=1)
    # recent averages (last 4 and 13 periods), computed by the forecaster itself step by step, so a forecast
    # never sees future values
    window = RollingFeatures(stats=["mean", "mean"], window_sizes=[4, 13]) if cfg.get("rolling") else None
    return ForecasterRecursiveMultiSeries(estimator=est, lags=cfg["lags"], encoding="ordinal", window_features=window,
                                          transformer_series=None if yoy_target else StandardScaler(),
                                          transformer_exog=StandardScaler(),
                                          differentiation=1 if cfg["target"] == "diff" else None)


def _train_dict(wide, end, years=None):
    """Series up to (not including) `end`, optionally only the last `years`, trimmed of leading NaNs."""
    out = {}
    first = end - pd.DateOffset(years=years) if years else wide.index[0]
    for c in wide:
        s = wide.loc[(wide.index < end) & (wide.index >= first), c].dropna()
        if len(s) >= MIN_SERIES:
            out[c] = s.asfreq(FREQ)
    return out


def fit_predict(cfg, wide, exog, end, steps, features, pool=None):
    """Fit on everything before `end` (plus companion series if the config pools), forecast the requested
    series `steps` months from `end`. `pool` is (companion DataFrame, companion exog dict)."""
    if cfg["model"] == "seasonal_naive":
        # horizon <= SEASON, so "same period last year" is always a period before `end`
        rows = [{"month": m, "series": c, "pred": seasonal_naive(wide, m, c)}
                for c in wide for m in pd.date_range(end, periods=steps, freq=FREQ)]
        pred = pd.DataFrame(rows)
        pred["step"] = pred.groupby("series").cumcount() + 1
        return pred
    frame = wide
    if cfg.get("pool") and pool is not None:
        frame = pd.concat([wide, pool[0]], axis=1)
        exog = {**exog, **pool[1]}
    source = yoy(frame) if cfg["target"] == "yoy" else frame
    train = _train_dict(source, end, cfg.get("train_years"))
    targets = [c for c in wide if c in train]
    if not targets:
        return pd.DataFrame()
    future = pd.date_range(end, periods=steps, freq=FREQ)
    if cfg["target"] == "yoy" and features:  # a change target gets change features: vs the same month last year
        features = [f for f in features if f != "month_of_year"]  # seasonality is already differenced out
        exog = {c: yoy_exog(exog[c][features]) for c in train}
    ex_train = {c: exog[c].loc[train[c].index, features] for c in train} if features else None
    ex_future = {c: exog[c].loc[future, features] for c in targets} if features else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # e.g. "unscaled series with a linear model": yoy log changes share a scale
        f = make_forecaster(cfg)
        f.fit(series=train, exog=ex_train)
        pred = f.predict(steps=steps, levels=targets, exog=ex_future, suppress_warnings=True)
    pred = pred.reset_index().rename(columns={"index": "month", "level": "series", "pred": "pred"})
    if cfg["target"] == "yoy":  # back to units: last year's value times the predicted change
        last_year = [seasonal_naive(wide, m, c) for m, c in zip(pred.month, pred.series)]
        pred["pred"] = np.expm1(pred.pred + np.log1p(last_year))
    pred["step"] = pred.groupby("series").cumcount() + 1
    return pred


def yoy_exog(ex):
    """Features as changes from the same month last year (month_of_year stays as is)."""
    out = ex - ex.shift(SEASON)
    if "population" in ex:
        out["population"] = np.log(ex.population) - np.log(ex.population.shift(SEASON))
    return out


def yoy(wide):
    """Log change from the same month last year."""
    return np.log1p(wide.clip(lower=0)) - np.log1p(wide.clip(lower=0)).shift(SEASON)


def seasonal_naive(wide, month, series):
    """Same period last year (same month, week or quarter): the baseline every model must beat."""
    prev = month - SEASON * pd.tseries.frequencies.to_offset(FREQ)
    return wide.at[prev, series] if prev in wide.index else np.nan


def score(bt):
    """Relative MAE: model error divided by seasonal-naive error on the same months (below 1 = better)."""
    ok = bt.dropna(subset=["actual", "pred", "naive"])
    naive = (ok.actual - ok.naive).abs().sum()
    return (ok.actual - ok.pred).abs().sum() / naive if naive else np.nan


def backtest(cfg, wide, exog, origins, steps, features, pool=None, n_jobs=1):
    """Forecast from each origin and record it next to what actually happened and the seasonal-naive baseline."""
    preds = Parallel(n_jobs=n_jobs)(delayed(in_grain)(GRAIN, fit_predict, cfg, wide, exog, o, steps, features, pool)
                                    for o in origins) \
        if n_jobs != 1 else [fit_predict(cfg, wide, exog, o, steps, features, pool) for o in origins]
    rows = []
    for origin, pred in zip(origins, preds):
        for r in pred.itertuples():
            if r.month in wide.index:
                rows.append({"origin": origin, "month": r.month, "step": r.step, "series": r.series,
                             "pred": max(r.pred, 0.0), "actual": wide.at[r.month, r.series],
                             "naive": seasonal_naive(wide, r.month, r.series)})
    return pd.DataFrame(rows)


def windows(wide, steps):
    n = len(wide)
    test = TEST_MONTHS if n >= MIN_TRAIN + TUNE_MONTHS + TEST_MONTHS else SEASON
    if n < MIN_TRAIN + TUNE_MONTHS + test:
        raise TooLittleData(f"Only {n} months of history; need at least {MIN_TRAIN + TUNE_MONTHS + test} "
                            "to tune and backtest honestly.")
    idx = wide.index
    test_origins = list(idx[n - test: n - steps + 1])[::ORIGIN_STRIDE]   # every period whose full horizon is observed
    tune_origins = list(idx[n - test - TUNE_MONTHS: n - test - steps + 1])[::ORIGIN_STRIDE]  # before the test window
    return tune_origins, test_origins


def per_step(bt):
    rows = []
    for step, g in bt.groupby("step"):
        ok = g.dropna(subset=["actual", "pred", "naive"])
        mae, mae_naive = (ok.actual - ok.pred).abs().mean(), (ok.actual - ok.naive).abs().mean()
        wape = (ok.actual - ok.pred).abs().sum() / ok.actual.abs().sum()
        wape_naive = (ok.actual - ok.naive).abs().sum() / ok.actual.abs().sum()
        skill = 1 - mae / mae_naive if mae_naive else np.nan
        label = "beats baseline" if skill > 0.05 else ("on par with baseline" if skill > -0.05 else "worse than baseline")
        rows.append({"step": int(step), "folds": len(ok), "mae": mae, "mae_naive": mae_naive, "wape": wape,
                     "wape_naive": wape_naive,
                     "skill_vs_naive": skill, "reliability": label})
    return pd.DataFrame(rows)


def ensemble_backtest(cfgs, wide, exog, origins, steps, features, pool, weight):
    """Average the configurations' forecasts, then blend with the seasonal-naive forecast: weight 1 = all model."""
    bts = [backtest(c, wide, exog, origins, steps, features, pool, N_JOBS) for c in cfgs]
    bt = bts[0].copy()
    bt["pred"] = np.mean([b.pred.to_numpy() for b in bts], axis=0)
    bt["pred"] = weight * bt.pred + (1 - weight) * bt.naive.fillna(bt.pred)
    return bt


def ensemble_forecast(cfgs, wide, exog, end, steps, features, pool, weight):
    fcs = [fit_predict(c, wide, exog, end, steps, features, pool) for c in cfgs]
    fc = fcs[0].copy()
    fc["pred"] = np.mean([f.pred.to_numpy() for f in fcs], axis=0)
    naive = [seasonal_naive(wide, m, c) for m, c in zip(fc.month, fc.series)]
    fc["pred"] = weight * fc.pred + (1 - weight) * pd.Series(naive, index=fc.index).fillna(fc.pred)
    return fc


def _grid_score(cfg, wide, exog, origins, steps, features, pool):
    return score(backtest(cfg, wide, exog, origins, steps, features, pool))


def run(wide, exog, future_index, steps, feature_groups, log=print, pool=None):
    t0 = time.time()
    tune_origins, test_origins = windows(wide, steps)
    cols = FEATURE_GROUPS
    features = [c for g in feature_groups for c in cols[g]]

    # 1. grid search on the tuning window only, configurations in parallel
    cands = configs((False, True) if pool is not None and len(pool[0].columns) else (False,))
    scores = Parallel(n_jobs=N_JOBS)(delayed(in_grain)(GRAIN, _grid_score, cfg, wide, exog, tune_origins, steps,
                                                       features, pool)
                                     for cfg in cands)
    grid = [{**{k: str(v) for k, v in cfg.items()}, "rel_mae": sc, "_cfg": cfg} for cfg, sc in zip(cands, scores)]
    grid.append({"model": "seasonal_naive", "rel_mae": 1.0, "_cfg": {"model": "seasonal_naive"}})
    grid = pd.DataFrame(grid).sort_values("rel_mae", kind="stable").reset_index(drop=True)
    best = grid.iloc[0]["_cfg"]  # the baseline wins ties: a model must beat it to be used
    log(f"  grid search: {len(grid) - 1} configs in {time.time() - t0:.0f}s, chose {best['model']}"
        f"{' pooled' if best.get('pool') else ''} (tuning rel MAE {grid.rel_mae.iloc[0]:.3f})")

    # 2. feature selection, also on the tuning window: drop a feature group unless the model is clearly better with it
    #    (its error without the group must be at least KEEP_MARGIN higher); otherwise the simpler model wins
    chosen_groups, selection = list(feature_groups), []
    if best["model"] != "seasonal_naive":
        base = score(backtest(best, wide, exog, tune_origins, steps, features, pool, N_JOBS))
        for g in feature_groups:
            trial = [c for c in features if c not in cols[g]]
            trial_score = score(backtest(best, wide, exog, tune_origins, steps, trial, pool, N_JOBS))
            selection.append({"group": g, "with": base, "without": trial_score})
            if trial_score < base * (1 + KEEP_MARGIN):
                chosen_groups.remove(g)
                features, base = trial, trial_score
                log(f"  dropped feature group '{g}': tuning rel MAE {trial_score:.3f} without it")

    # 3. ensemble of the top configurations and its blend with the baseline, both chosen on the tuning window
    ranked = [c for c in grid._cfg if c["model"] != "seasonal_naive"]
    weight, blend, top = 0.0, [], []
    if best["model"] != "seasonal_naive":
        for k in TOP_K:
            tune_bt = ensemble_backtest(ranked[:k], wide, exog, tune_origins, steps, features, pool, 1.0)
            for w in BLEND_WEIGHTS:
                b = tune_bt.copy()
                b["pred"] = w * b.pred + (1 - w) * b.naive.fillna(b.pred)
                blend.append({"models_averaged": k, "model_share": w, "tuning_rel_mae": score(b)})
        # ties go to fewer models and more model share: the simplest choice that is as good
        pick = min(blend, key=lambda r: (round(r["tuning_rel_mae"], 6), r["models_averaged"], -r["model_share"]))
        top, weight = ranked[:pick["models_averaged"]], pick["model_share"]
        log(f"  {len(top)} model(s) averaged, blended {weight:.0%} model / {1 - weight:.0%} last year "
            f"(tuning rel MAE {pick['tuning_rel_mae']:.3f})")

    # 4. honest test: rolling origin over the last months, refit at every origin
    if top:
        bt = ensemble_backtest(top, wide, exog, test_origins, steps, features, pool, weight)
    else:
        bt = backtest(best, wide, exog, test_origins, steps, features, pool, N_JOBS)
    steps_table = per_step(bt)
    log(f"  backtest: {len(test_origins)} origins, test rel MAE {score(bt):.3f}")

    # 5. report only: each input group's effect in the Test period (selection above never saw these months), scored
    #    exactly like the final forecast (same models, same blend with last year), so the numbers compare directly
    def test_score(feats):
        if top:
            return score(ensemble_backtest(top, wide, exog, test_origins, steps, feats, pool, weight))
        return score(backtest(best, wide, exog, test_origins, steps, feats, pool, N_JOBS))
    ablation = [{"features": "chosen: " + (", ".join(chosen_groups) or "none"), "rel_mae": score(bt)}]
    effects = []
    for g in (feature_groups if best["model"] != "seasonal_naive" else []):
        if g in chosen_groups:
            other = test_score([c for c in features if c not in cols[g]])
            ablation.append({"features": f"without {g}", "rel_mae": other})
            with_g, without_g = score(bt), other
        else:
            other = test_score(features + cols[g])
            ablation.append({"features": f"with {g} added back", "rel_mae": other})
            with_g, without_g = other, score(bt)
        sel = next(s for s in selection if s["group"] == g)
        # how much the group helps: the error without it, relative to the error with it (positive = it helps)
        effects.append({"group": g, "kept": g in chosen_groups,
                        "selection": sel["without"] / sel["with"] - 1, "test": without_g / with_g - 1})
    ablation.append({"features": "seasonal naive baseline", "rel_mae": 1.0})

    # 6. final forecast on all history; intervals from the backtest's relative errors at each step
    fc = ensemble_forecast(top, wide, exog, future_index[0], steps, features, pool, weight) if top else \
        fit_predict(best, wide, exog, future_index[0], steps, features, pool)
    skipped = {c: f"only {int(wide[c].notna().sum())} months of history; at least {MIN_SERIES} are needed"
               for c in wide if c not in set(fc.series)}
    if skipped:
        log(f"  not forecast (too little history): {', '.join(skipped)}")
    unvalidated = sorted(set(fc.series) - set(bt.series)) if len(bt) else sorted(set(fc.series))
    if unvalidated:
        log(f"  forecast but never backtested (too young during the test window): {', '.join(unvalidated)}")
    ok = bt.dropna(subset=["actual", "pred"])
    ok = ok[ok.pred > 0]
    rel = ((ok.actual - ok.pred) / ok.pred).groupby(ok.step)
    lo, hi = rel.quantile(0.1), rel.quantile(0.9)
    fc["pred"] = fc.pred.clip(lower=0)
    fc["lo"] = (fc.pred * (1 + fc.step.map(lo))).clip(lower=0)
    fc["hi"] = fc.pred * (1 + fc.step.map(hi))
    log(f"  done in {time.time() - t0:.0f}s")
    return {"best": best, "grid": grid.drop(columns="_cfg"), "backtest": bt, "per_step": steps_table,
            "test_rel_mae": score(bt), "ablation": pd.DataFrame(ablation), "effects": pd.DataFrame(effects), "forecast": fc,
            "test_window": (test_origins[0], wide.index[-1]), "features": features, "feature_groups": chosen_groups,
            "skipped": skipped, "unvalidated": unvalidated, "pooled": bool(best.get("pool")),
            "ensemble": top, "model_share": weight, "blend": pd.DataFrame(blend),
            "companions": list(pool[0].columns) if pool is not None and best.get("pool") else [],
            "tune_window": (tune_origins[0], test_origins[0] - pd.offsets.MonthBegin(1))}
