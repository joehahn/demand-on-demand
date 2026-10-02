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
    "titos_minis_by_item": ("AI missed renumbered items", "Same mistake as above, in a per-item forecast. In the first full "
                            "run the AI got this request right; in a rerun it got it wrong: same request, different SQL."),
    "titos_st_ansgar": ("AI missed renumbered items", "Same mistake; only one month differs (July 2020, when the mini had "
                        "a temporary number)."),
    "bdi_store": ("AI missed renumbered items", "Same mistake, for a single store."),
    "bottled_in_bond": ("AI used old category codes", "The AI filtered on the category code recorded on each order "
                        "(category_code) instead of today's category (category_current). The state reassigned codes in "
                        "2016, so older history counts the wrong products."),
    "crown_mount_pleasant": ("Reference bug", "The reference agent's product search shows at most 60 products, and "
                             "Crown Royal has 91, so the reference left out 31 small ones (about 0.5% of liters). The "
                             "AI-written SQL (item_desc ILIKE 'CROWN ROYAL%') included them all."),
    "jack_iowa_city": ("Reference bug", "Same search limit: Jack Daniel's has 80 products and the reference used 60. "
                       "The AI-written SQL included them all."),
}


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
    return f"{(b / a - 1):+.1%}" if a else ""


def build():
    rows = json.loads((HERE / "differential.json").read_text())
    rows = [r for r in rows if r.get("ref_status") == "ok"]
    same = [r for r in rows if r["match"]]
    ai = [r for r in rows if not r["match"] and WHY.get(r["id"], ("",))[0].startswith("AI")]
    ref = [r for r in rows if not r["match"] and WHY.get(r["id"], ("",))[0] == "Reference bug"]
    avg = lambda key: sum(r[key] or 0 for r in rows) / len(rows)
    tiles = [(f"{len(same)} of {len(rows)}", "requests where AI-written SQL matched the reference exactly"),
             (str(len(ai)), "AI-written queries that were wrong (but ran fine)"),
             (str(len(ref)), "bugs found in the reference path"),
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
<li><strong>The AI's mistakes passed every quick check.</strong> The wrong queries ran without error, and for 4 of
the 5 the last 12 months matched the reference exactly. The errors were in older history, the part the model learns from. Only a
month-by-month comparison against a reference found them.</li>
<li><strong>The same request can produce different SQL.</strong> One request was right in one run and wrong in the next.</li>
<li><strong>Documentation was not enough.</strong> The data dictionary the AI reads says to use the product family for
renumbered items and today's category for history; the AI still used the raw codes in {len(ai)} of {len(rows)}
requests.</li>
<li><strong>The reference had bugs too.</strong> Its product search showed at most 60 products, so for big brands it
quietly left some out. Differential testing finds problems on both sides.</li>
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
          f"{len(rows)} requests: {len(same)} identical month by month, {len(ai)} AI-written queries wrong, "
          f"{len(ref)} reference bugs. Details and both queries: docs/differential.html.\n",
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
