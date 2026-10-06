"""Score the agent's SQL (dod/agent.ask) against the answer key (evals/answers.json).

    python evals/score_sql.py                       # every request, 3 runs each, 4 at a time (about $2)
    python evals/score_sql.py --runs 1 --only cream_weekly,hyvee_weekly
    python evals/score_sql.py --rescore evals/sql_results/<file>.json   # rerun the saved SQL, score again (no AI)

Each run is judged on two things:
  data     the AI's order lines, summed by month (by fixed code, as in dod/history.py), equal the answer key in every
           month (within half a unit)
  reading  the grain and horizon are the ones expected (or one of the equivalent readings in "accept", e.g. 1 quarter
           or 3 months; "any" when the request gives none); a request that should be declined is declined
Writes evals/sql_results/<timestamp>.json (every run, with its SQL) and evals/sql_report.md.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import agent, db  # noqa: E402
from build_answers import norm  # noqa: E402

HERE = Path(__file__).parent


def monthly(sql):
    """The agent's order lines summed by month and series (column day = the month's first day)."""
    return db.query(f"SELECT date_trunc('month', day)::date AS day, series, sum(value) AS value FROM ({sql}) q GROUP BY 1, 2")


def compare(answer, rows):
    """Month by month, per series. Returns (match, why, error as a share of the answer's total)."""
    key = pd.DataFrame(answer["series"]).fillna(0.0)
    key.index = pd.to_datetime(key.index)
    month = pd.to_datetime(rows.day).dt.to_period("M").dt.start_time
    ai = rows.assign(month=month, series=rows.series.map(norm)).pivot_table(
        index="month", columns="series", values="value", aggfunc="sum").reindex(key.index).fillna(0.0)
    if len(key.columns) == 1 and len(ai.columns) == 1:
        ai.columns = key.columns
    elif set(ai.columns) != set(key.columns):
        if len(ai.columns) != len(key.columns):
            return False, f"{len(ai.columns)} series, expected {len(key.columns)}", None
        # same number of series under other names (e.g. item number vs description): pair them by size
        ai = ai.rename(columns=dict(zip(ai.sum().sort_values().index, key.sum().sort_values().index)))
    diff = (key - ai[key.columns]).abs()
    bad = diff > (key.abs() * 1e-9).clip(lower=0.5)
    share = float(diff.values.sum() / max(key.values.sum(), 1))
    if not bad.values.any():
        return True, "", 0.0
    first = bad.any(axis=1).idxmax().date()
    return False, f"{int(bad.values.sum())} of {bad.size} months differ (first {first}), off by {share:.2%}", share


def reading_ok(exp, grain, horizon):
    accept = exp.get("accept", [[exp["grain"], exp["horizon"]]])
    return accept == "any" or [grain, horizon] in accept


def score(case, answer, row, rows):
    """Fill in a run's verdict from its status, grain, horizon and daily rows."""
    exp = case["expect"]
    if exp["status"] != "ok":
        row.update(reading=row["status"] != "ok", data=True, why="" if row["status"] != "ok" else "answered; should decline")
    elif row["status"] != "ok":
        row.update(reading=False, data=False, why=f"no forecast: {row['message'][:150]}")
    else:
        row["reading"] = reading_ok(exp, row["grain"], row["horizon"])
        row["data"], why, row["off_share"] = compare(answer, rows)
        row["why"] = "; ".join(x for x in [why, "" if row["reading"] else
                                           f"read as {row['horizon']} {row['grain']}, expected {exp['horizon']} {exp['grain']}"] if x)
    row["passed"] = row["reading"] and row["data"]
    print(f"  {'PASS' if row['passed'] else 'FAIL'} {case['id']} #{row['run']} {row['why']}", flush=True)
    return row


def one(case, answer, run_no):
    t0 = time.time()
    try:
        r = agent.ask(case["request"], log=lambda *a: None)
    except Exception as e:   # a crash is a failed run, not a failed scorer
        r = {"status": "crash", "message": repr(e)[:300], "usage": {"est_cost_usd": 0}, "trace": []}
    row = {"id": case["id"], "run": run_no, "status": r["status"], "cost": r["usage"].get("est_cost_usd", 0),
           "seconds": round(time.time() - t0, 1), "tool_calls": len(r.get("trace", [])),
           "message": r.get("message", "")[:500]}
    if r["status"] == "ok":
        plan = r["plan"]
        row.update(sql=plan.sql, grain=plan.grain, horizon=plan.horizon, assumptions=plan.assumptions,
                   title=plan.title, product=plan.product, place=plan.place)
    return score(case, answer, row, monthly(row["sql"]) if r["status"] == "ok" else None)


def rescore(row, case, answer):
    """A saved run scored again against the current cases and answers, by rerunning its SQL (no AI call)."""
    rows = monthly(row["sql"]) if row["status"] == "ok" else None
    return score(case, answer, dict(row), rows)


def report(rows, cases):
    df = pd.DataFrame(rows)
    by = df.groupby("id")
    lines = ["# AI-written SQL scored against the answer key\n",
             f"{len(cases)} requests x {df.run.nunique()} runs = {len(df)} runs. Passed: **{df.passed.sum()} of {len(df)}** "
             f"(data right in {df.data.sum()}, reading right in {df.reading.sum()}). Requests right in every run: "
             f"{int(by.passed.all().sum())} of {len(cases)}. Cost ${df.cost.sum():.2f}, median {df.seconds.median():.0f} s "
             f"and {df.tool_calls.median():.0f} tool calls per request.\n",
             "| request | passed | what went wrong |", "|---|---|---|"]
    for c in cases:
        g = df[df.id == c["id"]]
        whys = sorted({w for w in g.why if w})
        lines.append(f"| {c['request']} | {g.passed.sum()}/{len(g)} | {'; '.join(whys)[:300]} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    runs = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 3
    cases = json.loads((HERE / "answer_cases.json").read_text())
    if "--only" in sys.argv:
        keep = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        cases = [c for c in cases if c["id"] in keep]
    answers = json.loads((HERE / "answers.json").read_text())
    out = HERE / "sql_results"
    if "--rescore" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--rescore") + 1])
        by_id = {c["id"]: c for c in cases}
        rows = [rescore(r, by_id[r["id"]], answers.get(r["id"])) for r in json.loads(path.read_text()) if r["id"] in by_id]
    else:
        jobs = [(c, answers.get(c["id"]), n) for n in range(1, runs + 1) for c in cases]
        with ThreadPoolExecutor(4) as pool:
            rows = list(pool.map(lambda j: one(*j), jobs))
        # a run of only some requests is named apart, so the dashboards and landing page read only full runs
        path = out / f"{'only_' if '--only' in sys.argv else ''}{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.mkdir(exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, default=str))
    (HERE / "sql_report.md").write_text(report(rows, cases))
    print("\n" + report(rows, cases).split("\n")[2])
