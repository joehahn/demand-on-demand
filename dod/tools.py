"""The agent's tools. Every one is read-only; the only way the agent affects a forecast is the spec it submits,
which the harness validates and runs. Results are compact text, because they go back into the model's context."""
import json
import re
from pydantic import ValidationError

from . import db, panel
from .spec import Spec
from .sqlcheck import check_sql

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


# Search the small dimension tables; per-code dates come from index lookups (min/max on (code, date)).
FIND_SQL = {
    "item": """
        SELECT h.item_no, h.item_desc, h.bottle_volume_ml AS ml, h.pack, c.category_name, v.vendor_name,
               min(i.first_order_on) AS first_order, max(i.last_order_on) AS last_order, sum(i.total_bottles) AS bottles
        FROM sales.item i JOIN sales.item h ON h.item_no = i.family_item_no
        LEFT JOIN sales.category c ON c.category_code = h.category_current LEFT JOIN sales.vendor v ON v.vendor_no = h.vendor_no
        WHERE {match} GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY bottles DESC NULLS LAST LIMIT 60""",
    "category": """
        SELECT c.category_code, c.category_name, count(*) AS items, min(i.first_order_on) AS first_order,
               max(i.last_order_on) AS last_order, sum(i.total_bottles) AS bottles
        FROM sales.category c JOIN sales.item i ON i.category_current = c.category_code
        WHERE {match} GROUP BY 1, 2 ORDER BY bottles DESC NULLS LAST LIMIT 40""",
    "vendor": """
        WITH m AS (SELECT vendor_no, vendor_name FROM sales.vendor WHERE {match})
        SELECT m.*, (SELECT count(*) FROM sales.item i WHERE i.vendor_no = m.vendor_no) AS items,
               (SELECT max(ordered_on) FROM sales.invoice_line l WHERE l.vendor_no = m.vendor_no) AS last_order
        FROM m ORDER BY items DESC LIMIT 40""",
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
FIND_COLUMN = {"item": "h.item_desc", "category": "c.category_name", "vendor": "vendor_name",
               "city": "city", "county": "county_name", "store": "store_name"}


def name_match(col, text, prefix="w"):
    """SQL condition and parameters: every search word of `text` appears in the name column (punctuation ignored)."""
    words = _tokens(text)
    cond = " AND ".join(f"{_canonical(col)} LIKE %({prefix}{n})s" for n in range(len(words)))
    return cond, {f"{prefix}{n}": f"%{w}%" for n, w in enumerate(words)}


def find_values(kind, text):
    if kind not in FIND_SQL or not _tokens(text):
        return "Error: kind must be one of item, category, vendor, city, county, store, and text must contain a word."
    match, params = name_match(FIND_COLUMN[kind], text)
    out = as_text(db.query(FIND_SQL[kind].format(match=match), params))
    if kind == "item":   # the list is capped at 60: say so, and how to include every match
        n = db.query(f"SELECT count(DISTINCT i.family_item_no) AS n FROM sales.item i JOIN sales.item h "
                     f"ON h.item_no = i.family_item_no WHERE {match}", params).n[0]
        if n > 60:
            out += (f"\n({n} products match; the 60 largest are shown. To include every product matching these "
                    f"words, use product kind \"name\" with codes [\"{text}\"].)")
    return out


def run_select(sql):
    sql = sql.strip().rstrip(";")
    problem = check_sql(sql)
    if problem:
        return f"Error: rejected ({problem}). Write one SELECT over sales, ref or meta, schema-qualified."
    try:
        return as_text(db.query(f"SELECT * FROM ({sql}) q LIMIT {MAX_ROWS + 1}"))
    except Exception as e:  # database errors go back to the model so it can correct its query
        return f"Error: {str(e).splitlines()[0]}"


def parse_spec(spec_json):
    try:
        return Spec(**json.loads(spec_json)), None
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        return None, f"Error: invalid spec: {e}"


def preview(spec_json):
    """Build the monthly series for a draft spec, without training anything."""
    spec, err = parse_spec(spec_json)
    if err:
        return err, None
    try:
        p = panel.build(spec)
    except ValueError as e:
        return f"Error: {e}", None
    lines = [f"Last complete month {p.series.index[-1]:%Y-%m}; {p.series.shape[1]} series."]
    if spec.product.kind == "name":   # show what the brand words matched, so an overreach is visible before submitting
        heads = db.query("SELECT DISTINCT h.item_desc, h.total_bottles FROM sales.item i JOIN sales.item h "
                         "ON h.item_no = i.family_item_no WHERE i.item_no = ANY(%s) ORDER BY 2 DESC NULLS LAST",
                         (panel.member_items(spec),))
        lines.append(f"Product name matches {len(heads)} products, largest: " + "; ".join(heads.item_desc.head(8)))
    for c in p.series:
        s = p.series[c].dropna()
        nz = s[s > 0]
        if nz.empty:
            lines.append(f"- {c}: no sales")
            continue
        months = len(s)
        lines.append(f"- {c} ({p.labels.get(c, c)}): {months} months of history from {s.index[0]:%Y-%m}, "
                     f"last sale {nz.index.max():%Y-%m}, last 12 months {s.iloc[-12:].sum():,.0f}"
                     + (" -- under 24 months, too short to forecast" if months < 24 else ""))
    return "\n".join(lines), spec


TOOLS = [
    {"name": "find_values",
     "description": "Fuzzy-search warehouse names to resolve business words to codes: products (one row per product, "
                    "with size, category, vendor, dates and bottles sold), categories, vendors, cities, counties or "
                    "stores, largest first. Use short words (kind=item, text='titos mini'); search again with other "
                    "words if nothing fits.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["item", "category", "vendor", "city", "county", "store"]},
         "text": {"type": "string"}}, "required": ["kind", "text"], "additionalProperties": False},
     "strict": True},
    {"name": "run_select",
     "description": "Run one read-only SELECT against the sales, ref or meta schemas (tables must be "
                    f"schema-qualified). Returns at most {MAX_ROWS} rows. Use it only to check a fact the other "
                    "tools do not give you (e.g. which counties are largest).",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}},
                      "required": ["sql"], "additionalProperties": False},
     "strict": True},
    {"name": "preview_spec",
     "description": "Validate a draft spec (JSON string) and summarize the monthly series it produces: months of "
                    "history, last sale, last 12 months. Nothing is trained. Use it to confirm the spec matches the "
                    "request before submitting.",
     "input_schema": {"type": "object", "properties": {"spec_json": {"type": "string"}},
                      "required": ["spec_json"], "additionalProperties": False},
     "strict": True},
    {"name": "ask_user",
     "description": "Ask the requester one short clarifying question when the request is genuinely ambiguous and a "
                    "wrong guess would change the answer (e.g. a city vs its county). Do not ask about defaults.",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}},
                      "required": ["question"], "additionalProperties": False},
     "strict": True},
    {"name": "submit_spec",
     "description": "Submit the final spec (JSON string) for training, backtesting and the dashboard, with the "
                    "assumptions you made in plain English.",
     "input_schema": {"type": "object", "properties": {
         "spec_json": {"type": "string"},
         "assumptions": {"type": "array", "items": {"type": "string"}}},
         "required": ["spec_json", "assumptions"], "additionalProperties": False},
     "strict": True},
]
