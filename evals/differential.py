"""Differential test: does AI-written SQL (NL2SQL, dod/nl2sql.py) produce the same monthly series as the slot-filling
path (dod/agent.py + the harness's fixed SQL), which serves as the reference?

    python evals/differential.py [--rules] [--only titos_polk,chicago]

--rules gives the NL2SQL agent explicit rules for this warehouse (dod/nl2sql.RULES); results then go to
evals/differential_rules.json, so the two configurations can be compared.

For every eval case the reference can answer, both agents get the same request. The reference agent fills in the
request form and the harness builds the series with fixed SQL; the NL2SQL agent writes the series query itself.
Both series go through the same zero-filling (dod/panel.to_wide) and are compared month by month. Writes
evals/differential.json (everything, including both queries) and evals/differential.md.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import agent, db, nl2sql, panel  # noqa: E402
from dod.spec import Spec  # noqa: E402

HERE = Path(__file__).parent


def norm(name):
    return " ".join(str(name).upper().replace(" COUNTY", "").split())


def reference(request, last_month):
    r = agent.ask(request, train=False, log=lambda *a: None)
    if r["status"] != "ok":
        return {"status": r["status"], "cost": r["usage"]["est_cost_usd"]}
    spec = Spec.model_validate(r["spec"])
    sql, params = panel.build_sql(spec)
    wide = panel.to_wide(db.query(sql, params), spec.start, last_month)
    wide.columns = [norm(panel.labels_for(spec, [c]).get(c, c)) if spec.series_by != "none" else "TOTAL" for c in wide]
    return {"status": "ok", "wide": wide, "spec": r["spec"], "cost": r["usage"]["est_cost_usd"],
            "seconds": r["usage"].get("agent_seconds")}


RULES = "--rules" in sys.argv


def generated(request, last_month):
    r = nl2sql.ask(request, log=lambda *a: None, rules=RULES)
    if r["status"] != "ok":
        return {"status": r["status"], "cost": r["usage"]["est_cost_usd"], "message": r.get("message", "")}
    rows = r["rows"].copy()
    rows["series"] = rows.series.map(norm)
    wide = panel.to_wide(rows, "2016-01-01", last_month)
    if wide.shape[1] == 1:
        wide.columns = ["TOTAL"]
    return {"status": "ok", "wide": wide, "sql": r["sql"], "assumptions": r["assumptions"],
            "cost": r["usage"]["est_cost_usd"], "seconds": r["usage"].get("agent_seconds")}


def compare(ref, gen):
    """Month-by-month agreement over the reference's months and series (a cell matches within half a unit)."""
    common = [c for c in ref.columns if c in gen.columns]
    if not common and len(ref.columns) == len(gen.columns) > 1:
        # same number of series under different names (e.g. item number vs description): pair them by total
        order_r = ref.sum().sort_values().index
        order_g = gen.sum().sort_values().index
        gen = gen.rename(columns=dict(zip(order_g, order_r)))
        common = list(order_r)
    out = {"ref_series": len(ref.columns), "gen_series": len(gen.columns), "matched_series": len(common)}
    if not common:
        return {**out, "match": False, "why": "different series (the two read the request differently)"}
    r = ref[common].fillna(0)
    g = gen[common].reindex(r.index).fillna(0)
    diff = (r - g).abs()
    tol = (r.abs() * 1e-9).clip(lower=0.5)
    bad = (diff > tol)
    last12 = r.index[-12:]
    ref12, gen12 = float(r.loc[last12].sum().sum()), float(g.loc[last12].sum().sum())
    out.update(months=int(r.shape[0]), cells=int(r.size), bad_cells=int(bad.values.sum()),
               first_bad=str(bad.any(axis=1).idxmax().date()) if bad.values.any() else None,
               ref_total=float(r.sum().sum()), gen_total=float(g.sum().sum()),
               ref_last12=ref12, gen_last12=gen12,
               match=bool(not bad.values.any() and len(common) == len(ref.columns) == len(gen.columns)))
    return out


def one(case, last_month):
    t0 = time.time()
    ref, gen = reference(case["request"], last_month), generated(case["request"], last_month)
    row = {"id": case["id"], "request": case["request"], "ref_status": ref["status"], "gen_status": gen["status"],
           "ref_cost": ref["cost"], "gen_cost": gen["cost"], "ref_seconds": ref.get("seconds"),
           "gen_seconds": gen.get("seconds"), "spec": ref.get("spec"), "sql": gen.get("sql"),
           "assumptions": gen.get("assumptions"), "message": gen.get("message")}
    if ref["status"] == "ok" and gen["status"] == "ok":
        row.update(compare(ref["wide"], gen["wide"]))
    else:
        row["match"] = ref["status"] == gen["status"]   # both declining counts as agreement
    print(f"  {'MATCH' if row['match'] else 'DIFF ':5s} {case['id']} ({time.time() - t0:.0f}s)", flush=True)
    return row


if __name__ == "__main__":
    cases = [c for c in json.loads((HERE / "cases.json").read_text()) if c["expect"]["status"] == "ok"]
    if "--only" in sys.argv:
        keep = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        cases = [c for c in cases if c["id"] in keep]
    _, last_month = panel.data_end()
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda c: one(c, last_month), cases))
    path = HERE / ("differential_rules.json" if RULES else "differential.json")
    if "--only" in sys.argv and path.exists():   # a partial rerun updates those cases in the saved results
        saved = {r["id"]: r for r in json.loads(path.read_text())}
        saved.update({r["id"]: r for r in rows})
        rows = list(saved.values())
    path.write_text(json.dumps(rows, indent=1, default=str))
    ok = sum(r["match"] for r in rows)
    print(f"\n{ok} of {len(rows)} requests: AI-written SQL matched the reference month by month")
