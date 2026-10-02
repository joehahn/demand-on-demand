"""
differential_report.py: publish docs/differential.html (and evals/differential.md) from evals/differential.json:
AI-written SQL (NL2SQL) tested against the slot-filling path as a fixed reference, explained for a general audience.

    python evals/differential_report.py
"""
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod.panel import build_sql  # noqa: E402
from dod.spec import Spec  # noqa: E402
from dod.viz import page  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE.parent / "docs" / "differential.html"
REPO = "https://github.com/joehahn/demand-on-demand/blob/main"

# Why each mismatch happened, found by reading both queries (evals/differential.json). Key: case id.
WHY = {
    "titos_minis_des_moines": ("AI missed renumbered items", "The AI filtered on today's item numbers (item_no) instead of "
                               "the product family (family_item_no), so the mini's older numbers 38180 and 938180 were "
                               "left out and history before mid-2020 is too low."),
    "titos_minis_by_item": ("AI missed renumbered items", "Same mistake as above, in a per-item forecast. In an earlier "
                            "run the AI got this request right: same request, different SQL."),
    "bdi_store": ("AI missed renumbered items", "Same mistake, for a single store."),
    "titos_polk": ("AI missed renumbered items", "The AI listed today's Tito's item numbers instead of the whole brand, "
                   "leaving out older numbers and small products."),
    "titos_st_ansgar": ("AI missed renumbered items", "Same mistake; only one month differs (July 2020, when the mini "
                        "had a temporary number)."),
    "bottled_in_bond": ("AI used old category codes", "The AI filtered on the category code recorded on each order "
                        "(category_code) instead of today's category (category_current). The state reassigned codes in "
                        "2016, so older history counts the wrong products."),
    "vodka_top_counties": ("AI used old category codes", "Same mistake, in a five-county breakout. In an earlier run "
                           "the AI got this request right."),
    "ames_whiskey": ("AI used old category codes", "The AI chose its own whiskey categories by name and filtered on the "
                     "category codes as recorded, not today's taxonomy."),
    "crown_mount_pleasant": ("AI missed some products", "The AI matched names starting with CROWN ROYAL, so barrel "
                             "picks named \"BP CROWN ROYAL ...\" were left out (a tiny difference)."),
    "jack_iowa_city": ("AI missed some products", "Same: names starting with JACK DANIEL, so special releases named "
                       "\"HA JACK DANIELS ...\" were left out."),
}
# Found by the first run and fixed in the reference path (a bug on the trusted side, not the AI's).
FIXED = ("The reference agent's product search showed at most 60 products, so for Crown Royal (91 products) and Jack "
         "Daniel's (80) it quietly left out the smallest ones. Fixed: the search now says when more products match, "
         "and the request form can name a whole brand.")


def reference_sql(spec):
    """The SQL the harness writes for the reference request, readable (bind parameters filled in)."""
    s = Spec.model_validate(spec)
    sql, params = build_sql(s)
    items = params["items"] if len(params["items"]) <= 12 else params["items"][:12] + ["..."]
    params["items"] = items
    for k, v in params.items():
        sql = sql.replace(f"%({k})s", repr(v) if not isinstance(v, list) else "ARRAY" + repr(v))
    return sql.strip()


def pct(a, b):
    if not a:
        return ""
    d = b / a - 1
    return "under 0.1%" if abs(d) < 0.0005 else f"{d:+.1%}"


def build():
    rows = json.loads((HERE / "differential.json").read_text())
    rows = [r for r in rows if r.get("ref_status") == "ok"]
    same = [r for r in rows if r["match"]]
    ai = [r for r in rows if not r["match"]]
    avg = lambda key: sum(r[key] or 0 for r in rows) / len(rows)
    tiles = [(f"{len(same)} of {len(rows)}", "requests where AI-written SQL matched the reference exactly"),
             (str(len(ai)), "AI-written queries that were wrong (but ran fine)"),
             ("1", "bug found in the reference path (fixed)"),
             (f"${avg('gen_cost'):.3f}", f"per AI-written query (reference: ${avg('ref_cost'):.3f})")]
    tiles_html = "".join(f'<div class="tile"><div class="v">{html.escape(v)}</div><div class="k">{html.escape(k)}</div></div>'
                         for v, k in tiles)
    trs = []
    order = {k: i for i, k in enumerate(WHY)}   # explanations that say "same mistake" follow the one they refer to
    for r in sorted(rows, key=lambda r: (r["match"], order.get(r["id"], 99), r["id"])):
        verdict, why = ("Identical", "Same series, month by month.") if r["match"] else WHY.get(r["id"], ("Different", ""))
        hist = pct(r.get("ref_total"), r.get("gen_total")) if not r["match"] else ""
        last = pct(r.get("ref_last12"), r.get("gen_last12")) if not r["match"] else ""
        sqls = (f"<details><summary>both queries</summary><p><strong>Reference (fixed code):</strong></p>"
                f"<pre>{html.escape(reference_sql(r['spec']))}</pre><p><strong>AI-written:</strong></p>"
                f"<pre>{html.escape(r['sql'] or '')}</pre></details>") if r.get("spec") and r.get("sql") else ""
        trs.append(f"<tr><td>{html.escape(r['request'])}{sqls}</td><td><strong>{html.escape(verdict)}</strong>"
                   f"<br>{html.escape(why)}</td><td class=\"num\">{hist}</td><td class=\"num\">{last}</td></tr>")
    body = f"""
<p class="note"><a href="index.html">demand-on-demand</a> &middot; <a href="data_dictionary.html">data dictionary</a>
&middot; <a href="https://github.com/joehahn/demand-on-demand">GitHub</a></p>
<h1>Can AI-written SQL be trusted? Testing it against a reference</h1>
<p>Two ways to turn a plain-English request into the data a forecast is trained on:</p>
<ul>
<li><strong>Slot filling (the reference).</strong> The AI fills in a short request form (product, place, measure,
months), and fixed, tested code writes the SQL. Predictable, but it only handles what the form has slots for.</li>
<li><strong>Text-to-SQL (NL2SQL).</strong> The AI writes the SQL itself. It can handle requests nobody planned for, but
every query is new code. How do you know it is right?</li>
</ul>
<p><strong>The test:</strong> give both the same {len(rows)} requests, with the same data dictionary, the same lookup
tools and the same read-only database login, and compare the two monthly histories month by month. Where the slot
form can express a request, the two must agree; any difference is a bug on one side.</p>
<div class="tiles">{tiles_html}</div>
<h2>What we learned</h2>
<ol>
<li><strong>The AI's mistakes passed every quick check.</strong> The wrong queries ran without error, and their last
12 months matched the reference exactly or within 1%. The errors were in older history, the part the model learns from. Only a
month-by-month comparison against a reference found them.</li>
<li><strong>The same request can produce different SQL.</strong> Several requests were right in one run and wrong in
another.</li>
<li><strong>Documentation was not enough.</strong> The data dictionary the AI reads says to use the product family for
renumbered items and today's category for history; the AI still used the raw codes in {len(ai)} of {len(rows)}
requests.</li>
<li><strong>The reference had a bug too.</strong> {FIXED} Differential testing finds problems on both sides; after the
fix, every remaining difference is on the AI side.</li>
</ol>
<p><strong>What this means:</strong> AI-written SQL is promising for requests the form cannot express, but it needs a
reference to be checked against. A practical design keeps slot filling for the common requests, lets the AI write SQL
for the rest, and checks every AI-written series against anything the reference can compute (for example, weekly
totals must add up to the monthly reference).</p>
<h2>Every request</h2>
<div class="tbl"><table><thead><tr><th>request</th><th>result</th><th class="num">all history, AI vs reference</th>
<th class="num">last 12 months</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>
<p class="note">Model: both paths use the same Claude agent (claude-sonnet-5) and tools. Code:
<a href="{REPO}/dod/nl2sql.py">the NL2SQL agent</a>, <a href="{REPO}/dod/agent.py">the slot-filling agent</a>,
<a href="{REPO}/evals/differential.py">the test</a>. Results: <a href="{REPO}/evals/differential.json">differential.json</a>.</p>
<footer>Data: Iowa Liquor Sales, State of Iowa, via the Iowa Data Hub, CC BY 4.0; modified (see the data fixes page).</footer>"""
    md = [f"# Differential test: AI-written SQL vs the slot-filling reference\n",
          f"{len(rows)} requests: {len(same)} identical month by month, {len(ai)} AI-written queries wrong. The first "
          f"run also found a reference bug, since fixed: {FIXED} Details and both queries: docs/differential.html.\n",
          "| request | result | all history | last 12 months |", "|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["match"], order.get(r["id"], 99), r["id"])):
        verdict = "identical" if r["match"] else WHY.get(r["id"], ("different",))[0]
        md.append(f"| {r['request']} | {verdict} | {'' if r['match'] else pct(r.get('ref_total'), r.get('gen_total'))} | "
                  f"{'' if r['match'] else pct(r.get('ref_last12'), r.get('gen_last12'))} |")
    (HERE / "differential.md").write_text("\n".join(md) + "\n")
    return page("AI-written SQL vs a Reference", body)


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT} and {HERE / 'differential.md'}")
