"""
showcase.py: build docs/index.html, the GitHub Pages landing page: what this is, how it works, example
dashboards, and the measured results (benchmark and agent evals).

    python showcase.py

Reads docs/examples/index.json (written when the examples are generated), benchmark/results.csv and
evals/results/*.json. No database or API calls.
"""
import glob
import json
from pathlib import Path

import pandas as pd

from dod.viz import page

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "index.html"
REPO = "https://github.com/joehahn/demand-on-demand"

DIAGRAM = """
<svg viewBox="0 0 960 300" role="img" aria-label="How a forecast request flows" class="diagram">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>
  <g font-size="13" fill="var(--ink)">
    <rect x="10" y="100" width="170" height="90" rx="10" fill="var(--surface)" stroke="var(--line)"/>
    <text x="95" y="130" text-anchor="middle" font-weight="600">Business question</text>
    <text x="95" y="152" text-anchor="middle" fill="var(--ink2)">"Tito's minis in</text>
    <text x="95" y="170" text-anchor="middle" fill="var(--ink2)">Des Moines, 5 months"</text>

    <rect x="230" y="80" width="210" height="130" rx="10" fill="var(--surface)" stroke="var(--accent)" stroke-width="1.5"/>
    <text x="335" y="108" text-anchor="middle" font-weight="600">Claude agent</text>
    <text x="335" y="130" text-anchor="middle" fill="var(--ink2)">resolves words to codes</text>
    <text x="335" y="150" text-anchor="middle" fill="var(--ink2)">read-only tools, about</text>
    <text x="335" y="170" text-anchor="middle" fill="var(--ink2)">4 calls and 15 seconds</text>
    <text x="335" y="192" text-anchor="middle" fill="var(--muted)" font-size="12">writes a spec, not code</text>

    <rect x="490" y="80" width="220" height="130" rx="10" fill="var(--surface)" stroke="var(--line)"/>
    <text x="600" y="108" text-anchor="middle" font-weight="600">Fixed Python harness</text>
    <text x="600" y="130" text-anchor="middle" fill="var(--ink2)">builds the SQL, tunes 96 models</text>
    <text x="600" y="150" text-anchor="middle" fill="var(--ink2)">backtests vs last year</text>
    <text x="600" y="170" text-anchor="middle" fill="var(--ink2)">on months it never saw</text>
    <text x="600" y="192" text-anchor="middle" fill="var(--muted)" font-size="12">about 15 seconds</text>

    <rect x="760" y="100" width="190" height="90" rx="10" fill="var(--surface)" stroke="var(--line)"/>
    <text x="855" y="130" text-anchor="middle" font-weight="600">Dashboard</text>
    <text x="855" y="152" text-anchor="middle" fill="var(--ink2)">forecast, 80% range,</text>
    <text x="855" y="170" text-anchor="middle" fill="var(--ink2)">how far to trust it</text>

    <rect x="330" y="240" width="280" height="50" rx="10" fill="var(--surface)" stroke="var(--line)" stroke-dasharray="4 3"/>
    <text x="470" y="262" text-anchor="middle" font-weight="600">Clean Postgres warehouse</text>
    <text x="470" y="280" text-anchor="middle" fill="var(--ink2)" font-size="12">26M orders, fixed once at load time</text>

    <rect x="330" y="10" width="280" height="44" rx="10" fill="none" stroke="var(--line)" stroke-dasharray="4 3"/>
    <text x="470" y="37" text-anchor="middle" fill="var(--ink2)" font-size="12">credentials never reach the model</text>
  </g>
  <g stroke="var(--muted)" stroke-width="1.5" fill="none" marker-end="url(#arr)">
    <line x1="180" y1="145" x2="226" y2="145"/>
    <line x1="440" y1="145" x2="486" y2="145"/>
    <line x1="710" y1="145" x2="756" y2="145"/>
    <line x1="335" y1="210" x2="400" y2="238"/>
    <line x1="600" y1="210" x2="540" y2="238"/>
  </g>
</svg>"""

EXTRA_CSS = """
.diagram { width:100%; height:auto; margin:8px 0 4px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr)); gap:12px; margin:12px 0; }
.ex { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px 16px; }
.ex a.q { font-weight:600; font-style:italic; color:var(--ink); text-decoration:none; }
.ex a.q:hover { text-decoration:underline; }
.ex p { font-size:14px; margin:8px 0 0; }
.ex .meta { font-size:12px; color:var(--muted); margin-top:8px; }
.cta { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px 18px; margin-top:28px; }
"""


def esc(s):
    import html
    return html.escape(str(s))


def build():
    ex = json.loads((ROOT / "docs" / "examples" / "index.json").read_text())
    bench = pd.read_csv(ROOT / "benchmark" / "results.csv").dropna(subset=["rel_mae"])
    evals = json.loads(Path(sorted(glob.glob(str(ROOT / "evals" / "results" / "*.json")))[-1]).read_text())
    n_ok, n_runs = sum(r["passed"] for r in evals), len(evals)
    beat = int((bench.rel_mae < 1).sum())
    end_to_end = sorted(e["agent_seconds"] + e["harness_seconds"] for e in ex)[len(ex) // 2]
    cost = sorted(e["cost"] for e in ex)[len(ex) // 2]

    def verdict(r):
        return (f"{1 - r:.0%} more accurate than repeating last year" if r < 0.95 else
                "about as accurate as repeating last year" if r <= 1.05 else f"{r - 1:.0%} less accurate than last year")
    cards = "".join(
        f'<div class="ex"><a class="q" href="examples/{e["slug"]}.html">&ldquo;{esc(e["request"])}&rdquo;</a>'
        f'<p>{esc(e["summary"])}</p><div class="meta">Backtest: {verdict(e["rel_mae"])} ({e["rel_mae"]:.2f}). '
        f'{e["agent_seconds"] + e["harness_seconds"]:.0f} s, ${e["cost"]:.2f}.</div></div>' for e in ex)
    tiles = [(f"{end_to_end:.0f} s", "plain English to dashboard (median)"),
             (f"${cost:.2f}", "Claude API cost per request"),
             (f"{beat} of {len(bench)}", "benchmark forecasts beat last year"),
             (f"{n_ok}/{n_runs}", "agent eval runs correct")]
    tiles_html = "".join(f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in tiles)

    body = f"""
<h1>demand-on-demand</h1>
<p class="asked">Ask for a demand forecast in plain English. Get a tested forecast and dashboard in under a minute.</p>
<p>A business user types a question like <em>"monthly forecast of Tito's minis in Des Moines for the next 5 months"</em>.
One Claude agent turns the words into a precise request against a company-style Postgres warehouse of 26 million
Iowa liquor orders (2016 to 2026). A fixed Python harness then builds the data, tunes and tests the models against the
simplest honest benchmark, the same month last year, and publishes a dashboard that says how far to trust the answer.</p>
<div class="tiles">{tiles_html}</div>

<h2>How it works</h2>
{DIAGRAM}
<ul>
<li><strong>The AI decides what to forecast; code decides how.</strong> The agent resolves products, places, measures
and horizons with read-only tools, and hands over a spec. It never writes the SQL, the train/test split, the metrics
or the charts. Those are fixed code, the same for every request.</li>
<li><strong>Honest accuracy.</strong> Every forecast is backtested on the last 24 months, which no choice ever saw.
Model settings are tuned on the two years before that, and "same month last year" is always a candidate: a model is
used only as far as it beats it.</li>
<li><strong>Clean data, fixed once.</strong> The public data has real problems: duplicated export rows, recoded
categories, renumbered products, inconsistent spellings. They are documented on
<a href="data_exploration.html">the data exploration page</a> and fixed once, in the warehouse, as shown on
<a href="data_fixes.html">the data fixes page</a>. No forecast has to know they existed.</li>
<li><strong>Least privilege.</strong> The agent's database login can only read the clean tables. Credentials stay
in the Python process and never appear in a prompt.</li>
</ul>

<h2>Example forecasts</h2>
<p>Five requests typed in plain English, each run once, shown as they came out, the misses included.</p>
<div class="cards">{cards}</div>

<h2>How good is it?</h2>
<p><strong>Forecast accuracy.</strong> On {len(bench)} forecasts sampled from the warehouse (products, categories,
vendors; counties and statewide; bottles, dollars and liters; 3 to 12 months ahead), the chosen model beat "same month
last year" on <strong>{beat}</strong>, with a median error {1 - bench.rel_mae.median():.0%} lower than that baseline
(median monthly error {bench.model_error.median():.1%} vs {bench.baseline_error.median():.1%}). Retail demand here is
very regular year to year, so last year is a hard baseline to beat, and on the rest it was not beaten.
<a href="{REPO}/blob/main/benchmark/report.md">Full benchmark</a>.</p>
<p><strong>Agent accuracy.</strong> {n_ok} of {n_runs} runs across {n_runs // 2} test requests produced exactly the right
product, place, measure and horizon, or correctly declined (a city outside Iowa, a 24-month horizon, a product too new
to forecast). Every number in the dashboard summaries is checked against the harness's results.
<a href="{REPO}/blob/main/evals/report.md">Eval report</a>.</p>

<h2>Built with</h2>
<p>Claude Code (building), the Claude API with Claude Sonnet 5 (the agent at runtime), Postgres, skforecast,
LightGBM and scikit-learn, plotly. Code, specs, evals and write-up: <a href="{REPO}">github.com/joehahn/demand-on-demand</a>.</p>

<div class="cta"><strong>Joseph M. Hahn, Ph.D., JMH DataSciences.</strong> Independent AI and machine learning
consultant; eight years delivering AI systems in Oracle's AI Center of Excellence. If your business runs on forecasts
someone still builds by hand, <a href="https://jmh-datasciences.com">let's talk</a>.
<a href="https://www.linkedin.com/in/hahnjoe/">LinkedIn</a>.</div>

<footer>
Data: <a href="https://catalog.data.gov/dataset?q=iowa+liquor+sales">Iowa Liquor Sales</a>, State of Iowa, via the Iowa
Data Hub, licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; modified (cleaned and
aggregated). County population and income: U.S. Census Bureau. Not endorsed by the State of Iowa. Brand names appear
only as they do in the public data.
</footer>"""
    html = page("demand-on-demand", body).replace("</style>", EXTRA_CSS + "</style>", 1)
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    build()
