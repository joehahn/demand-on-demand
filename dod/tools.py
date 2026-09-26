"""The agent's tools. Every one is read-only; the only way the agent changes anything is by submitting a
spec, which the harness validates and runs. Results are compact text, because they go back into the
model's context."""
import json
import re
from pathlib import Path

from pydantic import ValidationError

from . import checks, db, panel, register
from .spec import Spec
from .sqlcheck import check_sql

ROOT = Path(__file__).parent.parent
MAX_ROWS = 100


def as_text(df, max_rows=MAX_ROWS):
    if df.empty:
        return "(no rows)"
    more = f"\n... {len(df) - max_rows} more rows" if len(df) > max_rows else ""
    return df.head(max_rows).to_string(index=False) + more


ABBREVIATIONS = {"MT": "MOUNT", "ST": "SAINT", "FT": "FORT"}  # common in place names, both directions


def _tokens(text):
    """Search words: letters and digits only, a trailing plural 's' dropped ("Tito's minis" -> tito, mini),
    place-name abbreviations expanded ("Mt Pleasant" -> mount, pleasant)."""
    words = re.sub(r"[^A-Za-z0-9 ]", "", text).upper().split()
    words = [ABBREVIATIONS.get(w, w) for w in words]
    return [w[:-1] if len(w) > 3 and w.endswith("S") else w for w in words]


def _canonical(col):
    """SQL for a name with punctuation removed and place-name abbreviations expanded, so MT PLEASANT
    and MOUNT PLEASANT both match a search for either."""
    expr = f"regexp_replace(upper({col}), '[^A-Z0-9 ]', '', 'g')"
    for short, full in ABBREVIATIONS.items():
        expr = f"regexp_replace({expr}, '(^| ){short}( |$)', '\\1{full}\\2', 'g')"
    return expr


FIND_SQL = {
    "item": """
        SELECT i.item_no, i.item_desc, i.bottle_volume_ml AS ml, i.pack, c.category_name, v.vendor_name,
               min(l.ordered_on) AS first_order, max(l.ordered_on) AS last_order, sum(l.sales_bottles) AS bottles
        FROM sales.item i
        LEFT JOIN sales.category c USING (category_code) LEFT JOIN sales.vendor v USING (vendor_no)
        LEFT JOIN sales.invoice_line l ON l.item_no = i.item_no
        WHERE {match} GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY bottles DESC NULLS LAST LIMIT 60""",
    "category": """
        SELECT c.category_code, c.category_name, min(l.ordered_on) AS first_order, max(l.ordered_on) AS last_order,
               count(*) AS lines
        FROM sales.category c JOIN sales.invoice_line l USING (category_code)
        WHERE {match} GROUP BY 1, 2 ORDER BY lines DESC LIMIT 40""",
    "vendor": """
        SELECT vendor_no, vendor_name FROM sales.vendor WHERE {match} ORDER BY vendor_name LIMIT 40""",
    "city": """
        SELECT city, county_name, county_fips, count(*) AS stores, min(first_order_on) AS first_order,
               max(last_order_on) AS last_order
        FROM sales.store WHERE {match} GROUP BY 1, 2, 3 ORDER BY stores DESC LIMIT 40""",
    "county": """
        SELECT county_fips, county_name, count(*) AS stores FROM sales.store WHERE {match}
        GROUP BY 1, 2 ORDER BY stores DESC LIMIT 40""",
    "store": """
        SELECT store_no, store_name, city, county_name, first_order_on, last_order_on FROM sales.store
        WHERE {match} ORDER BY last_order_on DESC LIMIT 40""",
}
FIND_COLUMN = {"item": "i.item_desc", "category": "c.category_name", "vendor": "vendor_name",
               "city": "city", "county": "county_name", "store": "store_name"}


def find_values(kind, text):
    words = _tokens(text)
    if kind not in FIND_SQL or not words:
        return "Error: kind must be one of item, category, vendor, city, county, store, and text must contain a word."
    col = _canonical(FIND_COLUMN[kind])
    match = " AND ".join(f"{col} LIKE %(w{n})s" for n in range(len(words)))
    params = {f"w{n}": f"%{w}%" for n, w in enumerate(words)}
    return as_text(db.query(FIND_SQL[kind].format(match=match), params))


def run_select(sql):
    sql = sql.strip().rstrip(";")
    problem = check_sql(sql)
    if problem:
        return f"Error: rejected ({problem}). Write one SELECT over sales, ref or meta, schema-qualified."
    try:
        return as_text(db.query(f"SELECT * FROM ({sql}) q LIMIT {MAX_ROWS + 1}"))
    except Exception as e:  # database errors go back to the model so it can correct its query
        return f"Error: {str(e).splitlines()[0]}"


def parse_spec(spec_json, source="agent"):
    try:
        spec = Spec(**json.loads(spec_json))
        for m in spec.mitigations:  # record who chose each fix, whatever the model wrote
            m.source = source
        return spec, None
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        return None, f"Error: invalid spec: {e}"


def preview(spec_json):
    """Build the monthly series and run the slice checks, without training anything."""
    spec, err = parse_spec(spec_json)
    if err:
        return err, None
    decisions = register.assess(spec, register.load())
    try:
        p = panel.build(spec, decisions)
    except ValueError as e:
        return f"Error: {e}", None
    findings = checks.run(spec, p)
    lines = [f"Series start {p.start}, last complete month {p.series.index[-1]:%Y-%m}, {len(p.series)} months."]
    for c in p.series:
        s = p.series[c].dropna()
        nz = s[s > 0]
        lines.append(f"- {c} ({p.labels.get(c, c)}): first sale {nz.index.min():%Y-%m}, last sale "
                     f"{nz.index.max():%Y-%m}, last 12 months {s.iloc[-12:].sum():,.0f}" if len(nz) else f"- {c}: no sales")
    lines.append("Register decisions:")
    lines += [f"- {d['issue_id']}: {d['action']} ({d['note']})" for d in decisions if d["action"] != "not_relevant"]
    lines.append("Slice findings:" if findings else "Slice findings: none")
    for f in findings:
        fix = f"{f['suggested_rule']} {json.dumps(f['suggested_params'])}" if f["suggested_rule"] else "none"
        lines.append(f"- [{f['severity']}] {f['check']} ({f['series']}): {f['message']} Suggested fix: {fix}. "
                     + {"fixed": "Fixed by this spec.", "reviewed": "Reviewed in this spec and left as is.",
                        "no_effect": "", "open": ""}[f["resolution"]])
    for ch in p.changes:
        lines.append(f"Applied: {ch['rule']} {json.dumps(ch['params'])} {ch.get('note', '')}")
    return "\n".join(lines), spec


def propose_issue(issue):
    """Act 3: a warehouse-wide problem found during a request becomes a PROPOSED register entry for a human."""
    path = ROOT / "out" / "proposed_issues.jsonl"
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(issue) + "\n")
    return f"Recorded as a proposal in {path.relative_to(ROOT)}; a human reviews it before it enters the register."


TOOLS = [
    {"name": "find_values",
     "description": "Fuzzy-search warehouse names to resolve business words to codes. Returns matching rows with "
                    "codes, names, sizes and sales volume, largest first. Search one kind at a time with short words "
                    "(e.g. kind=item, text='titos mini'); search again with other words if nothing fits.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["item", "category", "vendor", "city", "county", "store"]},
         "text": {"type": "string"}}, "required": ["kind", "text"], "additionalProperties": False},
     "strict": True},
    {"name": "run_select",
     "description": "Run one read-only SELECT against the sales, ref or meta schemas (tables must be "
                    f"schema-qualified). Returns at most {MAX_ROWS} rows. Use it to check facts, not to aggregate the "
                    "forecast series; the harness builds those itself.",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}},
                      "required": ["sql"], "additionalProperties": False},
     "strict": True},
    {"name": "preview_spec",
     "description": "Validate a draft spec (JSON string), build its monthly series, apply the register, and run the "
                    "slice checks. Returns series summaries, register decisions and findings with suggested fixes. "
                    "Nothing is trained. Call it before submit_spec, and again after adding mitigations.",
     "input_schema": {"type": "object", "properties": {"spec_json": {"type": "string"}},
                      "required": ["spec_json"], "additionalProperties": False},
     "strict": True},
    {"name": "ask_user",
     "description": "Ask the requester one short clarifying question when the request is genuinely ambiguous and a "
                    "wrong guess would change the answer (e.g. a city vs its county). Do not ask about defaults.",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}},
                      "required": ["question"], "additionalProperties": False},
     "strict": True},
    {"name": "propose_register_issue",
     "description": "Propose a WAREHOUSE-WIDE data problem you discovered (one that would affect many requests) for "
                    "the known-issues register. A human decides. Do not use this for problems specific to one item or place.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "description": {"type": "string"}, "evidence_sql": {"type": "string"},
         "suggested_rule": {"type": "string"}}, "required": ["title", "description", "evidence_sql", "suggested_rule"],
         "additionalProperties": False},
     "strict": True},
    {"name": "submit_spec",
     "description": "Submit the final spec (JSON string) for training, backtesting and the dashboard. Include every "
                    "mitigation you chose, each with a one-line reason. List the assumptions you made in plain English.",
     "input_schema": {"type": "object", "properties": {
         "spec_json": {"type": "string"},
         "assumptions": {"type": "array", "items": {"type": "string"}}},
         "required": ["spec_json", "assumptions"], "additionalProperties": False},
     "strict": True},
]
