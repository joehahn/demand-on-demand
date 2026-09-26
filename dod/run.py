"""Run one forecast request end to end.

    python -m dod.run specs/titos_polk.json [more specs...]

Writes out/<slug>/: dashboard.html, forecast.csv, backtest.csv, summary.json."""
import json
import sys
import time
from pathlib import Path

from . import checks, dashboard, model, panel, register
from .spec import load

OUT = Path(__file__).parent.parent / "out"


def run(spec, out_root=OUT, usage=None, log=print):
    t0 = time.time()
    log(f"== {spec.title}")
    decisions = register.assess(spec, register.load())
    p = panel.build(spec, decisions)
    log(f"  panel: {p.series.shape[1]} series x {p.series.shape[0]} months from {p.start}")
    findings = checks.run(spec, p)
    log(f"  slice checks: {len(findings)} finding(s), {sum(f['addressed'] for f in findings)} addressed by the spec")
    res = model.run(p.series, p.exog, p.future_index, spec.horizon, spec.features, log=log)
    out = out_root / spec.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard.html").write_text(dashboard.build(spec, p, decisions, findings, res, usage))
    res["forecast"].assign(label=res["forecast"].series.map(p.labels)).to_csv(out / "forecast.csv", index=False)
    res["backtest"].to_csv(out / "backtest.csv", index=False)
    summary = {"title": spec.title, "spec": spec.model_dump(), "best": res["best"],
               "feature_groups": res["feature_groups"], "test_rel_mae": res["test_rel_mae"],
               "per_step": res["per_step"].to_dict("records"), "findings": findings, "register": decisions,
               "forecast_total": float(res["forecast"].pred.sum()), "seconds": round(time.time() - t0, 1)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log(f"  wrote {out}/dashboard.html in {time.time() - t0:.0f}s")
    return summary


if __name__ == "__main__":
    for path in sys.argv[1:]:
        run(load(path))
