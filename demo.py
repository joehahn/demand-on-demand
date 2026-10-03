"""
demo.py: run the canned requests in demo/requests.json in front of an audience.

    python demo.py                 # list the requests
    python demo.py 3               # run request 3 live (agent + fixed code, ~40 s) and open its dashboard
    python demo.py 3 --replay      # open the copy saved at rehearsal (no network or API needed)
    python demo.py "any request"   # an audience request, live
    python demo.py --rehearse      # run every request live and save copies to demo/saved/ for --replay
    python demo.py --check         # score the agent's SQL on the demo requests against the answer key (a few cents)

Live runs are interactive: if the agent needs a clarification, it asks here and you type the answer.
"""
import json
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from dod import forecast

ROOT = Path(__file__).parent
REQUESTS = json.loads((ROOT / "demo" / "requests.json").read_text())
SAVED = ROOT / "demo" / "saved"


def show_list():
    for i, r in enumerate(REQUESTS, 1):
        print(f"{i}. {r['request']}\n   shows {r['shows']}\n")


def run(request, save_as=None):
    """Run one request live, open its dashboard, and optionally keep a copy for --replay."""
    print(f"\n“{request}”\n")
    t0 = time.time()
    result = forecast.forecast(request, interactive=True)
    if result["status"] != "ok":
        print(f"\nNo forecast ({result['status']}): {result.get('message', '')}")
        if save_as:  # a decline is part of the demo too: keep its message for replay
            SAVED.mkdir(parents=True, exist_ok=True)
            (SAVED / f"{save_as}.txt").write_text(result.get("message", ""))
        return
    dashboard = Path(result["summary"]["dashboard"])
    print(f"\nDone in {time.time() - t0:.0f} s, about ${result['usage']['est_cost_usd']:.2f}: {dashboard}")
    if save_as:
        SAVED.mkdir(parents=True, exist_ok=True)
        shutil.copy(dashboard, SAVED / f"{save_as}.html")
    webbrowser.open(dashboard.resolve().as_uri())


def replay(item):
    page, note = SAVED / f"{item['id']}.html", SAVED / f"{item['id']}.txt"
    print(f"\n“{item['request']}” (saved at rehearsal)")
    if page.exists():
        webbrowser.open(page.resolve().as_uri())
    elif note.exists():
        print(f"\nNo forecast: {note.read_text()}")
    else:
        print("No saved copy: run python demo.py --rehearse first.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--check" in sys.argv:
        ids = ",".join(r["id"] for r in REQUESTS)
        sys.exit(subprocess.call([sys.executable, str(ROOT / "evals" / "score_sql.py"), "--runs", "1", "--only", ids]))
    elif "--rehearse" in sys.argv:
        for r in REQUESTS:
            run(r["request"], save_as=r["id"])
    elif not args:
        show_list()
    elif args[0].isdigit():
        item = REQUESTS[int(args[0]) - 1]
        replay(item) if "--replay" in sys.argv else run(item["request"])
    else:
        run(" ".join(args))
