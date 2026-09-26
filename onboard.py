"""
onboard.py: Act 1 of the demo. Claude reads the warehouse profile and drafts a known-issues register;
a human approves entries into meta.known_issues.

    python onboard.py                      # draft: profile -> Claude -> verify evidence -> out/onboarding/
    python onboard.py --dry-run            # build and save the prompt only, no API call
    python onboard.py --review             # list the drafted issues and their evidence checks
    python onboard.py --approve all        # write every verified warehouse-level issue to meta.known_issues
    python onboard.py --approve id1,id2    # write only these issues

Needs: explore_data.py run first (its cached profiling results are the evidence), ANTHROPIC_API_KEY in .env.
Claude never touches the database here. Its evidence SQL is re-run by this script under the read-only
dod_agent role, so every claim in the register is checked before a human sees it.
"""
import json
import os
import sys
import time
from pathlib import Path

import anthropic
import pandas as pd
import psycopg
import sqlglot
from dotenv import load_dotenv
from sqlglot import exp

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
CACHE = ROOT / "cache" / "explore"
OUT = ROOT / "out" / "onboarding"

MODEL = os.environ.get("DOD_ONBOARD_MODEL", "claude-opus-5")
PRICES = {"claude-opus-5": (5.00, 25.00), "claude-sonnet-5": (2.00, 10.00),
          "claude-opus-4-8": (5.00, 25.00)}  # $ per 1M input / output tokens
AGENT_SCHEMAS = {"sales", "ref", "meta"}   # what the read-only agent role can see

# The harness's closed vocabulary of fixes. Claude must pick one; it cannot invent code.
MITIGATIONS = {
    "etl_fixed": "Already handled by the loader; recorded for lineage. No action at forecast time.",
    "min_date": "Start affected series on or after a date. params: {\"date\": \"YYYY-MM-DD\"}",
    "derive_price": "Compute unit price as sales_dollars / sales_bottles instead of using a price column.",
    "exclude_zero_lines": "Drop lines with sales_bottles <= 0 or sales_dollars <= 0 before aggregating.",
    "use_line_id": "Count and key order lines by line_id, never by invoice_id.",
    "normalize_values": "Map variant spellings to one canonical value. params: {\"column\": ..., \"mapping\": {variant: canonical}}",
    "stitch_successor": "Treat a new code as the continuation of an old one. params: {\"column\": ..., \"from\": ..., \"to\": ...}",
    "carry_forward_reference": "Reference data lags; carry the latest published value forward to later periods.",
    "cap_outliers": "Winsorize monthly values beyond k median absolute deviations. params: {\"k\": 5}",
    "flag_only": "No automatic fix; show the issue on the dashboard so a human can judge it.",
}

ISSUE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string", "description": "short snake_case slug"},
                    "title": {"type": "string"},
                    "level": {"type": "string", "enum": ["warehouse", "request_specific"]},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "scope_tables": {"type": "array", "items": {"type": "string"}},
                    "scope_columns": {"type": "array", "items": {"type": "string"}},
                    "date_from": {"type": "string", "description": "YYYY-MM-DD or empty"},
                    "date_to": {"type": "string", "description": "YYYY-MM-DD or empty"},
                    "description": {"type": "string"},
                    "impact_on_forecasting": {"type": "string"},
                    "evidence_sql": {"type": "string", "description": "one SELECT over sales/ref/meta, or empty"},
                    "mitigation_rule": {"type": "string", "enum": list(MITIGATIONS)},
                    "mitigation_params_json": {"type": "string", "description": "JSON object, or {}"},
                },
                "required": ["issue_id", "title", "level", "severity", "scope_tables", "scope_columns",
                             "date_from", "date_to", "description", "impact_on_forecasting",
                             "evidence_sql", "mitigation_rule", "mitigation_params_json"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["issues"],
    "additionalProperties": False,
}

SYSTEM = f"""You are the data engineer onboarding a new data source into a small company's sales warehouse.
Before anyone uses it for demand forecasting, you write the known-issues register: the data-quality
problems a forecaster must know about, each with evidence and a fix.

The warehouse is Postgres. Forecasts are monthly totals of sales_bottles, sales_dollars or sales_liters
for some product scope (item, vendor, category, or everything) and some region scope (store, city,
county, or statewide), from sales.invoice_line joined to the dimension and reference tables.

For each issue:
- level = "warehouse" when it affects many requests and a data team would reasonably know it
  (taxonomy changes, missing columns, id semantics, source-system changes, reference-data lags).
  level = "request_specific" when it only matters for particular items, stores or places
  (one product renumbered, one city spelled two ways). Only warehouse issues go into the register;
  request_specific ones are left for the forecasting agent to discover on its own, so list them but
  keep them brief.
- evidence_sql must be ONE read-only SELECT that runs against the schemas sales, ref and meta only
  (the forecasting agent cannot read raw.*), with every table schema-qualified (sales.item, not item). Keep it cheap: aggregate, and never return more than
  about 50 rows. Leave it empty only when the evidence exists solely in raw data.
- mitigation_rule must be one of these, exactly:
{chr(10).join(f"  {k}: {v}" for k, v in MITIGATIONS.items())}
- Be specific: dates, codes, columns, magnitudes taken from the evidence. Do not invent facts that are
  not supported by the evidence you were given; if something is a hypothesis, say so."""


# ---------------------------------------------------------------- evidence

def schema_text(conn):
    """Tables, columns, types and comments the agent can see."""
    rows = conn.execute("""
        SELECT c.table_schema, c.table_name, c.column_name, c.data_type,
               col_description((c.table_schema || '.' || c.table_name)::regclass, c.ordinal_position),
               obj_description((c.table_schema || '.' || c.table_name)::regclass)
        FROM information_schema.columns c
        WHERE c.table_schema IN ('sales', 'ref', 'meta') AND c.table_name <> 'known_issues'
        ORDER BY 1, 2, c.ordinal_position""").fetchall()
    out, last = [], None
    for schema, table, col, dtype, ccomment, tcomment in rows:
        if (schema, table) != last:
            out.append(f"\n{schema}.{table}: {tcomment or ''}")
            last = (schema, table)
        out.append(f"  {col} {dtype}" + (f"  -- {ccomment}" if ccomment else ""))
    return "\n".join(out)


def reference_coverage(conn):
    rows = conn.execute("""
        SELECT 'ref.county_population', min(year), max(year) FROM ref.county_population
        UNION ALL SELECT 'ref.county_income', min(year), max(year) FROM ref.county_income
        UNION ALL SELECT 'sales.invoice_line (ordered_on)', min(extract(year FROM ordered_on))::int,
                         max(extract(year FROM ordered_on))::int FROM sales.invoice_line""").fetchall()
    return "\n".join(f"  {t}: {a} to {b}" for t, a, b in rows)


ETL_NOTES = """Loader notes (what load_data.py did between raw.liquor_sales and sales.*):
- raw.liquor_sales holds 27,947,018 rows exactly as published. sales.invoice_line holds 26,434,053:
  1,512,965 exact duplicate rows were dropped. The duplicates sit in the 2022, 2025 and 2026 yearly
  exports (repeated verbatim across CSV parts); the portal's own 2026 row count matches the distinct count.
- line_id is a new surrogate key; invoice_id is not unique.
- Dimension tables (store, item, vendor, category) keep each code's most recently recorded attributes.
- Blank text became NULL; numbers and dates were typed. Nothing else was cleaned."""


def evidence_text():
    """Everything Claude gets: schema, coverage, loader notes, and the cached profiling results."""
    if not CACHE.exists():
        sys.exit("No profiling cache; run `python explore_data.py` first.")
    with psycopg.connect(os.environ["DOD_OWNER_DSN"]) as conn:
        parts = ["# Schema visible to the forecasting agent", schema_text(conn),
                 "\n# Date coverage", reference_coverage(conn), "\n# " + ETL_NOTES,
                 "\n# Profiling results (from explore_data.py)"]
    for path in sorted(CACHE.glob("*.parquet")):
        df = pd.read_parquet(path)
        if path.stem == "monthly":  # 128 rows; the yearly shape is what matters
            df = df.assign(year=pd.to_datetime(df.month).dt.year).groupby("year").sum(numeric_only=True).reset_index()
        parts.append(f"\n## {path.stem}\n{df.to_string(index=False, max_rows=60)}")
    return "\n".join(parts)


# ---------------------------------------------------------------- Claude

def draft(evidence):
    client = anthropic.Anthropic()
    user = (f"{evidence}\n\nDraft the known-issues register for this warehouse. Cover every data-quality "
            "problem the evidence supports that could distort a monthly demand forecast.")
    t0 = time.time()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": ISSUE_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if a safety classifier declines, the API retries on a recommended model
    ) as stream:
        msg = stream.get_final_message()
    (OUT / "raw_response.json").write_text(msg.to_json())  # keep what we paid for before any parsing
    if msg.stop_reason == "refusal":
        sys.exit(f"Claude declined the request ({msg.stop_details}); nothing drafted.")
    if msg.stop_reason == "max_tokens":
        sys.exit("Response hit max_tokens before the JSON was complete; nothing drafted.")
    text = next(b.text for b in msg.content if b.type == "text")
    pin, pout = PRICES.get(msg.model, PRICES["claude-opus-5"])
    usage = {"model": msg.model, "seconds": round(time.time() - t0, 1),
             "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens,
             "est_cost_usd": round((msg.usage.input_tokens * pin + msg.usage.output_tokens * pout) / 1e6, 4),
             "message_id": msg.id}
    return json.loads(text)["issues"], usage


# ---------------------------------------------------------------- verification

def check_sql(sql):
    """Allow exactly one SELECT whose tables all live in schemas the agent can read."""
    try:
        stmts = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        return f"does not parse: {str(e).splitlines()[0]}"
    if len(stmts) != 1 or not isinstance(stmts[0], (exp.Select, exp.Union, exp.With)) and stmts[0].find(exp.Select) is None:
        return "not a single SELECT"
    if any(stmts[0].find(t) for t in (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter)):
        return "contains a write"
    ctes = {c.alias for c in stmts[0].find_all(exp.CTE)}
    for table in stmts[0].find_all(exp.Table):
        if table.name in ctes:
            continue
        if table.db not in AGENT_SCHEMAS:
            return f"reads {table.db or '(no schema)'}.{table.name}, outside sales/ref/meta"
    return None


def verify(issues):
    """Run each evidence query as the read-only agent role and record what came back."""
    with psycopg.connect(os.environ["DOD_AGENT_DSN"], autocommit=True) as conn:
        for issue in issues:
            sql = issue["evidence_sql"].strip().rstrip(";")
            if not sql:
                issue["evidence_check"] = {"status": "none", "note": "no evidence query (raw-only evidence)"}
                continue
            problem = check_sql(sql)
            if problem:
                issue["evidence_check"] = {"status": "rejected", "note": problem}
                continue
            try:
                t0 = time.time()
                cur = conn.execute(f"SELECT * FROM ({sql}) evidence LIMIT 50")
                rows = cur.fetchall()
                cols = [d.name for d in cur.description]
                issue["evidence_check"] = {"status": "ran", "seconds": round(time.time() - t0, 1),
                                           "rows": len(rows), "columns": cols,
                                           "sample": [[str(v) for v in r] for r in rows[:5]]}
            except psycopg.Error as e:
                issue["evidence_check"] = {"status": "error", "note": str(e).splitlines()[0]}
            try:
                json.loads(issue["mitigation_params_json"] or "{}")
            except json.JSONDecodeError:
                issue["evidence_check"]["params_note"] = "mitigation_params_json is not valid JSON"
    return issues


# ---------------------------------------------------------------- review and approval

def review():
    issues = json.loads((OUT / "proposed_register.json").read_text())["issues"]
    for level in ("warehouse", "request_specific"):
        print(f"\n== {level} ({sum(i['level'] == level for i in issues)})")
        for i in issues:
            if i["level"] != level:
                continue
            chk = i["evidence_check"]
            print(f"- {i['issue_id']} [{i['severity']}] {i['title']}")
            print(f"    fix: {i['mitigation_rule']} {i['mitigation_params_json']}")
            print(f"    evidence: {chk['status']}" + (f" ({chk.get('rows')} rows)" if chk["status"] == "ran" else f" ({chk.get('note', '')})"))


REGISTER_DDL = """
CREATE TABLE IF NOT EXISTS meta.known_issues (
    issue_id text PRIMARY KEY, title text, severity text, scope_tables text[], scope_columns text[],
    date_from date, date_to date, description text, impact_on_forecasting text, evidence_sql text,
    mitigation_rule text, mitigation_params jsonb, status text, drafted_by text, approved_at timestamptz)"""


def approve(which):
    doc = json.loads((OUT / "proposed_register.json").read_text())
    chosen = [i for i in doc["issues"] if i["level"] == "warehouse" and (which == "all" or i["issue_id"] in which)]
    # evidence that failed, was rejected, or came back empty never rides along with --approve all;
    # an empty result can still be approved by naming the issue explicitly
    def ok(i):
        chk = i["evidence_check"]
        if chk["status"] in ("rejected", "error"):
            return False
        return which != "all" or not (chk["status"] == "ran" and chk["rows"] == 0)
    blocked = [i["issue_id"] for i in chosen if not ok(i)]
    chosen = [i for i in chosen if i["issue_id"] not in blocked]
    with psycopg.connect(os.environ["DOD_OWNER_DSN"], autocommit=True) as conn:
        conn.execute(REGISTER_DDL)
        conn.execute("COMMENT ON TABLE meta.known_issues IS 'Known data-quality issues, approved by a human, "
                     "with evidence queries and the harness rule that mitigates each one.'")
        for i in chosen:
            conn.execute("""
                INSERT INTO meta.known_issues VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'approved',%s,now())
                ON CONFLICT (issue_id) DO UPDATE SET title=EXCLUDED.title, severity=EXCLUDED.severity,
                  scope_tables=EXCLUDED.scope_tables, scope_columns=EXCLUDED.scope_columns,
                  date_from=EXCLUDED.date_from, date_to=EXCLUDED.date_to, description=EXCLUDED.description,
                  impact_on_forecasting=EXCLUDED.impact_on_forecasting, evidence_sql=EXCLUDED.evidence_sql,
                  mitigation_rule=EXCLUDED.mitigation_rule, mitigation_params=EXCLUDED.mitigation_params,
                  drafted_by=EXCLUDED.drafted_by, approved_at=now()""",
                (i["issue_id"], i["title"], i["severity"], i["scope_tables"], i["scope_columns"],
                 i["date_from"] or None, i["date_to"] or None, i["description"], i["impact_on_forecasting"],
                 i["evidence_sql"], i["mitigation_rule"], i["mitigation_params_json"] or "{}", doc["usage"]["model"]))
    print(f"approved {len(chosen)} issue(s) into meta.known_issues")
    if blocked:
        print(f"not approved, evidence failed: {', '.join(blocked)}")


def write_review_md(doc):
    """A readable review sheet for the human approver."""
    lines = [f"# Proposed known-issues register\n\nDrafted by `{doc['usage']['model']}` in "
             f"{doc['usage']['seconds']}s, {doc['usage']['input_tokens']:,} in / {doc['usage']['output_tokens']:,} "
             f"out tokens, about ${doc['usage']['est_cost_usd']:.2f}.\n"]
    for level in ("warehouse", "request_specific"):
        lines.append(f"\n## {level}\n")
        for i in doc["issues"]:
            if i["level"] != level:
                continue
            chk = i["evidence_check"]
            lines += [f"### {i['issue_id']}: {i['title']}",
                      f"- severity: {i['severity']}; scope: {', '.join(i['scope_tables'])} "
                      f"[{', '.join(i['scope_columns'])}]; dates: {i['date_from'] or '-'} to {i['date_to'] or '-'}",
                      f"- {i['description']}", f"- impact: {i['impact_on_forecasting']}",
                      f"- fix: `{i['mitigation_rule']}` {i['mitigation_params_json']}",
                      f"- evidence check: **{chk['status']}** {chk.get('note', '')}"]
            if i["evidence_sql"]:
                lines += ["```sql", i["evidence_sql"].strip(), "```"]
            if chk["status"] == "ran":
                lines.append("first rows: " + "; ".join(", ".join(r) for r in chk["sample"]))
            lines.append("")
    (OUT / "review.md").write_text("\n".join(lines))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    if "--review" in args:
        review()
    elif "--approve" in args:
        which = args[args.index("--approve") + 1]
        approve("all" if which == "all" else set(which.split(",")))
    else:
        evidence = evidence_text()
        (OUT / "prompt.txt").write_text(SYSTEM + "\n\n---\n\n" + evidence)
        print(f"evidence: {len(evidence):,} characters -> {OUT.relative_to(ROOT)}/prompt.txt")
        if "--dry-run" in args:
            sys.exit(0)
        issues, usage = draft(evidence)
        print(f"{usage['model']}: {len(issues)} issues in {usage['seconds']}s, about ${usage['est_cost_usd']:.2f}")
        doc = {"usage": usage, "issues": verify(issues)}
        (OUT / "proposed_register.json").write_text(json.dumps(doc, indent=2))
        write_review_md(doc)
        review()
        print(f"\nreview sheet: {OUT.relative_to(ROOT)}/review.md; approve with --approve all or --approve id1,id2")
