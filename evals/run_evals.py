"""Agent evals: does the agent turn each request into the right spec?

    python evals/run_evals.py                 # every case, 2 runs each, 4 at a time
    python evals/run_evals.py --runs 3 --only titos_polk,chicago

Runs the agent in spec-only mode (no model training), scores every run against evals/cases.json, and writes
evals/results/<timestamp>.json and evals/report.md. Each run costs a few cents of API usage.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import agent  # noqa: E402

HERE = Path(__file__).parent


def check(case, res):
    """One pass/fail per expectation, with a short reason for each failure."""
    exp, out = case["expect"], []

    def add(name, ok, why=""):
        out.append({"check": name, "ok": bool(ok), "why": "" if ok else why})

    add("status", res["status"] == exp["status"], f"got {res['status']}")
    if exp["status"] != "ok" or res["status"] != "ok":
        return out
    spec = res["spec"]
    for key in ("target", "horizon", "series_by"):
        if key in exp:
            add(key, spec[key] == exp[key], f"got {spec[key]!r}, want {exp[key]!r}")
    for scope in ("product", "region"):
        if scope not in exp:
            continue
        want, got = exp[scope], spec[scope]
        add(f"{scope}.kind", got["kind"] == want["kind"], f"got {got['kind']}, want {want['kind']}")
        missing = sorted(set(want.get("must", [])) - set(got["codes"]))
        add(f"{scope}.codes", not missing, f"missing {missing}")
        extra = sorted(set(want.get("forbid", [])) & set(got["codes"]))
        if want.get("forbid"):
            add(f"{scope}.forbid", not extra, f"included {extra}")
    return out


def one(case, run_no):
    t0 = time.time()
    try:
        res = agent.ask(case["request"], train=False, log=lambda *a: None)
    except Exception as e:  # an agent crash is a failed run, not a failed eval
        res = {"status": "crash", "message": repr(e), "usage": {"est_cost_usd": 0}, "trace": []}
    checks = check(case, res)
    return {"id": case["id"], "run": run_no, "tags": case["tags"], "status": res["status"],
            "passed": all(c["ok"] for c in checks), "checks": checks,
            "cost": res["usage"].get("est_cost_usd", 0), "seconds": round(time.time() - t0, 1),
            "tool_calls": len(res.get("trace", [])), "spec": res.get("spec"), "assumptions": res.get("assumptions"),
            "message": res.get("message", "")}


def report(results, cases):
    by_case = {}
    for r in results:
        by_case.setdefault(r["id"], []).append(r)
    runs = len(results)
    lines = [f"# Agent eval report\n", f"{len(cases)} cases, {runs} runs, model `{agent.MODEL}`, "
             f"{time.strftime('%Y-%m-%d %H:%M')}.\n",
             f"- Runs fully correct: **{sum(r['passed'] for r in results)}/{runs}** "
             f"({sum(r['passed'] for r in results) / runs:.0%})",
             f"- Cases correct on every run: **{sum(all(r['passed'] for r in rs) for rs in by_case.values())}/{len(cases)}**",
             f"- Cost: ${sum(r['cost'] for r in results):.2f} total, ${sum(r['cost'] for r in results) / runs:.3f} per run; "
             f"median {sorted(r['seconds'] for r in results)[runs // 2]:.0f}s and "
             f"{sorted(r['tool_calls'] for r in results)[runs // 2]} tool calls per run\n"]
    tags = sorted({t for c in cases for t in c["tags"]})
    lines.append("| tag | runs correct |\n|---|---|")
    for t in tags:
        rs = [r for r in results if t in r["tags"]]
        lines.append(f"| {t} | {sum(r['passed'] for r in rs)}/{len(rs)} |")
    lines.append("\n| case | runs correct | failures |\n|---|---|---|")
    for c in cases:
        rs = by_case.get(c["id"], [])
        fails = sorted({f"{ch['check']}: {ch['why']}" for r in rs for ch in r["checks"] if not ch["ok"]})
        lines.append(f"| {c['id']} | {sum(r['passed'] for r in rs)}/{len(rs)} | {'; '.join(fails)[:300]} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    args = sys.argv[1:]
    n_runs = int(args[args.index("--runs") + 1]) if "--runs" in args else 2
    cases = json.loads((HERE / "cases.json").read_text())
    if "--only" in args:
        keep = set(args[args.index("--only") + 1].split(","))
        cases = [c for c in cases if c["id"] in keep]
    jobs = [(c, k) for c in cases for k in range(1, n_runs + 1)]
    print(f"{len(jobs)} runs of {len(cases)} cases")
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for r in pool.map(lambda j: one(*j), jobs):
            results.append(r)
            print(f"  {'PASS' if r['passed'] else 'FAIL'} {r['id']} #{r['run']}  ${r['cost']:.3f} {r['seconds']:.0f}s"
                  + ("" if r["passed"] else "  " + "; ".join(f"{c['check']}: {c['why']}" for c in r["checks"] if not c["ok"])[:200]))
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{time.strftime('%Y%m%d_%H%M')}.json").write_text(json.dumps(results, indent=1, default=str))
    name = "report_partial.md" if "--only" in args else "report.md"  # a subset never overwrites the full report
    (HERE / name).write_text(report(results, cases))
    print((HERE / name).read_text())
