"""Summary grounding eval: is every number in the dashboard summary traceable to the harness's facts?

    python evals/grounding.py [--runs 3]

For each out/*/summary.json that has saved facts, asks the narrator for a summary several times and checks
every number it writes against the numbers in the facts (2% tolerance for rounding). Dates and small counts
such as "5 months" are allowed. Writes evals/grounding.md.
"""
import json
import re
import sys
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import agent  # noqa: E402

ROOT = Path(__file__).parent.parent
NUM = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?%?(?:\s?(?:million|thousand|billion|k)\b)?")
SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "billion": 1e9}


def value(raw):
    """'$15.2 million' -> 15200000.0; '53k' -> 53000.0; '+41%' -> 41.0."""
    word = next((w for w in SCALE if raw.endswith(w)), None)
    num = raw[: -len(word)] if word else raw
    v = float(num.strip().replace(",", "").replace("$", "").rstrip("%"))
    return v * SCALE[word] if word else v


def numbers_in(obj):
    """Every number in the facts, including those inside strings like '+41%' or '2026-09'."""
    text = json.dumps(obj)
    return [value(m) for m in NUM.findall(text) if m.strip("+-$%,")]


def ungrounded(summary, facts):
    allowed = numbers_in(facts)
    bad = []
    for raw in NUM.findall(summary):
        v = value(raw)
        if 2000 <= v <= 2100 or (abs(v) <= 12 and not raw.endswith("%")):  # years, months, horizons, counts
            continue
        tol = 0.02 if v < 1e5 else 0.05  # "$15.2 million" rounds harder than "53,000"
        if not any(abs(v - a) <= tol * max(abs(a), 1) for a in allowed):
            bad.append(raw)
    return bad


if __name__ == "__main__":
    runs = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 3
    client = anthropic.Anthropic()
    rows, cost = [], {"model": agent.MODEL, "calls": 0, "input_tokens": 0, "output_tokens": 0,
                      "cache_write_tokens": 0, "cache_read_tokens": 0, "est_cost_usd": 0.0}
    for path in sorted(ROOT.glob("out/*/summary.json")):
        facts = json.loads(path.read_text()).get("facts")
        if not facts:
            continue
        for k in range(runs):
            text = agent.narrate(client, facts, cost)
            bad = ungrounded(text, facts)
            rows.append({"forecast": facts["title"], "run": k + 1, "ok": not bad, "ungrounded": bad, "summary": text})
            print(f"{'OK  ' if not bad else 'FAIL'} {facts['title']} #{k + 1} {bad}")
    ok = sum(r["ok"] for r in rows)
    md = [f"# Summary grounding eval\n\n{len(rows)} summaries, {ok} fully grounded ({ok / max(len(rows), 1):.0%}); "
          f"narrator `{agent.MODEL}`, ${cost['est_cost_usd']:.2f}.\n"]
    for r in rows:
        md.append(f"- **{r['forecast']} #{r['run']}**: {'grounded' if r['ok'] else 'UNGROUNDED ' + ', '.join(r['ungrounded'])}"
                  f"\n  > {r['summary']}")
    (ROOT / "evals" / "grounding.md").write_text("\n".join(md) + "\n")
    print(md[0])
