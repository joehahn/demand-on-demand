"""The agent's lookup tools, all read-only. The only way the agent affects a forecast is the query it submits
(submit_query in dod/agent.py), which fixed code checks and wraps in its own sums. Results are compact text, because
they go back into the model's context."""
import re

from . import db
from .sqlcheck import check_sql

MAX_ROWS = 100
TEST_SECONDS = 5    # a test query only needs to show the logic works; the full query is run later by fixed code


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
    if kind == "store":   # the list is capped at 40: say so, so a partial list is never mistaken for all of them
        n = db.query(f"SELECT count(*) AS n FROM sales.store WHERE {match}", params).n[0]
        if n > 40:
            out += f"\n({n} stores match; the 40 most recent are shown.)"
    if kind == "item":   # the list is capped at 60: say so, and how to include every match
        n = db.query(f"SELECT count(DISTINCT i.family_item_no) AS n FROM sales.item i JOIN sales.item h "
                     f"ON h.item_no = i.family_item_no WHERE {match}", params).n[0]
        if n > 60:
            out += (f"\n({n} products match; the 60 largest are shown. To include every product matching these "
                    f"words, select them by name in SQL (rule 2), not from this list.)")
    return out


def run_select(sql):
    sql = sql.strip().rstrip(";")
    problem = check_sql(sql)
    if problem:
        return f"Error: rejected ({problem}). Write one SELECT over sales, ref or meta, schema-qualified."
    try:
        return as_text(db.query(f"SELECT * FROM ({sql}) q LIMIT {MAX_ROWS + 1}", timeout=f"{TEST_SECONDS}s"))
    except Exception as e:  # database errors go back to the model so it can correct its query
        if "statement timeout" in str(e):
            return (f"Error: too slow to test (over {TEST_SECONDS} seconds). Test a smaller slice instead (one recent "
                    f"month, one store or one product), or submit: fixed code runs the full query without this limit.")
        return f"Error: {str(e).splitlines()[0]}"


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
                    f"schema-qualified). Returns at most {MAX_ROWS} rows and stops after {TEST_SECONDS} seconds. Use it to test parts of your query (add "
                    "things up: only 100 rows come back) and to check facts the other tools do not give you (e.g. "
                    "which counties are largest).",
     "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}},
                      "required": ["sql"], "additionalProperties": False},
     "strict": True},
    {"name": "ask_user",
     "description": "Ask the requester one short clarifying question when the request is genuinely ambiguous and a "
                    "wrong guess would change the answer (e.g. a city vs its county). Do not ask about defaults.",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}},
                      "required": ["question"], "additionalProperties": False},
     "strict": True}
]
