"""Regenerate the example dashboards published in docs/examples/, from their plain-English requests.

    python make_examples.py            # every example (about $0.15 of API calls and 3 minutes)
    python make_examples.py 4          # only example 4

Each request goes through the same path as any forecast (dod/forecast.py). The dashboard is copied to
docs/examples/<file>.html, and docs/examples/index.json (read by showcase.py) gets its summary, cost and timings.
"""
import json
import shutil
import sys
from pathlib import Path

from dod import agent, forecast

ROOT = Path(__file__).parent
DOCS = ROOT / "docs" / "examples"
# (request, published file name, title shown on the page: None keeps the agent's own title)
EXAMPLES = [
    ("Monthly forecast of Tito's minis in Des Moines for the next 5 months", "tito_s_minis_des_moines_next_5_months",
     "Tito's minis, Des Moines, next 5 months"),
    ("What revenue should we expect from Fireball in Linn County next quarter?", "fireball_linn_county_next_quarter",
     "Fireball, Linn County, next quarter revenue"),
    ("How many bottles of cream liqueur will Iowa stores order for the holidays?", "cream_liqueur_holidays",
     "Cream liqueurs, Iowa, through the holidays"),
    ("show me weekly forecast of Cream liqueur bottles sold across all of iowa, twelve weeks out",
     "cream_liqueur_by_week_next_12_weeks", "Weekly Cream Liqueur Bottles Statewide"),
]


def make(request, name, title):
    a = agent.ask(request)
    if a["status"] != "ok":
        raise SystemExit(f"No forecast for {request!r}: {a.get('message', '')}")
    plan = a["plan"].model_copy(update={"title": title}) if title else a["plan"]
    s = forecast.run(plan, a["usage"], a["trace"])
    shutil.copy(s["dashboard"], DOCS / f"{name}.html")
    return {"request": request, "slug": name, "title": plan.title, "grain": s["grain"], "rel_mae": s["test_rel_mae"],
            "summary": s["agent"]["summary"], "cost": a["usage"]["est_cost_usd"],
            "agent_seconds": a["usage"]["agent_seconds"], "harness_seconds": s["seconds"]}


if __name__ == "__main__":
    only = {int(x) for x in sys.argv[1:] if x.isdigit()}
    index_path = DOCS / "index.json"
    index = {e["slug"]: e for e in json.loads(index_path.read_text())} if index_path.exists() else {}
    for n, (request, name, title) in enumerate(EXAMPLES, 1):
        if only and n not in only:
            continue
        index[name] = make(request, name, title)
        print(f"{n}. {name}: {index[name]['summary']}", flush=True)
    order = [name for _, name, _ in EXAMPLES]
    index_path.write_text(json.dumps([index[k] for k in order if k in index], indent=1))
